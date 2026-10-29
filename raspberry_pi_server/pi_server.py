
"""MobleKurly phase-1 TCP server.

MFC protocol (UTF-8 newline terminated):
  PING|-|MFC-1             -> PONG|MFC-1
  DISPATCH_ORDER|7|MFC-2  -> ACK|MFC-2|QUEUED
  STATUS|-|MFC-3          -> ACK|MFC-3|IDLE/RUNNING

ACK means queued, NOT physically dispensed.
"""

import json
from contextlib import nullcontext
import logging
import pathlib
import queue
import socketserver
import subprocess
import sys
import threading
import time

import pymysql

# [ESTOP] 주문/DB/카메라와 독립된 아두이노 제어 연결
from conveyor_control import ConveyorController


CONFIG_FILE = pathlib.Path(__file__).with_name('pi_config.json')
CONFIG = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))

RUN_QUEUE = queue.Queue(maxsize=50)
ACTIVE = set()
STATE_LOCK = threading.Lock()
STATE = {'busy': False, 'message': 'IDLE'}

# One camera instance shared by inspection and MJPEG
CAMERA = None

# [ESTOP] USB는 주문마다 재연결하지 않고 서버 전체에서 한 번만 열어 둠.
CONVEYOR = None
CONVEYOR_LOCK = threading.Lock()


def get_conveyor():
    global CONVEYOR
    if CONFIG['dry_run']:
        raise RuntimeError('DRY_RUN_NO_HARDWARE')
    with CONVEYOR_LOCK:
        if CONVEYOR is None:
            CONVEYOR = ConveyorController(
                CONFIG['arduino_port'], int(CONFIG['arduino_baud']))
        return CONVEYOR


def sensor_db_worker():
    """Record Arduino DHT11 and reported FAN PWM output in sensor_logs.

    Arduino sends SENSOR first, followed by FAN on each measurement cycle;
    briefly wait for new FAN telemetry to avoid a one-cycle stale state.
    """
    last_unknown_warning = 0.0
    while True:
        try:
            controller = get_conveyor()
            temperature, humidity = controller.sensor_lines.get(timeout=3.0)
        except queue.Empty:
            continue
        except RuntimeError:
            time.sleep(3)
            continue

        received = time.monotonic()
        fan = controller.latest_fan_state(after=received, wait_seconds=0.8)
        # A reported state may be reused for a short period if FAN was
        # delayed/lost, but never trust stale telemetry indefinitely.
        if fan is not None and time.monotonic() - fan[0] <= 10.0:
            fan_on = int(fan[1] > 0)
        else:
            # Existing non-null schema requires a boolean. Preserve prior
            # behavior only when there is no recent FAN message, with a warning.
            fan_on = 0
            if time.monotonic() - last_unknown_warning >= 30.0:
                logging.warning('No fresh FAN telemetry: storing fan_on=0 (unknown)')
                last_unknown_warning = time.monotonic()

        try:
            connection = connect_db()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        'INSERT INTO sensor_logs (temperature, humidity, fan_on) '
                        'VALUES (%s, %s, %s)',
                        (temperature, humidity, fan_on)
                    )
                connection.commit()
            finally:
                connection.close()
            logging.info('DHT11: %.1f C / %.1f %%RH; fan_on=%d stored',
                         temperature, humidity, fan_on)
        except Exception:
            logging.exception('DHT11 database write failed; measurement discarded')


def fan_db_worker():
    """Record ON/OFF operating sessions in the existing fan_logs schema.

    A 50% or 100% PWM duty means ON; only the transition to 0% closes a
    run. A transition between 50% and 100% remains the same run.
    """
    last_on = None
    active_log_id = None
    while True:
        try:
            controller = get_conveyor()
            event = controller.fan_lines.get(timeout=3.0)
        except queue.Empty:
            continue
        except RuntimeError:
            time.sleep(3)
            continue

        _, speed, status, diff, base = event
        is_on = speed > 0
        if last_on is not None and is_on == last_on:
            continue
        temperature = (base + diff if base is not None and diff is not None
                       else None)
        if temperature is None:
            # Sensor error FAN events do not provide actual temperature.
            # The ON state is still captured in sensor_logs on next good read.
            logging.warning('Fan changed to %s but temperature unavailable', is_on)
            last_on = is_on
            continue
        # Thresholds correspond to the Arduino startup reference (not a
        # conventional hysteresis thermostat).
        on_threshold = base + 2.0
        off_threshold = base - 2.0
        try:
            con = connect_db()
            try:
                with con.cursor() as cur:
                    if is_on:
                        cur.execute("""INSERT INTO fan_logs
                            (started_at, start_temperature, on_threshold,
                             off_threshold, reason)
                            VALUES (NOW(), %s, %s, %s, %s)""",
                            (temperature, on_threshold, off_threshold,
                             'AUTO_PWM_' + str(speed)))
                        active_log_id = cur.lastrowid
                    elif active_log_id is not None:
                        cur.execute("""UPDATE fan_logs SET stopped_at=NOW(),
                            duration_seconds=GREATEST(0, TIMESTAMPDIFF(
                                SECOND, started_at, NOW())), stop_temperature=%s
                            WHERE fan_log_id=%s AND stopped_at IS NULL""",
                            (temperature, active_log_id))
                        active_log_id = None
                con.commit()
            finally:
                con.close()
            last_on = is_on
            logging.info('Fan changed: %s at %.1f C (%d%%, %s)',
                         'ON' if is_on else 'OFF', temperature, speed, status)
        except Exception:
            # Retry this fan transition when the next telemetry arrives.
            logging.exception('fan_logs write failed; will retry on next FAN event')


