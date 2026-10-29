"""Explicit, one-time product change approved on 2026-10-19.

Run without --apply to preview. Never called by the web server or launchers.
Only names/prices of the four existing team products may be changed.
"""

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import DB_CONFIG, get_db  # noqa: E402


EXPECTED_SERVER_UUID = "19724468-8ed8-11f1-a916-08bfb83b1684"
PLAN = {
    1: {"color": "RED", "name": "딸기 500g", "price": Decimal("14900.00")},
    2: {"color": "BLUE", "name": "블루베리 125g", "price": Decimal("5900.00")},
    3: {"color": "YELLOW", "name": "노랑 파프리카 2입", "price": Decimal("3990.00")},
    4: {"color": "GREEN", "name": "브로콜리 1입", "price": Decimal("3490.00")},
}
SELECT_PRODUCTS = """
    SELECT product_id, name, color, price, stock, min_stock
    FROM products WHERE product_id IN (1, 2, 3, 4) ORDER BY product_id
"""


def validate_rows(rows):
    if {row["product_id"] for row in rows} != set(PLAN) or len(rows) != len(PLAN):
        raise RuntimeError("기존 상품 ID 1~4를 모두 확인하지 못했습니다. 변경하지 않습니다.")
    for row in rows:
        if row["color"] != PLAN[row["product_id"]]["color"]:
            raise RuntimeError("기존 상품 색상과 계획이 다릅니다. 변경하지 않습니다.")


def apply_catalog(apply=False, backup_directory=None):
    if (DB_CONFIG["host"], DB_CONFIG["port"], DB_CONFIG["database"]) != (
            "192.168.0.90", 3306, "moblekurly"):
        raise RuntimeError("승인된 팀 DB 접속 대상이 아닙니다. 변경하지 않습니다.")
    connection = get_db()
    cursor = None
    try:
        if apply:
            connection.start_transaction()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT DATABASE() AS db, @@server_uuid AS server_uuid")
        identity = cursor.fetchone()
        if identity != {"db": "moblekurly", "server_uuid": EXPECTED_SERVER_UUID}:
            raise RuntimeError("팀 DB 서버 식별 정보가 다릅니다. 변경하지 않습니다.")
        cursor.execute(SELECT_PRODUCTS + (" FOR UPDATE" if apply else ""))
        before = cursor.fetchall()
        validate_rows(before)
        if not apply:
            return {"applied": False, "before": before, "plan": PLAN}

        # A durable, exclusive local snapshot must exist before any UPDATE.
        directory = Path(backup_directory) if backup_directory else ROOT.parent / "DB" / "백업" / "상품데이터"
        directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone(timedelta(hours=9)))
        backup = directory / f"produce_before_{now:%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.json"
        with backup.open("x", encoding="utf-8") as stream:
            json.dump({"checked_at": now.isoformat(), "identity": identity,
                       "before": before, "plan": PLAN}, stream,
                      ensure_ascii=False, indent=2, default=str)

        changed = 0
        for row in before:
            product_id = row["product_id"]
            target = PLAN[product_id]
            if row["name"] == target["name"] and row["price"] == target["price"]:
                continue
            cursor.execute(
                "UPDATE products SET name = %s, price = %s "
                "WHERE product_id = %s AND color = %s AND name = %s AND price = %s",
                (target["name"], target["price"], product_id,
                 row["color"], row["name"], row["price"]),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("상품 변경 건수가 예상과 다릅니다. 전체 변경을 취소합니다.")
            changed += 1
        cursor.execute(SELECT_PRODUCTS)
        after = cursor.fetchall()
        expected = [dict(row, name=PLAN[row["product_id"]]["name"],
                         price=PLAN[row["product_id"]]["price"]) for row in before]
        if after != expected:
            raise RuntimeError("재고·ID·색상 보존 검증에 실패했습니다. 전체 변경을 취소합니다.")
        connection.commit()
        return {"applied": True, "changed": changed, "backup": str(backup), "after": after}
    except Exception:
        connection.rollback()
        raise
    finally:
        try:
            if cursor is not None:
                cursor.close()
        finally:
            connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply the approved four-product update")
    args = parser.parse_args()
    print(json.dumps(apply_catalog(args.apply), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
