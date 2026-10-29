"""The shop reads current catalog values and never invents DB prices or stock.

All database access in this module is mocked. No live MySQL data is changed.
"""

import unittest
from decimal import Decimal
from html.parser import HTMLParser
from unittest.mock import Mock, patch

from mysql.connector import Error

import app as application
from order_support import post_order
import db as database_connections


def product(product_id=1, name="DB 상품명", color="red", price="1234.50", stock=150):
    return {"product_id": product_id, "name": name, "color": color,
            "price": Decimal(price), "stock": stock}


def mock_database(products):
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchall.side_effect = lambda: [dict(row) for row in products]

    def execute(sql, _params=None):
        if "INSERT INTO orders " in " ".join(sql.split()):
            cursor.lastrowid = 901
        elif "INSERT INTO order_items " in " ".join(sql.split()):
            cursor.lastrowid = 902

    cursor.execute.side_effect = execute
    return connection, cursor


class CardParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.cards = {}
        self.inputs = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article" and "product-card" in attrs.get("class", "").split():
            self.cards[attrs["data-id"]] = attrs
        if tag == "input" and attrs.get("name"):
            self.inputs[attrs["name"]] = attrs


class CatalogTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY="test-catalog")
        self.client = application.app.test_client()

    def test_won_retains_database_decimals_and_zero_without_rounding(self):
        for value, expected in [
            (Decimal("12000.00"), "12,000원"),
            (Decimal("1234.50"), "1,234.5원"),
            (Decimal("1234.56"), "1,234.56원"),
            (Decimal("0.00"), "0원"),
        ]:
            with self.subTest(value=value):
                self.assertEqual(application.won(value), expected)

    def test_fetch_products_reads_only_catalog_columns_and_returns_connection(self):
        products = [product()]
        connection, cursor = mock_database(products)
        with patch.object(application, "get_db", return_value=connection):
            result = application.fetch_products()
        self.assertEqual(result, products)
        self.assertEqual(
            " ".join(cursor.execute.call_args.args[0].split()),
            "SELECT product_id, name, color, price, stock FROM products ORDER BY product_id",
        )
        cursor.close.assert_called_once()
        connection.close.assert_called_once()

    def test_fetch_products_returns_connection_even_if_query_fails(self):
        connection, cursor = mock_database([])
        cursor.execute.side_effect = Error("test database failure")
        with patch.object(application, "get_db", return_value=connection):
            with self.assertRaises(Error):
                application.fetch_products()
        cursor.close.assert_called_once()
        connection.close.assert_called_once()

    def test_home_reads_price_name_and_stock_again_on_every_request(self):
        products = [product(name="수정 전 DB 상품", price="1234.50", stock=150)]
        connection, cursor = mock_database(products)
        with patch.object(application, "get_db", return_value=connection):
            before = self.client.get("/")
            products[0].update(name="수정 후 DB 상품", price=Decimal("987.65"), stock=7)
            after = self.client.get("/")
        self.assertEqual(before.status_code, 200)
        self.assertEqual(after.status_code, 200)
        self.assertIn("수정 전 DB 상품".encode(), before.data)
        self.assertIn("1,234.5원".encode(), before.data)
        self.assertIn("수정 후 DB 상품".encode(), after.data)
        self.assertIn("987.65원".encode(), after.data)
        self.assertNotIn("수정 전 DB 상품".encode(), after.data)
        self.assertEqual(CardParser(before.get_data(as_text=True)).cards["1"]["data-stock"], "150")
        self.assertEqual(CardParser(after.get_data(as_text=True)).cards["1"]["data-stock"], "7")
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertEqual(connection.close.call_count, 2)
        self.assertIn("no-store", before.headers.get("Cache-Control", ""))
        self.assertIn("no-store", after.headers.get("Cache-Control", ""))

    def test_cards_use_zero_decimal_and_full_database_stock_values(self):
        products = [product(price="0.00", stock=150),
                    product(2, "품절 DB 상품", "blue", "1234.56", 0)]
        connection, _cursor = mock_database(products)
        with patch.object(application, "get_db", return_value=connection):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        parsed = CardParser(html)
        self.assertEqual(Decimal(parsed.cards["1"]["data-price"]), Decimal("0.00"))
        self.assertEqual(parsed.cards["1"]["data-stock"], "150")
        self.assertEqual(parsed.inputs["quantity_1"]["max"], "150")
        self.assertEqual(Decimal(parsed.inputs["expected_price_1"]["value"]), Decimal("0"))
        self.assertEqual(parsed.cards["2"]["data-stock"], "0")
        if "quantity_2" in parsed.inputs:
            self.assertEqual(parsed.inputs["quantity_2"]["max"], "0")
            self.assertIn("disabled", parsed.inputs["quantity_2"])
        self.assertIn("0원", html)
        self.assertIn("1,234.56원", html)
        self.assertIn("일시 품절", html)

    def test_api_reads_current_catalog_and_returns_exact_prices_as_strings(self):
        products = [product(price="1234.50", stock=150)]
        connection, cursor = mock_database(products)
        with patch.object(application, "get_db", return_value=connection):
            before = self.client.get("/api/products")
            products[0].update(price=Decimal("0.00"), stock=0)
            after = self.client.get("/api/products")
        self.assertEqual(before.status_code, 200)
        self.assertEqual(after.status_code, 200)
        body = before.get_json()
        self.assertEqual(body["database"], "moblekurly")
        self.assertEqual(body["products"], [
            {"product_id": 1, "name": "DB 상품명", "color": "red",
             "price": "1234.50", "stock": 150},
        ])
        self.assertEqual(after.get_json()["products"][0]["price"], "0.00")
        self.assertEqual(after.get_json()["products"][0]["stock"], 0)
        self.assertIn("1,234.5원", body["html"])
        self.assertIn("0원", after.get_json()["html"])
        self.assertIn("no-store", before.headers.get("Cache-Control", ""))
        self.assertIn("no-store", after.headers.get("Cache-Control", ""))
        self.assertEqual(cursor.execute.call_count, 2)

    def test_team_catalog_is_identical_in_home_api_and_refresh_cards(self):
        products = [
            product(1, "RED 상품", "RED", "1000.00", 50),
            product(2, "BLUE 상품", "BLUE", "1000.00", 20),
            product(3, "YELLOW 상품", "YELLOW", "1000.00", 20),
            product(4, "GREEN 상품", "GREEN", "1000.00", 30),
        ]
        connection, cursor = mock_database(products)
        with patch.object(application, "get_db", return_value=connection):
            homepage = self.client.get("/")
            api = self.client.get("/api/products")

        self.assertEqual(homepage.status_code, 200)
        self.assertEqual(api.status_code, 200)
        body = api.get_json()
        self.assertEqual(body["database"], "moblekurly")
        self.assertEqual(body["products"], [
            {**row, "price": str(row["price"])} for row in products
        ])

        # Database colors remain uppercase in JSON; only the visual CSS key is
        # normalized. Neither rendering path may substitute the old demo rows.
        for html in [homepage.get_data(as_text=True), body["html"]]:
            with self.subTest(rendering="homepage" if "<!DOCTYPE" in html else "refresh"):
                parsed = CardParser(html)
                self.assertEqual(set(parsed.cards), {"1", "2", "3", "4"})
                self.assertEqual(html.count('class="product-price">1,000원'), 4)
                for row in products:
                    product_id = str(row["product_id"])
                    card = parsed.cards[product_id]
                    self.assertEqual(card["data-name"], row["name"])
                    self.assertEqual(card["data-color"], row["color"].lower())
                    self.assertEqual(card["data-price"], "1000.00")
                    self.assertEqual(card["data-stock"], str(row["stock"]))
                    self.assertEqual(parsed.inputs[f"quantity_{product_id}"]["max"], str(row["stock"]))
                    self.assertEqual(parsed.inputs[f"expected_price_{product_id}"]["value"], "1000.00")
                for demo_price in ["12,000원", "13,000원", "11,000원", "14,000원"]:
                    self.assertNotIn(demo_price, html)

        self.assertEqual(cursor.execute.call_count, 2)
        connection.commit.assert_not_called()

    def test_empty_catalog_stays_empty_instead_of_replacing_it_with_demo_data(self):
        connection, _cursor = mock_database([])
        with patch.object(application, "get_db", return_value=connection):
            homepage = self.client.get("/")
            api = self.client.get("/api/products")
        self.assertEqual(homepage.status_code, 200)
        self.assertEqual(CardParser(homepage.get_data(as_text=True)).cards, {})
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.get_json()["products"], [])

    def test_database_failure_is_reported_without_falling_back_to_demo_products(self):
        with patch.object(application, "get_db", side_effect=Error("test database failure")):
            with patch.object(application.app.logger, "exception"):
                homepage = self.client.get("/")
                api = self.client.get("/api/products")
        self.assertEqual(homepage.status_code, 503)
        self.assertEqual(CardParser(homepage.get_data(as_text=True)).cards, {})
        self.assertEqual(api.status_code, 503)
        self.assertTrue(api.get_json()["error"])
        self.assertNotIn("products", api.get_json())
        self.assertIn("no-store", homepage.headers.get("Cache-Control", ""))
        self.assertIn("no-store", api.headers.get("Cache-Control", ""))


class CheckoutCatalogTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY="test-catalog")
        self.client = application.app.test_client()

    def post_order(self, products, data):
        connection, cursor = mock_database(products)
        with patch.object(application, "get_db", return_value=connection):
            response = post_order(self.client, data=data)
        return response, connection, cursor

    def assert_no_inserts(self, cursor):
        self.assertFalse(any(
            " ".join(call.args[0].split()).startswith("INSERT")
            for call in cursor.execute.call_args_list
        ))

    def test_prices_changed_after_page_load_reject_before_any_insert(self):
        response, connection, cursor = self.post_order(
            [product(price="1234.56")],
            {"quantity_1": "2", "expected_price_1": "1234.50"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/"))
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()
        self.assert_no_inserts(cursor)
        with self.client.session_transaction() as session:
            self.assertTrue(session.get("_flashes"), "Price changes must be explained to the buyer.")

    def test_missing_malformed_and_nonfinite_expected_prices_never_create_orders(self):
        for expected in [None, "", "not-a-price", "NaN", "Infinity", "-Infinity", "0"]:
            with self.subTest(expected_price=expected):
                data = {"quantity_1": "1"}
                if expected is not None:
                    data["expected_price_1"] = expected
                response, connection, cursor = self.post_order([product()], data)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.location.endswith("/"))
                connection.commit.assert_not_called()
                self.assert_no_inserts(cursor)

    def test_stock_reduction_since_page_load_rejects_without_creating_jobs(self):
        response, connection, cursor = self.post_order(
            [product(stock=1)], {"quantity_1": "2", "expected_price_1": "1234.50"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/"))
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()
        self.assert_no_inserts(cursor)

    def test_out_of_stock_product_cannot_be_ordered_even_with_current_price(self):
        response, connection, cursor = self.post_order(
            [product(stock=0)], {"quantity_1": "1", "expected_price_1": "1234.50"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/"))
        connection.commit.assert_not_called()
        self.assert_no_inserts(cursor)

    def test_quantities_over_99_are_allowed_when_database_stock_allows_it(self):
        response, connection, cursor = self.post_order(
            [product(stock=150)], {"quantity_1": "125", "expected_price_1": "1234.50"},
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/orders/complete/901"))
        connection.commit.assert_called_once()
        item_inserts = [call for call in cursor.execute.call_args_list if "INSERT INTO order_items" in call.args[0]]
        self.assertEqual(len(item_inserts), 1)
        self.assertEqual(item_inserts[0].args[1], (901, 1, 125, Decimal("1234.50")))

    def test_order_total_uses_locked_database_price_not_extra_client_price_fields(self):
        response, connection, cursor = self.post_order(
            [product(price="1234.56")],
            {"quantity_1": "2", "expected_price_1": "1234.5600",
             "price_1": "1", "unit_price": "1", "total_price": "2"},
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/orders/complete/901"))
        connection.commit.assert_called_once()
        item_inserts = [call for call in cursor.execute.call_args_list if "INSERT INTO order_items" in call.args[0]]
        self.assertEqual(item_inserts[0].args[1], (901, 1, 2, Decimal("1234.56")))
        statements = [" ".join(call.args[0].split()) for call in cursor.execute.call_args_list]
        self.assertTrue(any("FOR UPDATE" in sql for sql in statements))
        self.assertFalse(any(sql.startswith("UPDATE products") for sql in statements))

    def test_zero_database_price_is_stored_as_zero_instead_of_a_demo_default(self):
        response, connection, cursor = self.post_order(
            [product(price="0.00")], {"quantity_1": "2", "expected_price_1": "0"},
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/orders/complete/901"))
        connection.commit.assert_called_once()
        item_inserts = [call for call in cursor.execute.call_args_list if "INSERT INTO order_items" in call.args[0]]
        self.assertEqual(item_inserts[0].args[1][-1], Decimal("0.00"))

    def test_one_stale_price_in_multiple_products_rolls_back_the_entire_order(self):
        response, connection, cursor = self.post_order(
            [product(1, price="1000"), product(2, price="2000")],
            {"quantity_1": "1", "expected_price_1": "1000",
             "quantity_2": "1", "expected_price_2": "1500"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/"))
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()
        self.assert_no_inserts(cursor)


class DatabaseSelectionTests(unittest.TestCase):
    def test_only_moblekurly_is_accepted_before_pool_creation_or_reuse(self):
        for existing_pool in [None, Mock()]:
            with self.subTest(pool_already_exists=existing_pool is not None):
                with patch.dict(database_connections.DB_CONFIG, {"database": "unapproved_catalog"}):
                    with patch.object(database_connections, "_pool", existing_pool):
                        with patch.object(database_connections.pooling, "MySQLConnectionPool") as create_pool:
                            with self.assertRaises(Error):
                                database_connections.get_db()
                        create_pool.assert_not_called()
                if existing_pool is not None:
                    existing_pool.get_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