def conveyor_reply(command, argument, request_id):
    try:
        controller = get_conveyor()
        if command == 'EMERGENCY_STOP' and argument == '-':
            state = controller.stop()
        elif command == 'CONVEYOR_STATUS' and argument == '-':
            state = controller.status()
        elif (command == 'START_CONVEYOR' and argument.isascii()
              and argument.isdecimal() and len(argument) <= 10
              and int(argument) <= 0xFFFFFFFF):
            state = controller.start(int(argument))
        else:
            return f'ERR|{request_id}|BAD_COMMAND'
        return f'ACK|{request_id}|{state.payload()}'
    except RuntimeError as exc:
        logging.warning('Conveyor control rejected: %s', exc)
        return f'ERR|{request_id}|{exc}'


def connect_db():
    c = CONFIG['mysql']

    return pymysql.connect(
        host=c['host'],
        port=int(c['port']),
        user=c['user'],
        password=c['password'],
        database=c['database'],
        charset='utf8mb4',
        connect_timeout=3,
        read_timeout=3,
        autocommit=False
    )


def order_lines(order_id):
    '''Validate the entire order in item order (never group by color).'''
    con = connect_db()
    try:
        with con.cursor() as cur:
            cur.execute('SELECT status FROM orders WHERE order_id=%s', (order_id,))
            status = cur.fetchone()
            if not status or status[0] != 'PENDING':
                raise ValueError('ORDER_NOT_PENDING')
            cur.execute('''
                SELECT oi.item_id, p.color, oi.quantity - oi.shipped_qty
                FROM order_items oi JOIN products p ON p.product_id=oi.product_id
                WHERE oi.order_id=%s ORDER BY oi.item_id
            ''', (order_id,))
            rows = [(int(i), str(c), int(q)) for i,c,q in cur.fetchall()]
            if not rows or any(q <= 0 or q > 1000 or c not in FEED_DIGITS
                               for _,c,q in rows):
                raise ValueError('BAD_ORDER_ITEMS')
            return rows
    finally:
        con.close()

def begin_order(order_id):
    """Approve order and create waiting jobs."""

    con = connect_db()

    try:
        with con.cursor() as cur:
            cur.execute(
                """
                UPDATE orders
                SET
                    status = 'PROCESSING',
                    approved_at = COALESCE(approved_at, NOW())
                WHERE order_id = %s
                  AND status = 'PENDING'
                """,
                (order_id,)
            )

            if cur.rowcount != 1:
                con.rollback()
                return False

            cur.execute(
                '''
                SELECT item_id, quantity, shipped_qty
                FROM order_items
                WHERE order_id = %s
                ORDER BY item_id
                FOR UPDATE
                ''',
                (order_id,)
            )

            items = cur.fetchall()

            if not items or any(
                int(q) <= int(shipped)
                for _, q, shipped in items
            ):
                raise ValueError('INVALID_ORDER_ITEMS')

            for item_id, _, _ in items:
                cur.execute(
                    '''
                    INSERT INTO outbound_jobs
                    (item_id, status, retry_count, created_at)
                    VALUES (%s, 'WAITING', 0, NOW())
                    ''',
                    (item_id,)
                )

        con.commit()
        return True

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()


