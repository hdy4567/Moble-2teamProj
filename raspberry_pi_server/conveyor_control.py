"""[ESTOP] Persistent Arduino connection, independent of DB/camera/order work.

USB protocol: ! stop, ? status, R,<stop revision>\n start.
Only STATE replies from the Arduino confirm conveyor state.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import queue
import math
import threading
import time


@dataclass(frozen=True)
class ConveyorState:
    running: bool
    pressed: bool
    revision: int

    def payload(self):
        return 'CONVEYOR,{},{},{}'.format(
            'RUNNING' if self.running else 'STOPPED',
            'PRESSED' if self.pressed else 'RELEASED', self.revision)


class ConveyorController:
    def __init__(self, port, baud, *, serial_factory=None, reset_wait=2.0,
                 timeout=0.8):
        self.port, self.baud = port, baud
        self._factory = serial_factory
        self._reset_wait, self._timeout = reset_wait, timeout
        self._cv = threading.Condition()
        self._open_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._control_lock = threading.Lock()
        self._job_lock = threading.Lock()
        self._serial = None
        self._reader_thread = None
        self._closed = False
        self._failure = None
        self._state = None
        self._sequence = 0
        self._epoch = 0
        self._job_lines = queue.Queue()
        # Sensor messages use their own queue to avoid stealing ACK/DONE/STATE.
        self.sensor_lines = queue.Queue(maxsize=20)
        # Arrival events are independent of servo ACKs and DHT measurements.
        self.bin_lines = queue.Queue(maxsize=30)
        # Latest reported Arduino fan output, never inferred from temperature.
        self._fan_lock = threading.Condition()
        self._fan_state = None  # (received_monotonic, speed_pct, state, diff, base)
        self.fan_lines = queue.Queue(maxsize=30)

    def _ensure_open(self):
        with self._open_lock:
            if self._closed:
                raise RuntimeError('ARDUINO_CLOSED')
            if self._serial is not None:
                if self._failure:
                    raise RuntimeError('ARDUINO_UNAVAILABLE')
                return
            factory = self._factory
            if factory is None:
                import serial
                factory = serial.Serial
            try:
                ser = factory(self.port, int(self.baud), timeout=0.1,
                              write_timeout=0.3)
                time.sleep(self._reset_wait)  # USB reset only once, not per order
                self._serial = ser
                self._reader_thread = threading.Thread(
                    target=self._read_loop, args=(ser,), daemon=True,
                    name='arduino-reader')
                self._reader_thread.start()
            except Exception as exc:
                raise RuntimeError('ARDUINO_UNAVAILABLE') from exc

    def _read_loop(self, ser):
        partial = b''
        try:
            while not self._closed:
                data = ser.readline()
                if not data:
                    continue
                partial += data
                if len(partial) > 1024:
                    raise RuntimeError('ARDUINO_BAD_FRAME')
                while b'\n' in partial:
                    raw, partial = partial.split(b'\n', 1)
                    line = raw.decode('ascii', errors='replace').strip()
                    if line.startswith('READY'):
                        with self._cv:
                            self._epoch += 1
                            self._state = None
                            self._cv.notify_all()
                    elif line.startswith('STATE,'):
                        fields = line.split(',')
                        if (len(fields) != 4 or fields[1] not in ('0', '1')
                                or fields[2] not in ('0', '1')
                                or not fields[3].isascii()
                                or not fields[3].isdecimal()
                                or not 0 <= int(fields[3]) <= 0xFFFFFFFF
                                or fields[1:3] == ['1', '1']):
                            raise RuntimeError('ARDUINO_BAD_STATE')
                        state = ConveyorState(fields[1] == '1', fields[2] == '1',
                                              int(fields[3]))
                        with self._cv:
                            self._state = state
                            self._sequence += 1
                            self._cv.notify_all()
                    elif line.startswith('SENSOR,'):
                        parts = line.split(',')
                        if len(parts) == 3:
                            try:
                                temp, humidity = float(parts[1]), float(parts[2])
                                if (-40 <= temp <= 80 and 0 <= humidity <= 100):
                                    try:
                                        self.sensor_lines.put_nowait((temp, humidity))
                                    except queue.Full:
                                        # Preserve newest measurements if DB writer is slow.
                                        try: self.sensor_lines.get_nowait()
                                        except queue.Empty: pass
                                        try: self.sensor_lines.put_nowait((temp, humidity))
                                        except queue.Full: pass
                            except ValueError:
                                pass
                    elif line.startswith('FAN,'):
                        # FAN,<speed>,<status>,<diff>,<base>;
                        # Arduino also reports FAN,100,SENSOR_ERROR on DHT failure.
                        fields = line.split(',')
                        if len(fields) in (3, 5):
                            try:
                                speed = int(fields[1])
                                label = fields[2]
                                valid_labels = ('NORMAL', 'WARNING', 'EMERGENCY',
                                                'SENSOR_ERROR')
                                if not (0 <= speed <= 100 and label in valid_labels):
                                    continue
                                if len(fields) == 5:
                                    diff = float(fields[3]); base = float(fields[4])
                                    if not (math.isfinite(diff) and math.isfinite(base)
                                            and -40 <= base <= 80):
                                        continue
                                elif label == 'SENSOR_ERROR':
                                    diff = base = None
                                else:
                                    continue
                                state = (time.monotonic(), speed, label, diff, base)
                                with self._fan_lock:
                                    self._fan_state = state
                                    self._fan_lock.notify_all()
                                try:
                                    self.fan_lines.put_nowait(state)
                                except queue.Full:
                                    try: self.fan_lines.get_nowait()
                                    except queue.Empty: pass
                                    try: self.fan_lines.put_nowait(state)
                                    except queue.Full: pass
                            except ValueError:
                                pass
                    elif line.startswith('BIN,'):
                        fields = line.split(',')
                        if (len(fields) == 3
                                and fields[1] in ('ERROR', 'SEOUL', 'GYEONGGI', 'CHUNGCHEONG')
                                and fields[2].isascii() and fields[2].isdecimal()):
                            entry = (time.monotonic(), fields[1], int(fields[2]))
                            try:
                                self.bin_lines.put_nowait(entry)
                            except queue.Full:
                                # Never mistake an old arrival for a new one.
                                try: self.bin_lines.get_nowait()
                                except queue.Empty: pass
                                try: self.bin_lines.put_nowait(entry)
                                except queue.Full: pass
                    elif (line.startswith('ACK,') or line.startswith('DONE,')
                          or line == 'ERR,BUSY'):
                        self._job_lines.put((line + '\n').encode('ascii'))
                    # Control rejections also emit STATE; never consume a servo ACK.
        except Exception as exc:
            with self._cv:
                self._failure = exc
                self._state = None
                self._cv.notify_all()

    def latest_fan_state(self, after=None, wait_seconds=0.0):
        """Return latest (received_time, speed, status, diff, base).

        When SENSOR is sent just before FAN, wait briefly for matching new fan
        telemetry rather than incorrectly logging the previous fan setting.
        """
        deadline = time.monotonic() + wait_seconds
        with self._fan_lock:
            while (after is not None and
                   (self._fan_state is None or self._fan_state[0] < after)):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._fan_lock.wait(remaining)
            return self._fan_state

    def _write(self, data):
        with self._write_lock:
            try:
                if self._failure or self._closed:
                    raise RuntimeError('ARDUINO_UNAVAILABLE')
                self._serial.write(data)
                self._serial.flush()
            except Exception as exc:
                with self._cv:
                    self._failure = exc
                    self._state = None
                    self._cv.notify_all()
                raise RuntimeError('ARDUINO_UNAVAILABLE') from exc

    def _exchange(self, data, accept=lambda state: True):
        self._ensure_open()
        with self._cv:
            sequence = self._sequence
        self._write(data)
        deadline = time.monotonic() + self._timeout
        with self._cv:
            while True:
                if self._failure or self._closed:
                    raise RuntimeError('ARDUINO_UNAVAILABLE')
                if (self._sequence > sequence and self._state is not None
                        and accept(self._state)):
                    return self._state
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._state = None
                    self._epoch += 1
                    self._cv.notify_all()
                    raise RuntimeError('ARDUINO_TIMEOUT')
                self._cv.wait(remaining)

    def status(self):
        with self._control_lock:
            return self._exchange(b'?')

    def stop(self):
        # Bypass _control_lock: STOP must not wait for a start/status timeout.
        self._ensure_open()
        with self._cv:
            revision = self._state.revision if self._state else None
            self._epoch += 1  # Cancel active feeding as soon as STOP is requested.
            self._cv.notify_all()
        return self._exchange(b'!', lambda s: not s.running
                              and (revision is None or s.revision != revision))

    def start(self, revision):
        if not isinstance(revision, int) or not 0 <= revision <= 0xFFFFFFFF:
            raise RuntimeError('BAD_START')
        with self._control_lock:
            before = self._exchange(b'?')
            if before.pressed:
                raise RuntimeError('BUTTON_PRESSED')
            if before.revision != revision:
                raise RuntimeError('STALE_START')
            # An older status reply may arrive before the RUN is processed.
            state = self._exchange(f'R,{revision}\n'.encode('ascii'),
                                   lambda s: s.running or s.pressed
                                   or s.revision != revision)
            if state.pressed:
                raise RuntimeError('BUTTON_PRESSED')
            if state.revision != revision:
                raise RuntimeError('STALE_START')
            if not state.running:
                raise RuntimeError('START_REJECTED')
            return state

    def wait_until_running(self):
        while not self._closed:
            try:
                state = self.status()
                if state.running and not state.pressed:
                    return
            except RuntimeError:
                pass
            time.sleep(0.25)
        raise RuntimeError('ARDUINO_CLOSED')

    @contextmanager
    def job_session(self):
        with self._job_lock:
            state = self.status()
            if not state.running or state.pressed:
                raise RuntimeError('CONVEYOR_STOPPED')
            with self._cv:
                token = (self._epoch, state.revision)
            session = _JobSerial(self, token)
            yield session
            session.check()

    def close(self):
        self._closed = True
        with self._cv:
            self._cv.notify_all()
        if self._serial is not None:
            self._serial.close()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=0.5)


class _JobSerial:
    """Keep the existing numeric command helpers and their ACK/DONE contract."""
    def __init__(self, controller, token):
        self.controller, self.token = controller, token

    def check(self):
        c = self.controller
        with c._cv:
            state = c._state
            if c._failure or c._closed:
                raise RuntimeError('ARDUINO_UNAVAILABLE')
            if (state is None or not state.running or state.pressed
                    or (c._epoch, state.revision) != self.token):
                raise RuntimeError('CONVEYOR_INTERRUPTED')

    def reset_input_buffer(self):
        self.check()
        while True:
            try: self.controller._job_lines.get_nowait()
            except queue.Empty: break

    def write(self, data):
        self.check()
        return self.controller._write(data)

    def flush(self):
        self.check()

    def readline(self):
        self.check()
        try:
            line = self.controller._job_lines.get(timeout=0.1)
        except queue.Empty:
            line = b''
        self.check()
        return line
