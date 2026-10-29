"""Produce-catalog regression tests using mocks and an in-memory database only.

Prices below are arbitrary test fixtures, not approved selling prices or seed
data. Application code must read whichever names, prices and stock MySQL has.
No test in this module connects to or changes the team's MySQL database.
"""

import sqlite3
import unittest
from datetime import datetime
from decimal import Decimal
from html.parser import HTMLParser
from unittest.mock import Mock, patch

import app as application
from order_support import post_order


def sample_catalog():
    """Return independent fixtures; their prices are not production defaults."""
    return [
        {"product_id": 1, "name": "딸기 500g", "color": "RED",
         "price": Decimal("14900.00"), "stock": 50},
        {"product_id": 2, "name": "블루베리 125g", "color": "BLUE",
         "price": Decimal("5900.00"), "stock": 20},
        {"product_id": 3, "name": "노랑 파프리카 2입", "color": "YELLOW",
         "price": Decimal("3990.00"), "stock": 20},
        {"product_id": 4, "name": "브로콜리 1입", "color": "GREEN",
         "price": Decimal("2990.00"), "stock": 30},
    ]


def catalog_connection(products):
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchall.side_effect = lambda: [dict(row) for row in products]

    def execute(sql, params=()):
        compact = " ".join(sql.split())
        if compact.startswith("INSERT INTO orders "):
            cursor.lastrowid = 901
        elif compact.startswith("INSERT INTO order_items "):
            cursor.lastrowid = 902

    cursor.execute.side_effect = execute
    return connection, cursor


