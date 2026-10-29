"""Customer inventory facts derived only from the existing team SQL schema.

There is no lot allocation, expiry date or expected arrival column in that
schema. A recent receipt event must not be presented as the age of all stock.
"""

from datetime import datetime


LOGISTICS_SQL = """
    SELECT p.product_id, p.name, p.stock,
           receipts.last_received_at,
           COALESCE(pending.pending_quantity, 0) AS pending_quantity,
           COALESCE(pending.pending_count, 0) AS pending_count,
           CURRENT_TIMESTAMP AS checked_at
    FROM products p
    LEFT JOIN (
        SELECT events.product_id, MAX(events.received_at) AS last_received_at
        FROM (
            SELECT product_id, received_at
            FROM purchase_orders
            WHERE status = 'RECEIVED'
              AND received_at IS NOT NULL
              AND received_at <= CURRENT_TIMESTAMP
            UNION ALL
            SELECT product_id, created_at AS received_at
            FROM stock_logs
            WHERE reason = 'RESTOCK' AND change_qty > 0
              AND created_at <= CURRENT_TIMESTAMP
        ) events
        GROUP BY events.product_id
    ) receipts ON receipts.product_id = p.product_id
    LEFT JOIN (
        SELECT product_id, SUM(quantity) AS pending_quantity,
               COUNT(*) AS pending_count
        FROM purchase_orders
        WHERE status = 'ORDERED'
        GROUP BY product_id
    ) pending ON pending.product_id = p.product_id
    ORDER BY p.product_id
"""


def _datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return None


def _elapsed_label(received_at, checked_at):
    if received_at is None or checked_at is None:
        return "경과시간 확인 불가"
    try:
        seconds = int((checked_at - received_at).total_seconds())
    except TypeError:
        return "경과시간 확인 불가"
    if seconds < 0:
        return "경과시간 확인 불가"
    minutes = seconds // 60
    if minutes == 0:
        return "기록 후 1분 미만"
    if minutes < 60:
        return f"기록 후 {minutes}분"
    hours, remaining_minutes = divmod(minutes, 60)
    if hours < 24:
        suffix = f" {remaining_minutes}분" if remaining_minutes else ""
        return f"기록 후 {hours}시간{suffix}"
    days, remaining_hours = divmod(hours, 24)
    suffix = f" {remaining_hours}시간" if remaining_hours else ""
    return f"기록 후 {days}일{suffix}"


def build_logistics_payload(rows):
    products = []
    checked_at = _datetime(rows[0].get("checked_at")) if rows else None
    for row in rows:
        received_at = _datetime(row.get("last_received_at"))
        row_checked_at = _datetime(row.get("checked_at"))
        # Defense in depth: never call a future timestamp a fresh receipt.
        if received_at is not None and row_checked_at is not None:
            try:
                if received_at > row_checked_at:
                    received_at = None
            except TypeError:
                received_at = None
        products.append({
            "product_id": row["product_id"],
            "name": row["name"],
            "stock": row["stock"],
            "last_received_at": received_at.isoformat() if received_at else None,
            "last_received_label": received_at.strftime("%Y.%m.%d %H:%M") if received_at else "입고 기록 없음",
            "elapsed_label": _elapsed_label(received_at, row_checked_at),
            "pending_quantity": int(row.get("pending_quantity") or 0),
            "pending_count": int(row.get("pending_count") or 0),
            "next_arrival_at": None,
            "next_arrival_label": "일정 미등록",
            "stock_age_known": False,
        })
    return {"database": "moblekurly", "products": products,
            "checked_at": checked_at.isoformat() if checked_at else None}
