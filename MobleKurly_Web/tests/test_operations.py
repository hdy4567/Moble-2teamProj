import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch

from flask import template_rendered
from mysql.connector import Error

import app as application
from order_support import post_order


@contextmanager
def rendered_contexts():
    contexts = []

    def record(_sender, template, context, **_extra):
        contexts.append((template.name, context))

    template_rendered.connect(record, application.app)
    try:
        yield contexts
    finally:
        template_rendered.disconnect(record, application.app)


class OperationsPageTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = application.app.test_client()
        self.now = datetime(2026, 10, 16, 12, 30)
        self.order = {
            "order_id": 123,
            "status": "PROCESSING",
            "ordered_at": self.now,
            "approved_at": None,
            "completed_at": None,
            "items": [
                {
                    "item_id": 71, "product_id": 1, "name": "레드 패키지",
                    "color": "red", "quantity": 2, "shipped_qty": 1,
                    "unit_price": Decimal("12000"), "line_total": Decimal("24000"),
                }
            ],
            "total": Decimal("24000"),
        }

    def test_order_list_aggregates_items_without_multiplying_outbound_jobs(self):
        database = sqlite3.connect(":memory:")
        self.addCleanup(database.close)
        database.row_factory = lambda cursor, row: {
            column[0]: row[index] for index, column in enumerate(cursor.description)
        }
        database.executescript("""
            CREATE TABLE orders (order_id INTEGER, status TEXT, ordered_at TEXT,
                                 approved_at TEXT, completed_at TEXT);
            CREATE TABLE order_items (item_id INTEGER, order_id INTEGER,
                                      quantity INTEGER, shipped_qty INTEGER,
                                      unit_price NUMERIC);
            CREATE TABLE outbound_jobs (job_id INTEGER, item_id INTEGER, status TEXT);
            INSERT INTO orders VALUES (123, 'PROCESSING', '2026-10-16 12:30:00', NULL, NULL);
            INSERT INTO orders VALUES (124, 'PENDING', '2026-10-16 12:30:00', NULL, NULL);
            ALTER TABLE orders ADD COLUMN delivery_region TEXT;
            ALTER TABLE orders ADD COLUMN points_used INTEGER DEFAULT 0;
            INSERT INTO order_items VALUES (71, 123, 2, 1, 12000), (72, 123, 1, 0, 13000);
            INSERT INTO outbound_jobs VALUES (1, 71, 'DONE'), (2, 71, 'WAITING'), (3, 72, 'WAITING');
        """)

        def execute_select(sql, params=()):
            return database.execute(sql.replace("%s", "?"), params).fetchall()

        with patch.object(application, "query", side_effect=execute_select) as query:
            with rendered_contexts() as contexts:
                response = self.client.get("/orders")

        self.assertEqual(response.status_code, 200)
        rows = contexts[-1][1]["orders"]
        self.assertEqual([row["order_id"] for row in rows], [124, 123])
        self.assertEqual(rows[1]["item_types"], 2)
        self.assertEqual(rows[1]["total_qty"], 3)
        self.assertEqual(rows[1]["shipped_qty"], 1)
        self.assertEqual(rows[1]["total_amount"], 37000)
        self.assertEqual(rows[0]["total_amount"], 0)
        self.assertIn("MK-000123".encode(), response.data)
        self.assertIn("37,000원".encode(), response.data)
        self.assertIn("LIMIT 200", " ".join(query.call_args.args[0].split()).upper())

    def test_order_list_search_accepts_friendly_order_numbers(self):
        for value in ["123", "000123", "MK-000123"]:
            with self.subTest(order_number=value):
                with patch.object(application, "query", return_value=[]) as query:
                    response = self.client.get("/orders", query_string={"order_id": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(query.call_args.args[1], (123,))
                self.assertIn("o.order_id = %s", query.call_args.args[0])

    def test_order_list_invalid_search_does_not_query_database(self):
        for value in ["MK-ABC", "0", "2147483648", "１23", "1" * 5000]:
            with self.subTest(order_number=value):
                with patch.object(application, "query") as query:
                    with rendered_contexts() as contexts:
                        response = self.client.get("/orders", query_string={"order_id": value})
                self.assertEqual(response.status_code, 200)
                query.assert_not_called()
                self.assertEqual(contexts[-1][1]["orders"], [])
                self.assertTrue(contexts[-1][1]["error"])

    def test_order_list_database_failure_returns_service_unavailable(self):
        with patch.object(application, "query", side_effect=Error("test failure")):
            response = self.client.get("/orders")
        self.assertEqual(response.status_code, 503)

    def test_order_detail_includes_items_total_and_outbound_jobs(self):
        jobs = [
            {"job_id": 81, "item_id": 71, "status": "DONE", "retry_count": 0,
             "product_name": "레드 패키지", "created_at": self.now,
             "started_at": self.now, "completed_at": self.now},
            {"job_id": 82, "item_id": 71, "status": "WAITING", "retry_count": 1,
             "product_name": "레드 패키지", "created_at": self.now,
             "started_at": None, "completed_at": None},
        ]
        with patch.object(application, "fetch_order", return_value=self.order) as fetch_order:
            with patch.object(application, "query", return_value=jobs) as query:
                with rendered_contexts() as contexts:
                    response = self.client.get("/orders/123")
        self.assertEqual(response.status_code, 200)
        fetch_order.assert_called_once_with(123)
        self.assertEqual(query.call_args.args[1], (123,))
        self.assertIn("outbound_jobs", query.call_args.args[0])
        self.assertEqual(contexts[-1][1]["jobs"], jobs)
        self.assertEqual(contexts[-1][1]["order"]["total"], Decimal("24000"))
        self.assertIn("MK-000123".encode(), response.data)
        self.assertIn("레드 패키지".encode(), response.data)
        self.assertIn("24,000원".encode(), response.data)

    def test_missing_order_detail_returns_not_found_without_job_query(self):
        with patch.object(application, "fetch_order", return_value=None):
            with patch.object(application, "query") as query:
                response = self.client.get("/orders/123")
        self.assertEqual(response.status_code, 404)
        query.assert_not_called()

    def test_order_detail_database_failures_return_service_unavailable(self):
        for stage in ["order", "jobs"]:
            with self.subTest(stage=stage):
                with patch.object(
                    application, "fetch_order", return_value=self.order,
                    side_effect=Error("test failure") if stage == "order" else None,
                ):
                    with patch.object(application, "query", side_effect=Error("test failure")):
                        response = self.client.get("/orders/123")
                self.assertEqual(response.status_code, 503)

    def test_inquiry_renders_products_jobs_and_detection_logs_using_read_queries(self):
        products = [
            {"product_id": 1, "name": "레드 패키지", "color": "red",
             "price": Decimal("12000"), "stock": 20, "min_stock": 5},
        ]
        jobs = [
            {"job_id": 81, "order_id": 123, "product_name": "레드 패키지",
             "status": "DONE", "retry_count": 0, "created_at": self.now},
        ]
        logs = [
            {"log_id": 91, "order_id": 123, "expected_name": "레드 패키지",
             "detected_name": None, "result": "UNKNOWN", "destination": None,
             "created_at": self.now},
        ]
        with patch.object(application, "query", side_effect=[products, jobs, logs]) as query:
            with rendered_contexts() as contexts:
                response = self.client.get("/inquiry")
        self.assertEqual(response.status_code, 200)
        context = contexts[-1][1]
        self.assertEqual(context["products"], products)
        self.assertEqual(context["jobs"], jobs)
        self.assertEqual(context["logs"], logs)
        self.assertIn("레드 패키지".encode(), response.data)
        self.assertIn("MK-000123".encode(), response.data)
        self.assertEqual(query.call_count, 3)
        statements = [" ".join(call.args[0].split()).upper() for call in query.call_args_list]
        self.assertTrue(all(sql.startswith("SELECT ") for sql in statements))
        self.assertIn("LIMIT 100", statements[1])
        self.assertIn("LIMIT 100", statements[2])

    def test_inquiry_database_failure_at_each_stage_returns_service_unavailable(self):
        for stage in range(3):
            with self.subTest(stage=stage):
                with patch.object(application, "query", side_effect=[[]] * stage + [Error("test failure")]):
                    response = self.client.get("/inquiry")
                self.assertEqual(response.status_code, 503)

    def test_order_post_still_commits_order_items_and_jobs_at_shared_orders_path(self):
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.fetchall.return_value = [
            {"product_id": 1, "name": "레드 패키지", "price": Decimal("12000"), "stock": 20},
        ]

        def execute(sql, params=None):
            if "INSERT INTO orders " in sql:
                cursor.lastrowid = 123
            elif "INSERT INTO order_items " in sql:
                cursor.lastrowid = 71

        cursor.execute.side_effect = execute
        with patch.object(application, "get_db", return_value=connection):
            with patch.object(application, "query") as query:
                response = post_order(self.client, data={"quantity_1": "2", "expected_price_1": "12000"})
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/orders/complete/123"))
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()
        query.assert_not_called()
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(sum("INSERT INTO orders " in sql for sql in statements), 1)
        self.assertEqual(sum("INSERT INTO order_items " in sql for sql in statements), 1)
        self.assertEqual(sum("INSERT INTO outbound_jobs " in sql for sql in statements), 1)
        self.assertFalse(any("UPDATE products" in sql for sql in statements))


if __name__ == "__main__":
    unittest.main()
