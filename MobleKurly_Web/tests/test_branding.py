"""Brand integration checks; no live database or real orders."""
import json
import unittest
from html.parser import HTMLParser
from unittest.mock import patch

import app as application


class BrandElements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.images = []
        self.icons = []
        self.apple_touch_icons = []
        self.manifests = []
        self.theme_colors = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == 'img' and attributes.get('class') == 'brand-wordmark':
            self.images.append(attributes)
        if tag == 'link' and attributes.get('rel') == 'icon':
            self.icons.append(attributes)
        if tag == 'link' and attributes.get('rel') == 'apple-touch-icon':
            self.apple_touch_icons.append(attributes)
        if tag == 'link' and attributes.get('rel') == 'manifest':
            self.manifests.append(attributes)
        if tag == 'meta' and attributes.get('name') == 'theme-color':
            self.theme_colors.append(attributes.get('content'))


class BrandingTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY='branding-tests-only')
        self.client = application.app.test_client()

    def test_header_and_footer_use_the_approved_compact_wordmark(self):
        with patch.object(application, 'fetch_products', return_value=[]):
            with patch.object(application, 'get_db', side_effect=AssertionError('No live database')):
                response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        elements = BrandElements(html)
        self.assertEqual(len(elements.images), 2)
        for image in elements.images:
            self.assertTrue(image['src'].endswith('/images/kurly-by-moble-wordmark-v6.png'))
            self.assertIn('모블 컬리', image['alt'])
            self.assertEqual((image['width'], image['height']), ('1781', '883'))
        self.assertNotIn('brand-symbol', html)
        self.assertIn('brand-20261020', html)
        self.assertEqual({icon['type'] for icon in elements.icons}, {'image/png', 'image/x-icon'})
        self.assertEqual(len(elements.icons), 3)
        self.assertTrue(all('shortcut-v7' in icon['href'] for icon in elements.icons))
        self.assertTrue(all('admin' not in icon['href'] for icon in elements.icons))
        self.assertEqual(len(elements.apple_touch_icons), 1)
        self.assertIn('shortcut-v7-180.png', elements.apple_touch_icons[0]['href'])
        self.assertEqual(len(elements.manifests), 1)
        self.assertIn('/static/site.webmanifest', elements.manifests[0]['href'])
        self.assertEqual(elements.theme_colors, ['#0992f2'])

    def test_brand_images_and_windows_shortcut_icons_are_served_locally(self):
        assets = {
            'kurly-by-moble-wordmark-v6.png': b'\x89PNG\r\n\x1a\n',
            'moble-kurly-shortcut-v7.png': b'\x89PNG\r\n\x1a\n',
            'moble-kurly-shortcut-v7-180.png': b'\x89PNG\r\n\x1a\n',
            'moble-kurly-shortcut-v7-192.png': b'\x89PNG\r\n\x1a\n',
            'moble-kurly-shortcut-v7-512.png': b'\x89PNG\r\n\x1a\n',
            'moble-kurly-shortcut-v7.ico': b'\x00\x00\x01\x00',
            'moble-kurly-admin-shortcut-v6.ico': b'\x00\x00\x01\x00',
        }
        for filename, signature in assets.items():
            with self.subTest(filename=filename):
                response = self.client.get('/static/images/' + filename)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data.startswith(signature))
                response.close()

        manifest_response = self.client.get('/static/site.webmanifest')
        self.assertEqual(manifest_response.status_code, 200)
        manifest = json.loads(manifest_response.get_data(as_text=True))
        manifest_response.close()
        self.assertEqual(manifest['name'], '모블 컬리')
        self.assertEqual(manifest['theme_color'], '#0992f2')
        self.assertEqual(
            {icon['sizes'] for icon in manifest['icons']},
            {'192x192', '512x512'},
        )


if __name__ == '__main__':
    unittest.main()
