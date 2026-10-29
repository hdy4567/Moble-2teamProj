"""Read-only inventory provenance tests; no live MySQL connection is used."""

import sqlite3
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from mysql.connector import Error

import app as application


class LogisticsTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY="test-logistics")
        self.client = application.app.test_client()
        self.now = datetime(2026, 10, 16, 12, 30)
        self.database = sqlite3.connect(":memory:")
        self.addCleanup(self.database.close)
        self.database.row_factory = lambda cursor, row: {
            column[0]: row[index] for index, column in enumerate(cursor.description)
        }
        current_time = lambda: self.now.isoformat(sep=" ")
        self.database.create_function("NOW", 0, current_time)
        self.database.create_function("CURRENT_TIMESTAMP", 0, current_time)
        self.database.executescript("""
            CREATE TABLE products (
                product_id INTEGER PRIMARY KEY, name TEXT, color TEXT,
                price NUMERIC, stock INTEGER, min_stock INTEGER
            );
            CREATE TABLE purchase_orders (
                po_id INTEGER PRIMARY KEY, product_id INTEGER, quantity INTEGER,
                status TEXT, created_at TEXT, received_at TEXT
            );
            CREATE TABLE stock_logs (
                stock_log_id INTEGER PRIMARY KEY, product_id INTEGER,
                change_qty INTEGER, reason TEXT, outbound_log_id INTEGER,
                po_id INTEGER, created_at TEXT
            );
        """)
        self.add_product(1, "첫 상품", 17)
        self.add_product(2, "품절 상품", 0)

    def add_product(self, product_id, name, stock):
        self.database.execute(
            "INSERT INTO products VALUES (?, ?, 'red', 1234.50, ?, 5)",
            (product_id, name, stock),
        )

    def add_purchase(self, po_id, product_id, quantity, status, received_at=None,
                     created_at="2026-10-13 08:00:00"):
        self.database.execute(
            "INSERT INTO purchase_orders VALUES (?, ?, ?, ?, ?, ?)",
            (po_id, product_id, quantity, status, created_at, received_at),
        )

    def add_stock_log(self, log_id, product_id, quantity, reason, created_at):
        self.database.execute(
            "INSERT INTO stock_logs VALUES (?, ?, ?, ?, NULL, NULL, ?)",
            (log_id, product_id, quantity, reason, created_at),
        )

    def execute_select(self, sql, params=()):
        self.assertTrue(" ".join(sql.split()).upper().startswith("SELECT "))
        rows = self.database.execute(sql.replace("%s", "?"), params).fetchall()
        # MySQL returns DATETIME values as datetime objects, including MAX aliases.
        for row in rows:
            for key, value in row.items():
                if key.endswith("_at") and isinstance(value, str):
                    try:
                        row[key] = datetime.fromisoformat(value)
                    except ValueError:
                        pass
        return rows

    def fetch(self):
        with patch.object(application, "query", side_effect=self.execute_select) as query:
            result = application.fetch_logistics()
        self.assertEqual(query.call_count, 1, "One SELECT must build one coherent snapshot.")
        return result

    @staticmethod
    def products_by_id(result):
        return {product["product_id"]: product for product in result["products"]}

    def test_database_name_and_current_stock_are_not_reconstructed_from_logs(self):
        self.add_purchase(1, 1, 500, "RECEIVED", "2026-10-14 09:30:00")
        self.add_stock_log(1, 1, 999, "RESTOCK", "2026-10-14 09:30:00")
        result = self.fetch()
        self.assertEqual(result["database"], "moblekurly")
        products = self.products_by_id(result)
        self.assertEqual(products[1]["name"], "첫 상품")
        self.assertEqual(products[1]["stock"], 17)
        self.assertEqual(products[2]["stock"], 0)

    def test_latest_real_receipt_can_come_from_positive_restock_log(self):
        self.add_purchase(1, 1, 10, "RECEIVED", "2026-10-13 12:30:00")
        self.add_stock_log(1, 1, 3, "RESTOCK", "2026-10-14 09:30:00")
        product = self.products_by_id(self.fetch())[1]
        self.assertEqual(product["last_received_at"], "2026-10-14T09:30:00")
        self.assertEqual(product["last_received_label"], "2026.10.14 09:30")
        self.assertEqual(product["elapsed_label"], "기록 후 2일 3시간")

    def test_latest_real_receipt_can_come_from_completed_purchase(self):
        self.add_stock_log(1, 1, 3, "RESTOCK", "2026-10-13 09:30:00")
        self.add_purchase(1, 1, 10, "RECEIVED", "2026-10-15 09:30:00")
        product = self.products_by_id(self.fetch())[1]
        self.assertEqual(product["last_received_at"], "2026-10-15T09:30:00")
        self.assertEqual(product["last_received_label"], "2026.10.15 09:30")

    def test_adjustments_outbound_and_nonpositive_restock_are_not_receipts(self):
        for log_id, quantity, reason in [
            (1, 5, "ADJUST"), (2, -1, "NORMAL_OUT"),
            (3, -1, "ERROR_OUT"), (4, 0, "RESTOCK"),
            (5, -3, "RESTOCK"),
        ]:
            self.add_stock_log(log_id, 1, quantity, reason, "2026-10-16 10:30:00")
        product = self.products_by_id(self.fetch())[1]
        self.assertIsNone(product["last_received_at"])
        self.assertEqual(product["last_received_label"], "입고 기록 없음")

    def test_ordered_purchase_and_created_at_never_masquerade_as_receipt(self):
        self.add_purchase(1, 1, 10, "ORDERED", "2026-10-16 10:30:00")
        self.add_purchase(2, 1, 20, "RECEIVED", None, "2026-10-16 11:30:00")
        product = self.products_by_id(self.fetch())[1]
        self.assertIsNone(product["last_received_at"])
        self.assertEqual(product["elapsed_label"], "경과시간 확인 불가")

    def test_pending_quantity_and_count_do_not_multiply_with_receipt_logs(self):
        self.add_purchase(1, 1, 6, "ORDERED")
        self.add_purchase(2, 1, 9, "ORDERED")
        self.add_purchase(3, 1, 100, "RECEIVED", "2026-10-13 09:30:00")
        self.add_purchase(4, 2, 4, "ORDERED")
        self.add_stock_log(1, 1, 10, "RESTOCK", "2026-10-13 09:30:00")
        self.add_stock_log(2, 1, 20, "RESTOCK", "2026-10-14 09:30:00")
        products = self.products_by_id(self.fetch())
        self.assertEqual(products[1]["pending_quantity"], 15)
        self.assertEqual(products[1]["pending_count"], 2)
        self.assertEqual(products[2]["pending_quantity"], 4)
        self.assertEqual(products[2]["pending_count"], 1)

    def test_missing_records_never_invent_delivery_date_or_stock_age(self):
        for product in self.fetch()["products"]:
            self.assertIsNone(product["last_received_at"])
            self.assertEqual(product["last_received_label"], "입고 기록 없음")
            self.assertEqual(product["elapsed_label"], "경과시간 확인 불가")
            self.assertEqual(product["pending_quantity"], 0)
            self.assertEqual(product["pending_count"], 0)
            self.assertIsNone(product["next_arrival_at"])
            self.assertEqual(product["next_arrival_label"], "일정 미등록")
            self.assertIs(product["stock_age_known"], False)

    def test_pending_purchase_is_not_a_promised_arrival_date(self):
        self.add_purchase(1, 1, 6, "ORDERED", None, "2026-10-17 08:00:00")
        product = self.products_by_id(self.fetch())[1]
        self.assertEqual(product["pending_quantity"], 6)
        self.assertIsNone(product["next_arrival_at"])
        self.assertEqual(product["next_arrival_label"], "일정 미등록")
        self.assertIs(product["stock_age_known"], False)

    def test_receipt_does_not_claim_age_of_entire_remaining_stock(self):
        self.add_purchase(1, 1, 6, "RECEIVED", "2026-10-14 09:30:00")
        product = self.products_by_id(self.fetch())[1]
        self.assertIs(product["stock_age_known"], False)

    def test_future_receipts_are_ignored_in_favor_of_real_past_receipts(self):
        self.add_purchase(1, 1, 6, "RECEIVED", "2026-10-14 09:30:00")
        self.add_purchase(2, 1, 6, "RECEIVED", "2026-10-17 09:30:00")
        self.add_stock_log(1, 1, 6, "RESTOCK", "2026-10-18 09:30:00")
        self.add_purchase(3, 2, 6, "RECEIVED", "2026-10-17 09:30:00")
        self.add_stock_log(2, 2, 6, "RESTOCK", "2026-10-18 09:30:00")
        products = self.products_by_id(self.fetch())
        self.assertEqual(products[1]["last_received_at"], "2026-10-14T09:30:00")
        self.assertIsNone(products[2]["last_received_at"])
        self.assertEqual(products[2]["elapsed_label"], "경과시간 확인 불가")

    def test_snapshot_checked_at_comes_from_database_clock(self):
        self.assertEqual(self.fetch()["checked_at"], "2026-10-16T12:30:00")

    def test_empty_catalog_is_empty_instead_of_demo_inventory(self):
        self.database.execute("DELETE FROM products")
        result = self.fetch()
        self.assertEqual(result["database"], "moblekurly")
        self.assertEqual(result["products"], [])

    def test_api_success_uses_same_public_snapshot_contract(self):
        snapshot = self.fetch()
        with patch.object(application, "fetch_logistics", return_value=snapshot) as fetch:
            response = self.client.get("/api/logistics")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), snapshot)
        fetch.assert_called_once_with()
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_api_reads_updated_database_stock_and_pending_rows_on_each_request(self):
        with patch.object(application, "query", side_effect=self.execute_select) as query:
            before = self.client.get("/api/logistics")
            self.database.execute("UPDATE products SET stock = 3 WHERE product_id = 1")
            self.add_purchase(1, 1, 8, "ORDERED")
            after = self.client.get("/api/logistics")
        self.assertEqual(before.status_code, 200)
        self.assertEqual(after.status_code, 200)
        self.assertEqual(self.products_by_id(before.get_json())[1]["stock"], 17)
        self.assertEqual(self.products_by_id(after.get_json())[1]["stock"], 3)
        self.assertEqual(self.products_by_id(after.get_json())[1]["pending_quantity"], 8)
        self.assertEqual(query.call_count, 2)
        self.assertIn("no-store", before.headers.get("Cache-Control", ""))
        self.assertIn("no-store", after.headers.get("Cache-Control", ""))

    def test_api_database_failure_is_explicit_and_never_returns_stale_products(self):
        with patch.object(application, "fetch_logistics", side_effect=Error("test failure")):
            with patch.object(application.app.logger, "exception"):
                response = self.client.get("/api/logistics")
        self.assertEqual(response.status_code, 503)
        body = response.get_json()
        self.assertTrue(body.get("error"))
        self.assertNotIn("products", body)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))


class LogisticsFormattingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, 12, 30)

    def payload(self, received_at=None, checked_at=None):
        from inventory import build_logistics_payload

        return build_logistics_payload([{
            "product_id": 1, "name": "DB 상품", "stock": 7,
            "last_received_at": received_at, "pending_quantity": 0,
            "pending_count": 0, "checked_at": checked_at,
        }])

    def test_elapsed_boundaries_are_labelled_without_claiming_stock_age(self):
        for seconds, expected in [
            (0, "기록 후 1분 미만"),
            (59, "기록 후 1분 미만"),
            (60, "기록 후 1분"),
            (3599, "기록 후 59분"),
            (3600, "기록 후 1시간"),
            (3660, "기록 후 1시간 1분"),
            (86399, "기록 후 23시간 59분"),
            (86400, "기록 후 1일"),
            (90000, "기록 후 1일 1시간"),
            (183600, "기록 후 2일 3시간"),
        ]:
            with self.subTest(seconds=seconds):
                received_at = self.now - timedelta(seconds=seconds)
                product = self.payload(received_at, self.now)["products"][0]
                self.assertEqual(product["elapsed_label"], expected)
                self.assertIs(product["stock_age_known"], False)

    def test_unknown_or_future_clock_does_not_produce_negative_or_invented_age(self):
        for received_at, checked_at in [
            (None, self.now),
            (self.now, None),
            (self.now + timedelta(seconds=1), self.now),
        ]:
            with self.subTest(received_at=received_at, checked_at=checked_at):
                product = self.payload(received_at, checked_at)["products"][0]
                self.assertEqual(product["elapsed_label"], "경과시간 확인 불가")
                self.assertIs(product["stock_age_known"], False)


if __name__ == "__main__":
    unittest.main()
