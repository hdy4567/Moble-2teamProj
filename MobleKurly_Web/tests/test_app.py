import sqlite3
import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import app as application
from order_support import post_order


PRODUCTS = [
    {"product_id": 1, "name": "레드 패키지", "color": "red", "price": Decimal("12000"), "stock": 20},
    {"product_id": 2, "name": "블루 패키지", "color": "blue", "price": Decimal("13000"), "stock": 15},
]


class FakeCursor:
    def __init__(self):
        self.results = []
        self.lastrowid = None
        self.queries = []
        self.closed = False

    def execute(self, query, params=None):
        compact = " ".join(query.split())
        self.queries.append((compact, params))
        if compact.startswith("SELECT product_id, name, color"):
            self.results = PRODUCTS
        elif "FROM products" in compact and "FOR UPDATE" in compact:
            ids = set(params)
            self.results = [product for product in PRODUCTS if product["product_id"] in ids]
        elif compact.startswith("INSERT INTO orders"):
            self.lastrowid = 7
        elif compact.startswith("INSERT INTO order_items"):
            self.lastrowid = 70 + len([q for q, _ in self.queries if q.startswith("INSERT INTO order_items")])

    def fetchall(self):
        return list(self.results)

    def fetchone(self):
        return self.results[0] if self.results else None

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, dictionary=False):
        return self.cursor_instance

    def start_transaction(self):
        pass

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def is_connected(self):
        return not self.closed

    def close(self):
        self.closed = True


class PurchasePageTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = application.app.test_client()

    def test_order_number_accepts_simple_formats(self):
        self.assertEqual(application.parse_order_number("MK-000123"), 123)
        self.assertEqual(application.parse_order_number("000123"), 123)
        self.assertEqual(application.parse_order_number("123"), 123)
        self.assertIsNone(application.parse_order_number("MK-ABC"))
        self.assertEqual(application.display_order_number(123), "MK-000123")

    def test_order_number_rejects_invalid_digits_and_out_of_range_values(self):
        invalid_numbers = {
            "superscript": "\u00b9",
            "full_width": "\uff11\uff12\uff13",
            "arabic_indic": "\u0661\u0662\u0663",
            "very_long": "1" * 5000,
            "above_int32": "2147483648",
            "ten_digit_overflow": "9999999999",
            "zero": "MK-000000",
            "missing": None,
        }
        for label, number in invalid_numbers.items():
            with self.subTest(case=label):
                self.assertIsNone(application.parse_order_number(number))
        self.assertEqual(application.parse_order_number("2147483647"), 2147483647)

    def test_lookup_invalid_numbers_render_inline_error_without_querying_database(self):
        invalid_numbers = ["\u00b9", "\uff11\uff12\uff13", "1" * 5000, "2147483648"]
        with patch.object(application, "fetch_order") as fetch_order:
            for method in ["get", "post"]:
                for index, number in enumerate(invalid_numbers):
                    with self.subTest(method=method, case=index):
                        arguments = {"query_string" if method == "get" else "data": {"order_number": number}}
                        response = getattr(self.client, method)("/lookup", **arguments)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.data.count(b'id="lookup-error"'), 1)
                        self.assertIn(b'aria-invalid="true"', response.data)
            fetch_order.assert_not_called()

    def test_lookup_get_order_number_fetches_and_renders_order(self):
        order = {
            "order_id": 123,
            "status": "PROCESSING",
            "ordered_at": datetime(2026, 10, 16, 12, 30),
            "items": [{"name": "레드 패키지", "color": "red", "quantity": 2,
                       "shipped_qty": 1, "unit_price": Decimal("12000"),
                       "line_total": Decimal("24000")}],
            "total": Decimal("24000"),
        }
        with patch.object(application, "fetch_order", return_value=order) as fetch_order:
            response = self.client.get("/lookup", query_string={"order_number": "MK-000123"})
        fetch_order.assert_called_once_with(123)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="MK-000123"', response.data)
        self.assertIn("레드 패키지".encode(), response.data)
        self.assertIn("24,000원".encode(), response.data)
        self.assertIn("출고 1 / 2개".encode(), response.data)
        self.assertNotIn(b'id="lookup-error"', response.data)

    def test_fetch_order_does_not_duplicate_items_when_item_has_multiple_jobs(self):
        # Execute the real SELECT against relational fixtures so restoring the old
        # jobs join would actually duplicate the first item and inflate the total.
        database = sqlite3.connect(":memory:")
        self.addCleanup(database.close)
        database.row_factory = lambda cursor, row: {
            column[0]: row[index] for index, column in enumerate(cursor.description)
        }
        database.executescript("""
            CREATE TABLE orders (order_id INTEGER, status TEXT, ordered_at TEXT,
                                 approved_at TEXT, completed_at TEXT);
            CREATE TABLE products (product_id INTEGER, name TEXT, color TEXT);
            CREATE TABLE order_items (item_id INTEGER, order_id INTEGER,
                                      product_id INTEGER, quantity INTEGER,
                                      shipped_qty INTEGER, unit_price NUMERIC);
            CREATE TABLE outbound_jobs (job_id INTEGER, item_id INTEGER, status TEXT);
            INSERT INTO orders VALUES (7, 'PROCESSING', '2026-10-16 12:30:00', NULL, NULL);
            ALTER TABLE orders ADD COLUMN delivery_region TEXT;
            ALTER TABLE orders ADD COLUMN points_used INTEGER DEFAULT 0;
            INSERT INTO products VALUES (1, 'Red package', 'red'), (2, 'Blue package', 'blue');
            INSERT INTO order_items VALUES (71, 7, 1, 2, 1, 12000), (72, 7, 2, 1, 0, 13000);
            INSERT INTO outbound_jobs VALUES (1, 71, 'DONE'), (2, 71, 'WAITING'), (3, 72, 'WAITING');
        """)
        sqlite_cursor = database.cursor()
        cursor = Mock()
        cursor.execute.side_effect = lambda query, params: sqlite_cursor.execute(query.replace("%s", "?"), params)
        cursor.fetchone.side_effect = sqlite_cursor.fetchone
        cursor.fetchall.side_effect = sqlite_cursor.fetchall
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch.object(application, "get_db", return_value=connection):
            order = application.fetch_order(7)
        self.assertEqual([item["name"] for item in order["items"]], ["Red package", "Blue package"])
        self.assertEqual(order["total"], Decimal("37000"))
        connection.close.assert_called_once()

    def test_product_page_renders_database_products(self):
        connection = FakeConnection()
        with patch.object(application, "get_db", return_value=connection):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("레드 패키지".encode(), response.data)
        self.assertIn("12,000원".encode(), response.data)

    def test_order_creates_items_and_outbound_jobs_atomically(self):
        connection = FakeConnection()
        with patch.object(application, "get_db", return_value=connection):
            response = post_order(
                self.client,
                data={"quantity_1": "2", "expected_price_1": "12000",
                      "quantity_2": "1", "expected_price_2": "13000"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/orders/complete/7"))
        self.assertTrue(connection.committed)
        queries = [query for query, _ in connection.cursor_instance.queries]
        self.assertEqual(sum(q.startswith("INSERT INTO order_items") for q in queries), 2)
        self.assertEqual(sum(q.startswith("INSERT INTO outbound_jobs") for q in queries), 2)
        self.assertFalse(any(q.startswith("UPDATE products") for q in queries))

    def test_empty_order_is_rejected(self):
        response = post_order(self.client, data={"quantity_1": "0"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/"))


if __name__ == "__main__":
    unittest.main()