def claim_retry_order(order_id):
    '''Retry only unshipped item quantities; preserve historical failed jobs.'''
    con = connect_db()
    new_job_ids = []
    try:
        with con.cursor() as cur:
            cur.execute('SELECT status FROM orders WHERE order_id=%s FOR UPDATE', (order_id,))
            if cur.fetchone() != ('ERROR',):
                raise ValueError('ORDER_NOT_ERROR')
            cur.execute('''SELECT oi.item_id, oi.quantity, oi.shipped_qty, p.color
                FROM order_items oi JOIN products p ON p.product_id=oi.product_id
                WHERE oi.order_id=%s ORDER BY oi.item_id FOR UPDATE''', (order_id,))
            items = cur.fetchall()
            if not items:
                raise ValueError('NO_ORDER_ITEMS')
            cur.execute('''SELECT j.status,j.retry_count FROM outbound_jobs j
                JOIN order_items oi ON oi.item_id=j.item_id
                WHERE oi.order_id=%s FOR UPDATE''', (order_id,))
            old_jobs = cur.fetchall()
            if not old_jobs:
                raise ValueError('NO_FAILED_JOB_TO_RETRY')
            if any(status in ('RUNNING','WAITING') for status,_ in old_jobs):
                raise ValueError('UNFINISHED_JOB_EXISTS')
            if any(status not in ('RETRY_WAIT','DONE') for status,_ in old_jobs):
                raise ValueError('JOB_STATE_REVIEW_REQUIRED')
            next_retry = max(int(count) for _,count in old_jobs)+1
            rows = []
            for item_id,quantity,shipped,color in items:
                remaining = int(quantity)-int(shipped)
                if remaining < 0 or remaining > 1000 or color not in FEED_DIGITS:
                    raise ValueError('BAD_REMAINING_QUANTITY')
                if remaining:
                    rows.append((int(item_id),str(color),remaining))
                    cur.execute('''INSERT INTO outbound_jobs
                        (item_id,status,retry_count,created_at)
                        VALUES (%s,'WAITING',%s,NOW())''', (item_id,next_retry))
                    new_job_ids.append(int(cur.lastrowid))
            if not rows:
                raise ValueError('NOTHING_LEFT_TO_RETRY')
            cur.execute('''UPDATE orders SET status='PROCESSING',completed_at=NULL
                WHERE order_id=%s AND status='ERROR' ''', (order_id,))
            if cur.rowcount!=1:
                raise ValueError('RETRY_ORDER_CLAIM_FAILED')
        con.commit()
        return rows,new_job_ids
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def undo_retry_queue_claim(order_id, job_ids):
    """Compensate only new jobs if enqueue fails; no physical command sent."""
    if not job_ids:
        return
    con = connect_db()
    try:
        with con.cursor() as cur:
            cur.execute('SELECT status FROM orders WHERE order_id=%s FOR UPDATE', (order_id,))
            if cur.fetchone() != ('PROCESSING',):
                raise RuntimeError('RETRY_CLAIM_ROLLBACK_UNSAFE')
            placeholders = ','.join(['%s'] * len(job_ids))
            cur.execute("DELETE FROM outbound_jobs WHERE status='WAITING' AND job_id IN ("+placeholders+")", job_ids)
            if cur.rowcount != len(job_ids):
                raise RuntimeError('RETRY_CLAIM_ROLLBACK_INCOMPLETE')
            cur.execute("UPDATE orders SET status='ERROR' WHERE order_id=%s", (order_id,))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def set_job_status(order_id, status):
    '''State transition only for jobs with unshipped boxes.'''
    con = connect_db()
    try:
        with con.cursor() as cur:
            if status == 'RUNNING':
                cur.execute('''UPDATE outbound_jobs j
                    JOIN order_items oi ON j.item_id=oi.item_id
                    SET j.status='RUNNING', j.started_at=NOW()
                    WHERE oi.order_id=%s AND j.status='WAITING'
                    AND oi.shipped_qty < oi.quantity''', (order_id,))
                if cur.rowcount <= 0:
                    raise ValueError('NO_WAITING_JOBS')
            elif status == 'RETRY_WAIT':
                cur.execute('''UPDATE outbound_jobs j
                    JOIN order_items oi ON j.item_id=oi.item_id
                    SET j.status='RETRY_WAIT'
                    WHERE oi.order_id=%s AND j.status IN ('RUNNING','WAITING')''', (order_id,))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def recover_queued_orders():
    """Recover waiting jobs, without replaying running motors."""

    con = connect_db()
    recovered = []

    try:
        with con.cursor() as cur:
            cur.execute(
                '''
                SELECT DISTINCT o.order_id
                FROM orders o
                JOIN order_items oi
                    ON oi.order_id = o.order_id
                JOIN outbound_jobs j
                    ON j.item_id = oi.item_id
                WHERE o.status = 'PROCESSING'
                  AND j.status = 'RUNNING'
                '''
            )

            interrupted = [
                int(row[0]) for row in cur.fetchall()
            ]

            for order_id in interrupted:
                cur.execute(
                    """
                    UPDATE orders
                    SET status = 'ERROR'
                    WHERE order_id = %s
                      AND status = 'PROCESSING'
                    """,
                    (order_id,)
                )

                cur.execute(
                    '''
                    UPDATE outbound_jobs j
                    JOIN order_items oi
                        ON j.item_id = oi.item_id
                    SET j.status = 'RETRY_WAIT'
                    WHERE oi.order_id = %s
                      AND j.status IN ('RUNNING', 'WAITING')
                    ''',
                    (order_id,)
                )

                logging.warning(
                    'Interrupted order %s -> ERROR',
                    order_id
                )

            cur.execute(
                '''
                SELECT o.order_id
                FROM orders o
                JOIN order_items oi
                    ON oi.order_id = o.order_id
                JOIN outbound_jobs j
                    ON j.item_id = oi.item_id
                WHERE o.status = 'PROCESSING'
                  AND j.status = 'WAITING'
                GROUP BY o.order_id, o.approved_at
                ORDER BY o.approved_at ASC, o.order_id ASC
                '''
            )

            waiting = [
                int(row[0]) for row in cur.fetchall()
            ]

            for order_id in waiting:
                cur.execute('''SELECT oi.item_id,p.color,oi.quantity-oi.shipped_qty
                FROM order_items oi JOIN products p ON p.product_id=oi.product_id
                WHERE oi.order_id=%s ORDER BY oi.item_id''', (order_id,))
                rows = [(int(i),str(c),int(q)) for i,c,q in cur.fetchall() if int(q)>0]
                if rows and all(0 < q <= 1000 and c in FEED_DIGITS for _,c,q in rows):
                    recovered.append((order_id,rows))

        con.commit()

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()

    if len(recovered) > RUN_QUEUE.maxsize:
        raise RuntimeError(
            'RECOVERY_QUEUE_CAPACITY_EXCEEDED'
        )

    for item in recovered:
        RUN_QUEUE.put(item)
        ACTIVE.add(item[0])

    logging.info(
        'Recovered %s queued orders',
        len(recovered)
    )


def fail_order(order_id):
    con = connect_db()

    try:
        with con.cursor() as cur:
            cur.execute(
                """
                UPDATE orders
                SET status = 'ERROR'
                WHERE order_id = %s
                  AND status = 'PROCESSING'
                """,
                (order_id,)
            )

        con.commit()

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()


def restore_pending(order_id):
    con = connect_db()

    try:
        with con.cursor() as cur:
            cur.execute(
                '''
                DELETE j
                FROM outbound_jobs j
                JOIN order_items oi
                    ON j.item_id = oi.item_id
                WHERE oi.order_id = %s
                  AND j.status = 'WAITING'
                ''',
                (order_id,)
            )

            cur.execute(
                """
                UPDATE orders
                SET status = 'PENDING'
                WHERE order_id = %s
                  AND status = 'PROCESSING'
                """,
                (order_id,)
            )

        con.commit()

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()


