"""Cart drawer integration, with mocked products and no live DB writes."""
from html.parser import HTMLParser
import unittest
from unittest.mock import patch

import app as application


class DrawerMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes = {}
        self.scripts = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if attrs.get('id'):
            self.nodes[attrs['id']] = (tag, attrs)
        if tag == 'script':
            self.scripts.append(attrs.get('src', ''))


class CartDrawerTests(unittest.TestCase):
    def test_empty_catalog_still_has_a_closed_accessible_drawer(self):
        application.app.config.update(TESTING=True, SECRET_KEY='drawer-tests-only')
        with patch.object(application, 'fetch_products', return_value=[]), patch.object(application, 'get_db', side_effect=AssertionError('No DB')):
            html = application.app.test_client().get('/').get_data(as_text=True)
        parsed = DrawerMarkup(html)
        tag, attrs = parsed.nodes['cart-drawer']
        self.assertEqual(tag, 'aside')
        self.assertIn('hidden', attrs)
        self.assertIn('floating-cart', parsed.nodes)
        self.assertNotIn('open', attrs)
        self.assertEqual(attrs['aria-labelledby'], 'cart-drawer-title')
        self.assertIn('아직 담은 상품이 없어요', html)
        self.assertIn('disabled', parsed.nodes['cart-checkout'][1])
        self.assertEqual(parsed.nodes['cart-checkout'][1]['type'], 'button')
        drawer_script = next(i for i, src in enumerate(parsed.scripts) if '/cart-drawer.js' in src)
        order_script = next(i for i, src in enumerate(parsed.scripts) if '/order.js' in src)
        self.assertLess(drawer_script, order_script)

    def test_other_pages_link_back_to_home_with_cart_open_request(self):
        application.app.config.update(TESTING=True, SECRET_KEY='drawer-tests-only')
        with patch.object(application, 'get_db', side_effect=AssertionError('No DB')):
            html = application.app.test_client().get('/lookup').get_data(as_text=True)
        self.assertIn('/?cart=open#products', html)
        self.assertNotIn('aria-controls="cart-drawer"', html)


if __name__ == '__main__':
    unittest.main()
