"""Editorial guide tests. No live MySQL writes or schema changes."""
import json
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import app as application
from product_guides import load_guides, guide_for, GUIDE_PATH


class ProductGuideTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True,SECRET_KEY='guide-test-only')
        self.client=application.app.test_client()
        self.guides=load_guides()
        self.product=dict(product_id=1,name='딸기 500g',color='RED',price=Decimal('1000.00'),stock=7)

    def test_all_twelve_known_products_have_separate_guidance(self):
        self.assertEqual(set(self.guides),{str(n) for n in range(1,13)})
        for product_id,entry in self.guides.items():
            with self.subTest(product_id=product_id):
                product=dict(product_id=int(product_id),name=entry['names'][0])
                self.assertIsNotNone(guide_for(product,self.guides))
                for field in ['storage','preparation','serving','summary']:self.assertTrue(entry[field])

    def test_editorial_file_never_defines_price_stock_origin_or_expiry(self):
        data=json.loads(GUIDE_PATH.read_text(encoding='utf-8'))
        for entry in data['products'].values():
            self.assertEqual(set(entry),{'names','summary','storage','preparation','serving','sources'})

    def test_reused_id_new_name_and_unregistered_id_do_not_inherit_wrong_advice(self):
        for product in [dict(self.product,name='닭가슴살 500g'),dict(self.product,name='딸기잼'),dict(self.product,name='딸기 1kg'),dict(self.product,product_id=99)]:
            self.assertIsNone(guide_for(product,self.guides))
        self.assertIsNotNone(guide_for(dict(self.product,name='딸기500g'),self.guides))

    def test_missing_invalid_and_wrong_version_files_fail_safely(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'guide.json'
            self.assertEqual(load_guides(path),{})
            for text in ['not-json','[]','{"version":2,"products":{}}']:
                # Fixture-only writes in isolated temp directories.
                path.write_text(text,encoding='utf-8')
                self.assertEqual(load_guides(path),{})

    def test_invalid_entries_are_skipped_without_discarding_valid_entries(self):
        data=json.loads(GUIDE_PATH.read_text(encoding='utf-8'))
        data['products']['2']['sources']=['javascript:unsafe']
        data['products']['3']['storage']=[]
        with TemporaryDirectory() as folder:
            path=Path(folder)/'guide.json';path.write_text(json.dumps(data),encoding='utf-8')
            loaded=load_guides(path)
        self.assertIn('1',loaded);self.assertNotIn('2',loaded);self.assertNotIn('3',loaded)

    def test_home_and_refresh_html_preserve_exact_db_values_without_extra_db_queries(self):
        with patch.object(application,'fetch_products',return_value=[self.product]),patch.object(application,'get_db',side_effect=AssertionError('No extra database reads')):
            home=self.client.get('/').get_data(as_text=True)
            data=self.client.get('/api/products').get_json()
        self.assertIn('data-price="1000.00"',home)
        self.assertIn('data-stock="7"',home)
        self.assertEqual(data['products'][0]['price'],'1000.00')
        self.assertIn('상품 보관과 손질 안내',data['html'])
        self.assertIn('먹기 직전에',data['html'])
        self.assertIn('data-price="1000.00"',data['html'])
        self.assertIn('id="detail-logistics"',home)

    def test_new_or_renamed_product_renders_explicit_fallback(self):
        with patch.object(application,'fetch_products',return_value=[dict(self.product,name='닭가슴살 500g')]):
            html=self.client.get('/').get_data(as_text=True)
        self.assertIn('상품 안내 준비 중',html)
        self.assertNotIn('요거트나 시리얼',html)

    def test_description_text_is_escaped_and_source_links_are_whitelisted(self):
        self.guides['1']['summary']='<script>unsafe()</script>'
        with patch.object(application,'load_guides',return_value=self.guides),patch.object(application,'fetch_products',return_value=[self.product]):
            html=self.client.get('/').get_data(as_text=True)
        self.assertIn('&lt;script&gt;unsafe()&lt;/script&gt;',html)
        self.assertNotIn('<script>unsafe()',html)
        self.assertIn('rel="noopener noreferrer"',html)
        self.assertIn('https://www.fda.gov/',html)

    def test_file_unavailable_does_not_block_purchases_or_catalog(self):
        with patch.object(application,'load_guides',return_value={}),patch.object(application,'fetch_products',return_value=[self.product]):
            response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertIn('id="order-button"',response.get_data(as_text=True))
        self.assertIn('data-stock="7"',response.get_data(as_text=True))

    def test_description_file_is_reread_without_restarting_python(self):
        data=json.loads(GUIDE_PATH.read_text(encoding='utf-8'))
        with TemporaryDirectory() as folder:
            path=Path(folder)/'guide.json';path.write_text(json.dumps(data),encoding='utf-8')
            first=load_guides(path)['1']['summary']
            data['products']['1']['summary']='수정된 상품 안내'
            path.write_text(json.dumps(data),encoding='utf-8')
            self.assertNotEqual(first,load_guides(path)['1']['summary'])


if __name__=='__main__':unittest.main()