def demo_complete_order(order_id):
    """
    Simulation-only completion.
    Never call for real hardware Stage 1.
    """

    con = connect_db()

    try:
        with con.cursor() as cur:
            cur.execute(
                'SELECT status FROM orders WHERE order_id=%s FOR UPDATE',
                (order_id,)
            )

            row = cur.fetchone()

            if row is None or row[0] != 'PROCESSING':
                raise ValueError(
                    'ORDER_NOT_PROCESSING_FOR_DEMO_COMPLETE'
                )

            cur.execute(
                '''
                SELECT
                    oi.item_id,
                    oi.product_id,
                    oi.quantity,
                    oi.shipped_qty,
                    p.color
                FROM order_items oi
                JOIN products p
                    ON p.product_id = oi.product_id
                WHERE oi.order_id = %s
                ORDER BY oi.item_id
                FOR UPDATE
                ''',
                (order_id,)
            )

            items = []
            demand = {}
            total = 0

            for item_id, product_id, qty, already, color in cur.fetchall():
                remaining = int(qty) - int(already)

                if remaining < 0 or remaining > 1000:
                    raise ValueError(
                        'INVALID_REMAINING_QUANTITY'
                    )

                if remaining == 0:
                    continue

                items.append(
                    (
                        int(item_id),
                        int(product_id),
                        color,
                        remaining
                    )
                )

                demand[color] = demand.get(color, 0) + remaining
                total += remaining

            if not items or total > 1000:
                raise ValueError(
                    'NO_REMAINING_ITEMS_OR_TOO_MANY_ITEMS'
                )

            cur.execute(
                '''
                SELECT product_id, color, stock
                FROM products
                ORDER BY product_id
                FOR UPDATE
                '''
            )

            inventories = {}

            for product_id, color, stock in cur.fetchall():
                inventories.setdefault(color, []).append(
                    (product_id, int(stock))
                )

            for color, needed in demand.items():
                group = inventories.get(color, [])

                if not group or len(
                    {stock for _, stock in group}
                ) != 1:
                    raise ValueError(
                        f'INCONSISTENT_SHARED_STOCK_{color}'
                    )

                if group[0][1] < needed:
                    raise ValueError(
                        f'INSUFFICIENT_SHARED_STOCK_{color}'
                    )

            for color, needed in sorted(demand.items()):
                cur.execute(
                    '''
                    UPDATE products
                    SET stock = stock - %s
                    WHERE color = %s
                      AND stock >= %s
                    ''',
                    (needed, color, needed)
                )

                if cur.rowcount != len(inventories[color]):
                    raise RuntimeError(
                        f'SHARED_STOCK_UPDATE_FAILED_{color}'
                    )

            for item_id, product_id, color, remaining in items:
                cur.execute(
                    '''
                    SELECT job_id
                    FROM outbound_jobs
                    WHERE item_id = %s
                      AND status = 'RUNNING'
                    ORDER BY job_id DESC
                    LIMIT 1
                    FOR UPDATE
                    ''',
                    (item_id,)
                )

                job = cur.fetchone()

                if not job:
                    raise RuntimeError('RUNNING_JOB_MISSING')

                job_id = int(job[0])

                for attempt in range(1, remaining + 1):
                    cur.execute(
                        '''
                        INSERT INTO outbound_logs
                        (
                            job_id,
                            attempt_no,
                            expected_product_id,
                            detected_product_id,
                            result,
                            destination,
                            created_at
                        )
                        VALUES
                        (%s, %s, %s, %s, 'SUCCESS', 'NORMAL', NOW())
                        ''',
                        (
                            job_id,
                            attempt,
                            product_id,
                            product_id
                        )
                    )

                    outbound_log_id = cur.lastrowid

                    cur.execute(
                        '''
                        INSERT INTO stock_logs
                        (
                            product_id,
                            change_qty,
                            reason,
                            outbound_log_id,
                            created_at
                        )
                        VALUES (%s, -1, 'NORMAL_OUT', %s, NOW())
                        ''',
                        (product_id, outbound_log_id)
                    )

                cur.execute(
                    '''
                    UPDATE order_items
                    SET shipped_qty = shipped_qty + %s
                    WHERE item_id = %s
                      AND shipped_qty + %s <= quantity
                    ''',
                    (remaining, item_id, remaining)
                )

                if cur.rowcount != 1:
                    raise RuntimeError(
                        'ORDER_ITEM_UPDATE_FAILED'
                    )

                cur.execute(
                    '''
                    UPDATE outbound_jobs
                    SET status = 'DONE',
                        completed_at = NOW()
                    WHERE job_id = %s
                      AND status = 'RUNNING'
                    ''',
                    (job_id,)
                )

                if cur.rowcount != 1:
                    raise RuntimeError(
                        'JOB_FINISH_UPDATE_FAILED'
                    )

            cur.execute(
                '''
                UPDATE orders
                SET status = 'COMPLETED',
                    completed_at = NOW()
                WHERE order_id = %s
                  AND status = 'PROCESSING'
                ''',
                (order_id,)
            )

            if cur.rowcount != 1:
                raise RuntimeError(
                    'ORDER_COMPLETE_UPDATE_FAILED'
                )

        con.commit()
        return total

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()


