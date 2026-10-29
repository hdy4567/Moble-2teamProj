"""Image/cart merge regressions; all catalog data is mocked, never live MySQL."""

import unittest
from collections import Counter
from decimal import Decimal
from html.parser import HTMLParser
from unittest.mock import patch

import app as application


PHOTO_NAMES = {
    1: "strawberry", 2: "blueberry", 3: "yellow_pepper", 4: "broccoli",
    5: "tomato", 6: "apple", 7: "grapes", 8: "eggplant", 9: "carrot",
    10: "corn", 11: "cucumber", 12: "cabbage",
}


def fixture_product(product_id=1, price="1234.56", stock=17):
    return {
        "product_id": product_id, "name": f"DB 상품 {product_id}", "color": "RED",
        "price": Decimal(price), "stock": stock,
    }


class ShopMarkup(HTMLParser):
    """Capture structural attributes without assuming HTML formatting."""

    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current_form = None
        self.ids = Counter()
        self.cards = {}
        self.inputs = []
        self.images = []
        self.buttons = []
        self.cart_forms = []
        self.cart_open = False
        self.photo_fallbacks = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if attrs.get("id"):
            self.ids[attrs["id"]] += 1
        if tag == "form":
            self.forms.append(attrs)
            self.current_form = attrs.get("id")
        if attrs.get("id") == "cart-edit-panel":
            self.cart_forms.append(self.current_form)
            self.cart_open = True
        if tag == "article" and "product-card" in attrs.get("class", "").split():
            self.cards[attrs["data-id"]] = attrs
        if tag == "input":
            self.inputs.append((self.current_form, attrs))
        if tag == "img":
            self.images.append(attrs)
        if tag == "button":
            self.buttons.append((self.cart_open, attrs))
        if tag == "span" and "product-photo" in attrs.get("class", "").split():
            self.photo_fallbacks.append(attrs)

    def handle_endtag(self, tag):
        if tag == "form":
            self.current_form = None
        if tag == "section" and self.cart_open:
            self.cart_open = False


class CartPhotoMergeTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY="test-cart-photos")
        self.client = application.app.test_client()
        # An accidental real DB call must fail before opening a connection.
        guard = patch.object(application, "get_db", side_effect=AssertionError("Live DB forbidden"))
        guard.start()
        self.addCleanup(guard.stop)

    def render_home(self, products):
        with patch.object(application, "fetch_products", return_value=products):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_one_cart_panel_inside_existing_form_without_duplicate_quantity_inputs(self):
        products = [fixture_product(1), fixture_product(2)]
        parsed = ShopMarkup(self.render_home(products))
        self.assertEqual(parsed.cart_forms, ["order-form"])
        for element_id in ["order-form", "cart-edit-panel", "cart-edit-items", "cart-clear"]:
            self.assertEqual(parsed.ids[element_id], 1)
        self.assertEqual([key for key, count in parsed.ids.items() if count > 1], [])
        quantities = [(form, attrs) for form, attrs in parsed.inputs
                      if attrs.get("name", "").startswith("quantity_")]
        self.assertEqual(Counter(attrs["name"] for _form, attrs in quantities),
                         Counter({"quantity_1": 1, "quantity_2": 1}))
        self.assertTrue(all(form == "order-form" for form, _attrs in quantities))
        cart_buttons = [attrs for inside_cart, attrs in parsed.buttons if inside_cart]
        self.assertTrue(cart_buttons)
        self.assertTrue(all(attrs.get("type") == "button" for attrs in cart_buttons))
        expected_prices = [attrs for _form, attrs in parsed.inputs
                           if attrs.get("name", "").startswith("expected_price_")]
        self.assertEqual(Counter(attrs["name"] for attrs in expected_prices),
                         Counter({"expected_price_1": 1, "expected_price_2": 1}))

    def test_twelve_individual_photos_have_matching_card_data_and_accessible_local_assets(self):
        products = [fixture_product(product_id) for product_id in PHOTO_NAMES]
        parsed = ShopMarkup(self.render_home(products))
        photos = [attrs for attrs in parsed.images
                  if "product-photo-img" in attrs.get("class", "").split()]
        self.assertEqual(len(photos), len(products))
        for row, image in zip(products, photos):
            product_id = row["product_id"]
            expected_url = f"/static/images/products/{PHOTO_NAMES[product_id]}.webp"
            with self.subTest(product_id=product_id):
                self.assertEqual(parsed.cards[str(product_id)]["data-photo"], expected_url)
                self.assertEqual(image["src"], expected_url)
                self.assertEqual(image["alt"], row["name"])
                self.assertEqual(image["loading"], "lazy")
                asset = self.client.get(expected_url)
                self.addCleanup(asset.close)
                self.assertEqual(asset.status_code, 200)
                self.assertEqual(asset.mimetype, "image/webp")
                self.assertGreater(len(asset.data), 100)
                self.assertEqual(asset.data[:4], b"RIFF")
                self.assertEqual(asset.data[8:12], b"WEBP")

    def test_unknown_product_id_keeps_safe_atlas_fallback_instead_of_broken_photo_url(self):
        parsed = ShopMarkup(self.render_home([fixture_product(999)]))
        self.assertEqual(parsed.cards["999"]["data-photo"], "")
        self.assertEqual([attrs for attrs in parsed.images
                          if "product-photo-img" in attrs.get("class", "").split()], [])
        self.assertEqual(len(parsed.photo_fallbacks), 1)
        self.assertIn("color-red", parsed.photo_fallbacks[0]["class"].split())
        asset = self.client.get("/static/images/produce-atlas.png")
        self.addCleanup(asset.close)
        self.assertEqual(asset.status_code, 200)
        self.assertGreater(len(asset.data), 100)

    def test_api_photo_markup_continues_to_use_current_db_price_name_and_stock(self):
        products = [fixture_product(1, price="1234.56", stock=150),
                    fixture_product(2, price="0.00", stock=0)]
        with patch.object(application, "fetch_products", side_effect=lambda: [dict(row) for row in products]):
            before = self.client.get("/api/products")
            products[0].update(name="DB에서 수정한 상품", price=Decimal("9876.54"), stock=3)
            after = self.client.get("/api/products")
        for response in [before, after]:
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response.headers["Cache-Control"])
        first_payload = before.get_json()
        payload = after.get_json()
        self.assertEqual(payload["database"], "moblekurly")
        self.assertEqual(first_payload["products"][0]["price"], "1234.56")
        self.assertEqual(payload["products"][0]["price"], "9876.54")
        parsed = ShopMarkup(payload["html"])
        self.assertEqual(parsed.cards["1"]["data-name"], "DB에서 수정한 상품")
        self.assertEqual(parsed.cards["1"]["data-price"], "9876.54")
        self.assertEqual(parsed.cards["1"]["data-stock"], "3")
        inputs = {attrs["name"]: attrs for _form, attrs in parsed.inputs}
        self.assertEqual(inputs["quantity_1"]["max"], "3")
        self.assertEqual(inputs["expected_price_1"]["value"], "9876.54")
        self.assertEqual(inputs["quantity_2"]["max"], "0")
        self.assertIn("disabled", inputs["quantity_2"])
        self.assertEqual(inputs["expected_price_2"]["value"], "0.00")
        self.assertIn("9,876.54원", payload["html"])
        self.assertNotIn("1,234.56원", payload["html"])


if __name__ == "__main__":
    unittest.main()