class ProductCards(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.cards = {}
        self.inputs = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "article" and "product-card" in attributes.get("class", "").split():
            self.cards[attributes["data-id"]] = attributes
        if tag == "input" and attributes.get("name"):
            self.inputs[attributes["name"]] = attributes


class ProduceCatalogTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY="test-produce")
        self.client = application.app.test_client()

    def assert_cards_match_database(self, html, products):
        cards = ProductCards(html)
        self.assertEqual(set(cards.cards), {str(row["product_id"]) for row in products})
        for row in products:
            product_id = str(row["product_id"])
            with self.subTest(product_id=product_id):
                card = cards.cards[product_id]
                self.assertEqual(card["data-name"], row["name"])
                self.assertEqual(card["data-color"], row["color"].lower())
                self.assertEqual(Decimal(card["data-price"]), row["price"])
                self.assertEqual(card["data-stock"], str(row["stock"]))
                self.assertEqual(
                    cards.inputs[f"expected_price_{product_id}"]["value"], str(row["price"]),
                )
                self.assertEqual(cards.inputs[f"quantity_{product_id}"]["max"], str(row["stock"]))
                self.assertIn(application.won(row["price"]), html)

    def test_four_produce_products_keep_database_ids_colors_stock_and_decimal_prices(self):
        products = sample_catalog()
        connection, cursor = catalog_connection(products)
        with patch.object(application, "get_db", return_value=connection):
            home = self.client.get("/")
            api = self.client.get("/api/products")

        self.assertEqual(home.status_code, 200)
        self.assertEqual(api.status_code, 200)
        body = api.get_json()
        self.assertEqual(body["database"], "moblekurly")
        self.assertEqual(body["products"], [
            {**row, "price": str(row["price"])} for row in products
        ])
        for html in [home.get_data(as_text=True), body["html"]]:
            self.assert_cards_match_database(html, products)
        self.assertIn("no-store", home.headers["Cache-Control"])
        self.assertIn("no-store", api.headers["Cache-Control"])
        self.assertEqual(cursor.execute.call_count, 2)
        connection.commit.assert_not_called()

    def test_later_database_changes_override_all_fixture_names_prices_and_stock(self):
        products = sample_catalog()
        connection, _cursor = catalog_connection(products)
        with patch.object(application, "get_db", return_value=connection):
            before = self.client.get("/api/products").get_json()
            for index, row in enumerate(products):
                row.update(name=f"DB에서 바꾼 상품 {index + 1}",
                           price=Decimal("1234.56") + index, stock=3 + index)
            after_home = self.client.get("/")
            after = self.client.get("/api/products").get_json()

        self.assertNotEqual(before["products"], after["products"])
        self.assertEqual(after["products"], [
            {**row, "price": str(row["price"])} for row in products
        ])
        for html in [after_home.get_data(as_text=True), after["html"]]:
            self.assert_cards_match_database(html, products)
            for old_name in ["딸기 500g", "블루베리 125g", "노랑 파프리카 2입", "브로콜리 1입"]:
                self.assertNotIn(f'data-name="{old_name}"', html)

    def test_logistics_returns_current_produce_names_ids_and_stock_without_fabricated_dates(self):
        products = sample_catalog()
        rows = [{
            "product_id": row["product_id"], "name": row["name"], "stock": row["stock"],
            "last_received_at": None, "pending_quantity": 0, "pending_count": 0,
            "checked_at": datetime(2026, 10, 19, 15, 0),
        } for row in products]
        with patch.object(application, "query", return_value=rows) as query:
            response = self.client.get("/api/logistics")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["database"], "moblekurly")
        self.assertIn("p.name", query.call_args.args[0])
        self.assertEqual([
            (row["product_id"], row["name"], row["stock"]) for row in payload["products"]
        ], [(row["product_id"], row["name"], row["stock"]) for row in products])
        for row in payload["products"]:
            self.assertIsNone(row["last_received_at"])
            self.assertIsNone(row["next_arrival_at"])
            self.assertFalse(row["stock_age_known"])

    def test_new_produce_order_snapshots_locked_database_prices_without_updating_products(self):
        products = sample_catalog()
        connection, cursor = catalog_connection(products)
        data = {}
        for row in products:
            product_id = row["product_id"]
            data[f"quantity_{product_id}"] = str(product_id)
            data[f"expected_price_{product_id}"] = str(row["price"])
        with patch.object(application, "get_db", return_value=connection):
            response = post_order(self.client, data=data)

        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/orders/complete/901"))
        connection.commit.assert_called_once()
        statements = [(" ".join(call.args[0].split()), call.args[1] if len(call.args) > 1 else ())
                      for call in cursor.execute.call_args_list]
        self.assertTrue(any("FOR UPDATE" in sql for sql, _params in statements))
        self.assertEqual([
            params for sql, params in statements if sql.startswith("INSERT INTO order_items ")
        ], [(901, row["product_id"], row["product_id"], row["price"]) for row in products])
        self.assertEqual(sum(sql.startswith("INSERT INTO outbound_jobs ") for sql, _params in statements), 4)
        self.assertFalse(any(sql.startswith(("UPDATE products", "DELETE", "REPLACE"))
                             for sql, _params in statements))

    def test_one_changed_produce_price_rejects_entire_stale_cart_before_inserts(self):
        products = sample_catalog()
        data = {}
        for row in products:
            product_id = row["product_id"]
            data[f"quantity_{product_id}"] = "1"
            data[f"expected_price_{product_id}"] = str(row["price"])
        products[2]["price"] = Decimal("4000.50")
        connection, cursor = catalog_connection(products)
        with patch.object(application, "get_db", return_value=connection):
            response = post_order(self.client, data=data)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/"))
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()
        self.assertFalse(any("INSERT INTO" in call.args[0] for call in cursor.execute.call_args_list))

    def test_existing_order_keeps_original_unit_prices_after_produce_catalog_changes(self):
        # Run the application's real SELECT against isolated relational data.
        # This catches replacing oi.unit_price with today's products.price.
        database = sqlite3.connect(":memory:")
        self.addCleanup(database.close)
        database.row_factory = lambda cursor, row: {
            column[0]: row[index] for index, column in enumerate(cursor.description)
        }
        database.executescript("""
            CREATE TABLE orders (order_id INTEGER, status TEXT, ordered_at TEXT,
                                 approved_at TEXT, completed_at TEXT);
            CREATE TABLE products (product_id INTEGER, name TEXT, color TEXT, price NUMERIC);
            CREATE TABLE order_items (item_id INTEGER, order_id INTEGER, product_id INTEGER,
                                      quantity INTEGER, shipped_qty INTEGER, unit_price NUMERIC);
            INSERT INTO orders VALUES (7, 'PENDING', '2026-10-19 10:00:00', NULL, NULL);
            ALTER TABLE orders ADD COLUMN delivery_region TEXT;
            ALTER TABLE orders ADD COLUMN points_used INTEGER DEFAULT 0;
        """)
        for row in sample_catalog():
            product_id = row["product_id"]
            database.execute("INSERT INTO products VALUES (?, ?, ?, ?)",
                             (product_id, row["name"], row["color"], int(row["price"])))
            database.execute("INSERT INTO order_items VALUES (?, 7, ?, ?, 0, 1000)",
                             (70 + product_id, product_id, product_id))
        sqlite_cursor = database.cursor()
        cursor = Mock()
        cursor.execute.side_effect = lambda sql, params: sqlite_cursor.execute(sql.replace("%s", "?"), params)
        cursor.fetchone.side_effect = sqlite_cursor.fetchone
        cursor.fetchall.side_effect = sqlite_cursor.fetchall
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch.object(application, "get_db", return_value=connection):
            order = application.fetch_order(7)

        self.assertEqual([row["name"] for row in order["items"]],
                         [row["name"] for row in sample_catalog()])
        self.assertEqual([Decimal(row["unit_price"]) for row in order["items"]],
                         [Decimal("1000.00")] * 4)
        self.assertEqual(order["total"], Decimal("10000"))
        self.assertNotEqual(order["total"], sum(
            row["product_id"] * row["price"] for row in sample_catalog()
        ))
        connection.commit.assert_not_called()
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