def send_arduino_digit(ser, digit, auto_return=False, timeout=5.0):
    """
    Arduino numeric commands 0~9.

    Servo 1/2:
        ACK,<digit>
        DONE,M1 or DONE,M2 after return

    Servo 3/4/5:
        ACK only
    """

    if digit not in '0123456789' or len(digit) != 1:
        raise ValueError('INVALID_MOTOR_DIGIT')

    ser.reset_input_buffer()
    ser.write(digit.encode('ascii'))
    ser.flush()

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        answer = ser.readline().decode(
            'ascii',
            errors='replace'
        ).strip()

        if answer == 'ACK,' + digit:
            break

        if answer.startswith('ERR,'):
            raise RuntimeError('ARDUINO_' + answer)

    else:
        raise TimeoutError(
            'ARDUINO_ACK_TIMEOUT_' + digit
        )

    if not auto_return:
        return

    motor = 'M1' if digit in '12' else 'M2'

    deadline = time.monotonic() + max(timeout, 4.0)

    while time.monotonic() < deadline:
        answer = ser.readline().decode(
            'ascii',
            errors='replace'
        ).strip()

        if answer == 'DONE,' + motor:
            return

        if answer.startswith('ERR,'):
            raise RuntimeError('ARDUINO_' + answer)

    raise TimeoutError(
        'ARDUINO_RETURN_TIMEOUT_' + digit
    )


def await_servo_return(ser, digit, timeout=5.0):
    motor = 'M1' if digit in '12' else 'M2'

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        answer = ser.readline().decode(
            'ascii',
            errors='replace'
        ).strip()

        if answer == 'DONE,' + motor:
            return

        if answer.startswith('ERR,'):
            raise RuntimeError('ARDUINO_' + answer)

    raise TimeoutError(
        'ARDUINO_RETURN_TIMEOUT_' + digit
    )


FEED_DIGITS = {
    'GREEN': '1',
    'YELLOW': '2',
    'BLUE': '3',
    'RED': '4'
}


def set_route(ser, region):
    """Set both routing servos for each order."""

    if region == 'SEOUL':
        send_arduino_digit(ser, '0')
        send_arduino_digit(ser, '7')

    elif region == 'CHUNGCHEONG':
        send_arduino_digit(ser, '8')
        send_arduino_digit(ser, '9')

    elif region == 'GYEONGGI':
        send_arduino_digit(ser, '8')
        send_arduino_digit(ser, '0')

    else:
        raise ValueError(
            'DELIVERY_REGION_NOT_SET'
        )


def get_order_detail(order_id):
    '''Return delivery region and unshipped boxes in original line-item order.'''
    con=connect_db()
    try:
        with con.cursor() as cur:
            cur.execute('SELECT delivery_region FROM orders WHERE order_id=%s',(order_id,))
            data=cur.fetchone()
            if not data or not data[0]:
                raise ValueError('DELIVERY_REGION_NOT_SET')
            region=str(data[0])
            if region not in ('SEOUL','GYEONGGI','CHUNGCHEONG'):
                raise ValueError('DELIVERY_REGION_NOT_SET')
            cur.execute('''SELECT oi.item_id,p.color,oi.quantity-oi.shipped_qty
                FROM order_items oi JOIN products p ON p.product_id=oi.product_id
                WHERE oi.order_id=%s ORDER BY oi.item_id''', (order_id,))
            items=[(int(i),str(c),int(q)) for i,c,q in cur.fetchall() if int(q)>0]
            if not items:
                raise ValueError('NO_PENDING_ITEMS')
            return region,items
    finally:
        con.close()

def record_camera_box(order_id, item_id, expected_color, detected_color, is_match):
    # Stage 1 physical ultrasonic arrival confirmation; one issued box.

    # One outbound log and one stock log per event, with atomic shared-color stock.
    # Cross-color detection cannot identify the SKU. Use a representative SKU
    # of that detected color for the existing product-ID-only schema.
    con = connect_db()
    try:
        with con.cursor() as cur:
            cur.execute('SELECT status FROM orders WHERE order_id=%s FOR UPDATE', (order_id,))
            state = cur.fetchone()
            if not state or state[0] != 'PROCESSING':
                raise ValueError('ORDER_NOT_PROCESSING')
            cur.execute('''
                SELECT oi.item_id, oi.product_id, oi.quantity, oi.shipped_qty
                FROM order_items oi JOIN products p ON p.product_id=oi.product_id
                WHERE oi.order_id=%s AND oi.item_id=%s AND p.color=%s
                FOR UPDATE
            ''', (order_id, item_id, expected_color))
            pending = [(int(a),int(b)) for a,b,q,sh in cur.fetchall() if int(q)>int(sh)]
            if not pending:
                raise ValueError('NO_PENDING_COLOR_ITEM')
            item_id, expected_id = pending[0]
            cur.execute('''
                SELECT job_id, retry_count FROM outbound_jobs
                WHERE item_id=%s AND status='RUNNING'
                ORDER BY job_id DESC LIMIT 1 FOR UPDATE
            ''', (item_id,))
            job = cur.fetchone()
            if not job:
                raise ValueError('RUNNING_JOB_NOT_FOUND')
            job_id = int(job[0])
            cur.execute('SELECT COALESCE(MAX(attempt_no),0) FROM outbound_logs WHERE job_id=%s', (job_id,))
            attempt = int(cur.fetchone()[0])+1
            stock_color = expected_color if is_match else detected_color
            cur.execute('SELECT product_id, stock FROM products WHERE color=%s ORDER BY product_id FOR UPDATE', (stock_color,))
            group = [(int(pid),int(qty)) for pid,qty in cur.fetchall()]
            if not group or len({x[1] for x in group})!=1 or group[0][1]<1:
                raise ValueError('SHARED_STOCK_INVALID_OR_EMPTY_'+stock_color)
            actual_id = expected_id if is_match else group[0][0]
            cur.execute('''
                INSERT INTO outbound_logs
                (job_id,attempt_no,expected_product_id,detected_product_id,result,destination,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,NOW())
            ''', (job_id,attempt,expected_id,actual_id,
                  'SUCCESS' if is_match else 'ERROR',
                  'NORMAL' if is_match else 'ERROR_BIN'))
            log_id=int(cur.lastrowid)
            cur.execute('UPDATE products SET stock=stock-1 WHERE color=%s AND stock>=1', (stock_color,))
            if cur.rowcount!=len(group):
                raise RuntimeError('STOCK_DECREMENT_FAILED')
            cur.execute('''
                INSERT INTO stock_logs(product_id,change_qty,reason,outbound_log_id,created_at)
                VALUES (%s,-1,%s,%s,NOW())
            ''', (actual_id, 'NORMAL_OUT' if is_match else 'ERROR_OUT',log_id))
            if is_match:
                cur.execute('''
                    UPDATE order_items SET shipped_qty=shipped_qty+1
                    WHERE item_id=%s AND shipped_qty<quantity
                ''', (item_id,))
                if cur.rowcount!=1:
                    raise RuntimeError('SHIPPED_QTY_NOT_UPDATED')
                cur.execute('''
                    SELECT COUNT(*) FROM order_items
                    WHERE order_id=%s AND shipped_qty < quantity
                ''', (order_id,))
                all_done = (int(cur.fetchone()[0])==0)
                cur.execute('''SELECT quantity,shipped_qty FROM order_items
                    WHERE item_id=%s FOR UPDATE''', (item_id,))
                item_qty,item_shipped = cur.fetchone()
                if int(item_shipped)==int(item_qty):
                    cur.execute('''UPDATE outbound_jobs SET status='DONE', completed_at=NOW()
                        WHERE job_id=%s AND status='RUNNING' ''', (job_id,))
                if all_done:
                    cur.execute('''
                        UPDATE orders SET status='COMPLETED', completed_at=NOW()
                        WHERE order_id=%s AND status='PROCESSING'
                    ''', (order_id,))
                    if cur.rowcount!=1:
                        raise RuntimeError('ORDER_COMPLETION_FAILED')
                    cur.execute('''
                        UPDATE outbound_jobs j JOIN order_items oi ON oi.item_id=j.item_id
                        SET j.status='DONE', j.completed_at=NOW()
                        WHERE oi.order_id=%s AND j.status='RUNNING'
                    ''', (order_id,))
            else:
                cur.execute('''
                    INSERT INTO error_bin(bin_id,item_count,warning_threshold)
                    VALUES(1,1,5) ON DUPLICATE KEY UPDATE item_count=item_count+1
                ''')
                cur.execute('''
                    UPDATE orders SET status='ERROR' WHERE order_id=%s AND status='PROCESSING'
                ''', (order_id,))
                cur.execute('''
                    UPDATE outbound_jobs j JOIN order_items oi ON oi.item_id=j.item_id
                    SET j.status='RETRY_WAIT' WHERE oi.order_id=%s
                      AND j.status IN ('RUNNING','WAITING')
                ''', (order_id,))
        con.commit()
        logging.info('BIN CONFIRMED recorded order=%s %s -> %s match=%s',
                        order_id,expected_color,detected_color,is_match)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def wait_for_bin_arrival(session, expected_bin, started_at, timeout_seconds):
    """Require a post-feeder arrival from the selected physical bin.

    Arduino sends BIN,<destination>,<sequence> immediately upon detecting an object.
    The persistent serial reader forwards it via bin_lines without touching
    the servo ACK queue. Ignore any event predating this feeder operation.
    """
    deadline = time.monotonic() + timeout_seconds
    events = get_conveyor().bin_lines
    while time.monotonic() < deadline:
        session.check()  # Emergency stop aborts confirmation immediately.
        try:
            event_time, destination, sequence = events.get(timeout=min(
                0.10, max(0.001, deadline - time.monotonic())))
        except queue.Empty:
            continue
        if event_time < started_at:
            continue
        logging.info('Bin sensor event: %s seq=%s expecting=%s',
                     destination, sequence, expected_bin)
        if destination != expected_bin:
            raise RuntimeError('WRONG_ARRIVAL_BIN_' + destination
                               + '_EXPECTED_' + expected_bin)
        session.check()
        return
    raise TimeoutError('ARRIVAL_SENSOR_TIMEOUT_' + expected_bin)


def process_job(order_id, rows):
    """
    One physical box at a time; each confirmed arrival commits its item.

    Camera + physical destination ultrasonic confirmation.
    The target destination bin must emit a completed arrival event.
    """

    if CONFIG['dry_run']:
        logging.info(
            'DRY RUN %s: %s. No motor/camera activation.',
            order_id,
            rows
        )
        return

    region, items = get_order_detail(order_id)

    camera_settings = CONFIG.get('inspection', {})

    timeout_clear = float(
        camera_settings.get('clear_timeout_seconds', 5)
    )

    timeout_color = float(
        camera_settings.get('color_timeout_seconds', 12)
    )

    settle = float(camera_settings.get('between_boxes_seconds', 2))
    arrival_timeout = float(camera_settings.get('arrival_timeout_seconds', 45))
    if not 5 <= arrival_timeout <= 300:
        raise ValueError('INVALID_ARRIVAL_TIMEOUT_SECONDS')

    planned = sum(qty for _, _, qty in items)

    logging.warning(
        'STAGE 1: order=%s region=%s items=%s. '
        'Camera + destination ultrasonic confirmation enabled.',
        order_id,
        region,
        items
    )

    # [ESTOP] 기존 숫자 명령/ACK/DONE은 유지하며 USB 재연결만 제거.
    with get_conveyor().job_session() as ser:

        # v21.1 CAMERA FIX
        if CAMERA is None:
            raise RuntimeError(
                'CAMERA_NOT_STARTED: video.enabled must be true'
            )

        # Reuse the persistent camera instead of opening another
        with nullcontext(CAMERA) as camera:

            for item_id, color, quantity in items:

                if color not in FEED_DIGITS:
                    raise ValueError(
                        'UNKNOWN_COLOR_' + color
                    )

                for _ in range(quantity):

                    # Wait for previous object to leave ROI
                    camera.begin(color)
                    camera.wait_empty(timeout_clear)

                    # Reset error gate
                    send_arduino_digit(ser, '6')

                    # Configure regional routing
                    set_route(ser, region)

                    logging.info(
                        'Feeding expected=%s via Arduino command=%s',
                        color,
                        FEED_DIGITS[color]
                    )

                    # Capture feeder start BEFORE the command; reject older bin events.
                    arrival_started = time.monotonic()

                    # Send physical feeder command
                    send_arduino_digit(
                        ser,
                        FEED_DIGITS[color],
                        auto_return=False,
                        timeout=5
                    )

                    # Camera recognition
                    detected = camera.wait_color(
                        timeout_color
                    )

                    # Wait for feeder auto-return
                    await_servo_return(
                        ser,
                        FEED_DIGITS[color],
                        timeout=5
                    )

                    logging.info(
                        'Camera: order=%s expected=%s detected=%s',
                        order_id,
                        color,
                        detected
                    )

                    if detected == color:
                        camera.report(
                            'NORMAL MATCH ' + color
                        )
                    else:
                        camera.report(
                            'ERROR MISMATCH ' + detected
                        )

                    if detected not in FEED_DIGITS:
                        raise RuntimeError('CAMERA_UNCERTAIN_' + str(detected))

                    matched = detected == color
                    if not matched:
                        send_arduino_digit(ser, '8')
                        send_arduino_digit(ser, '0')
                        send_arduino_digit(ser, '5')

                    # Route must match: ERROR on mismatch, otherwise order region.
                    # Commit stock/order only after the actual bin arrival event.
                    expected_bin = region if matched else 'ERROR'
                    logging.info('Waiting for arrival: order=%s destination=%s timeout=%.1fs',
                                 order_id, expected_bin, arrival_timeout)
                    wait_for_bin_arrival(ser, expected_bin, arrival_started,
                                         arrival_timeout)
                    record_camera_box(order_id, item_id, color, detected, matched)
                    if not matched:
                        raise RuntimeError('RECORDED_COLOR_MISMATCH expected='
                                           + color + ' detected=' + detected)
                    # Keep stop responsiveness during inter-box delay.
                    delay_end=time.monotonic()+settle
                    while time.monotonic()<delay_end:
                        ser.check()
                        time.sleep(min(0.10,max(0,delay_end-time.monotonic())))

    logging.info('Ultrasonic-confirmed processing done order=%s', order_id)


def worker():
    while True:
        order_id, rows = RUN_QUEUE.get()

        with STATE_LOCK:
            STATE['busy'] = True
            STATE['message'] = f'RUNNING order={order_id}'

        try:
            if not CONFIG['dry_run']:
                # [ESTOP] 대기 주문은 명시적인 컨베이어 실행 뒤에 진행.
                get_conveyor().wait_until_running()
                set_job_status(order_id, 'RUNNING')

            process_job(order_id, rows)

            logging.info(
                'ULTRASONIC CONFIRMED: inspection worker done order=%s',
                order_id
            )

        except Exception as exc:

            if CAMERA is not None:
                CAMERA.report(
                    'ERROR ' + str(exc)[:45]
                )

            logging.exception(
                'Job failed for order %s',
                order_id
            )

            if not CONFIG['dry_run']:
                try:
                    fail_order(order_id)

                    set_job_status(
                        order_id,
                        'RETRY_WAIT'
                    )

                    logging.warning(
                        'Order %s -> ERROR',
                        order_id
                    )

                except Exception:
                    logging.exception(
                        'Could not mark order %s as ERROR',
                        order_id
                    )

        finally:
            with STATE_LOCK:
                ACTIVE.discard(order_id)
                STATE['busy'] = False
                STATE['message'] = 'IDLE'

            RUN_QUEUE.task_done()


class Handler(socketserver.StreamRequestHandler):

    def handle(self):
        if (
            self.client_address[0]
            not in ('127.0.0.1', '::1')
            and CONFIG['host'] == '127.0.0.1'
        ):
            return

        raw = self.rfile.readline(513)

        if (
            not raw
            or len(raw) > 512
            or not raw.endswith(b'\n')
        ):
            return

        try:
            fields = raw.decode('utf-8').strip().split('|')

        except UnicodeDecodeError:
            return

        if len(fields) != 3:
            return

        command, order, request_id = fields

        if (
            not request_id
            or len(request_id) > 40
            or not request_id.replace('-', '').isalnum()
        ):
            return

        reply = f'ERR|{request_id}|BAD_COMMAND'

        if command == 'PING' and order == '-':
            reply = f'PONG|{request_id}'

        # [ESTOP] DB용 STATE_LOCK을 잡지 않으므로 출고/조회 중에도 제어.
        elif command in ('EMERGENCY_STOP', 'START_CONVEYOR', 'CONVEYOR_STATUS'):
            reply = conveyor_reply(command, order, request_id)

        elif command == 'STATUS' and order == '-':
            with STATE_LOCK:
                message = STATE['message']

            reply = f'ACK|{request_id}|{message}'

        elif (
            command == 'DISPATCH_ORDER'
            and order.isdecimal()
            and 0 < len(order) <= 16
            and int(order) > 0
        ):
            try:
                order_id = int(order)

                with STATE_LOCK:

                    if order_id in ACTIVE or RUN_QUEUE.full():
                        reply = f'ERR|{request_id}|BUSY'

                    else:
                        rows = order_lines(order_id)

                        if (
                            not CONFIG['dry_run']
                            and any(
                                color not in FEED_DIGITS
                                for _, color, _ in rows
                            )
                        ):
                            reply = (
                                f'ERR|{request_id}|UNSUPPORTED_COLOR'
                            )

                        elif (
                            not CONFIG['dry_run']
                            and not begin_order(order_id)
                        ):
                            reply = (
                                f'ERR|{request_id}|ORDER_ALREADY_CLAIMED'
                            )

                        else:
                            try:
                                ACTIVE.add(order_id)

                                RUN_QUEUE.put_nowait(
                                    (order_id, rows)
                                )

                            except Exception:
                                ACTIVE.discard(order_id)

                                if not CONFIG['dry_run']:
                                    restore_pending(order_id)

                                raise

                            state = (
                                'QUEUED_DRY_RUN'
                                if CONFIG['dry_run']
                                else 'QUEUED'
                            )

                            reply = (
                                f'ACK|{request_id}|{state}'
                            )

            except (
                ValueError,
                pymysql.MySQLError,
                OSError
            ) as exc:

                logging.warning(
                    'Order rejected: %s',
                    exc
                )

                reply = (
                    f'ERR|{request_id}|ORDER_LOOKUP_FAILED'
                )

        elif (command == 'RETRY_ORDER' and order.isdecimal()
              and 0 < len(order) <= 16 and int(order) > 0):
            order_id = int(order)
            if CONFIG['dry_run']:
                reply = f'ERR|{request_id}|RETRY_REQUIRES_HARDWARE_MODE'
            else:
                with STATE_LOCK:
                    if order_id in ACTIVE or RUN_QUEUE.full():
                        reply = f'ERR|{request_id}|BUSY'
                    else:
                        try:
                            # Operator must verify no unaccounted box remains.
                            rows, job_ids = claim_retry_order(order_id)
                            try:
                                ACTIVE.add(order_id)
                                RUN_QUEUE.put_nowait((order_id, rows))
                            except Exception:
                                ACTIVE.discard(order_id)
                                undo_retry_queue_claim(order_id, job_ids)
                                raise
                            reply = f'ACK|{request_id}|QUEUED'
                        except (ValueError, pymysql.MySQLError, OSError) as exc:
                            logging.warning('Retry rejected order %s: %s', order_id, exc)
                            reason = str(exc) if isinstance(exc, ValueError) else 'RETRY_DB_ERROR'
                            reply = f'ERR|{request_id}|{reason}'

        self.wfile.write(
            (reply + '\n').encode('utf-8')
        )

        logging.info(
            '%s from %s -> %s',
            command,
            self.client_address[0],
            reply
        )


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s'
    )

    from inspection_runtime import CameraInspector

    # Start video services inside try/finally so failed camera initialization
    # cannot leave the child CCTV process running on port 8081.
    cctv_process = None
    try:
        cctv_cfg = CONFIG.get('cctv', {})
        cctv_script = pathlib.Path(__file__).with_name('cctv_server.py')
        if cctv_cfg.get('enabled', True):
            if cctv_script.is_file():
                cmd = [sys.executable, str(cctv_script),
                       '--host', str(cctv_cfg.get('host', '0.0.0.0')),
                       '--port', str(cctv_cfg.get('port', 8081))]
                if cctv_cfg.get('camera') is not None:
                    cmd += ['--camera', str(cctv_cfg['camera'])]
                try:
                    cctv_process = subprocess.Popen(cmd, cwd=str(cctv_script.parent))
                    logging.info('CCTV process launched (pid=%s, port=%s)',
                                 cctv_process.pid, cctv_cfg.get('port', 8081))
                except OSError as exc:
                    logging.error('CCTV could not start: %s', exc)
            else:
                logging.warning('cctv_server.py not found, CCTV skipped: %s', cctv_script)

        video = CONFIG.get('video', {})
        if video.get('enabled', True):
            settings = CONFIG.get('inspection', {})
            camera_index = settings.get('camera_index', 0)
            CAMERA = CameraInspector(
                index=camera_index,
                full_frame=settings.get('full_frame', False),
                video_host=video.get('host', '0.0.0.0'),
                video_port=video.get('port', 8080)
            )
            try:
                CAMERA.start()
            except Exception:
                logging.exception('Inspection camera failed (camera_index=%s). '
                                  'Check /dev/video* and pi_config.json.', camera_index)
                raise
            logging.info('MJPEG available at http://<PI_IP>:%s/video_feed',
                         video.get('port', 8080))

        if not CONFIG['dry_run']:
            try:
                get_conveyor().status()
            except RuntimeError as exc:
                logging.warning('Arduino control unavailable: %s', exc)
            recover_queued_orders()

            threading.Thread(target=sensor_db_worker, daemon=True,
                             name='sensor-db-worker').start()
            threading.Thread(target=fan_db_worker, daemon=True,
                             name='fan-db-worker').start()

        threading.Thread(target=worker, daemon=True,
                         name='order-worker').start()

        with Server((CONFIG['host'], int(CONFIG['port'])), Handler) as srv:
            logging.info('MobleKurly Pi server %s:%s dry_run=%s',
                         CONFIG['host'], CONFIG['port'], CONFIG['dry_run'])
            srv.serve_forever()

    finally:
        if cctv_process is not None and cctv_process.poll() is None:
            logging.info('Stopping CCTV process pid=%s', cctv_process.pid)
            cctv_process.terminate()
            try:
                cctv_process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                cctv_process.kill()
                cctv_process.wait(timeout=2)
        if CONVEYOR is not None:
            CONVEYOR.close()
        if CAMERA is not None:
            CAMERA.stop()
