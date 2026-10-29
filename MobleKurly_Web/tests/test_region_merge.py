"""Region persistence contract. No live MySQL writes or schema changes."""
import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from mysql.connector import Error
import app as application
from checkout_demo import REGIONS
from test_app import FakeConnection
from order_support import post_order


class RegionMergeTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY='region-test-only')
        self.client=application.app.test_client()
        with self.client.session_transaction() as session: session['demo_csrf']='csrf'
        self.values=dict(checkout_mode='demo_v1',demo_csrf='csrf',demo_ack='1',
                         payment_method='card',delivery_region='GYEONGGI',
                         quantity_1='2',expected_price_1='12000')

    def order(self, region):
        return dict(order_id=7,status='PENDING',ordered_at=datetime(2026,10,19),
                    delivery_region=region,items=[],total=Decimal('24000'))

    def test_each_db_enum_region_is_parameterized_in_same_order_transaction(self):
        self.assertEqual(set(REGIONS),{'SEOUL','GYEONGGI','CHUNGCHEONG'})
        for region in REGIONS:
            with self.subTest(region=region):
                connection=FakeConnection()
                with patch.object(application,'get_db',return_value=connection):
                    result=post_order(self.client,data=dict(self.values,delivery_region=region))
                self.assertTrue(result.location.endswith('/orders/complete/7'))
                inserts=[(sql,args) for sql,args in connection.cursor_instance.queries if sql.startswith('INSERT')]
                self.assertEqual(len(inserts),3)
                self.assertEqual(inserts[0],("INSERT INTO orders (status, delivery_region) VALUES ('PENDING', %s)",(region,)))
                self.assertEqual(inserts[1][1],(7,1,2,Decimal('12000')))
                self.assertTrue(connection.committed)
                self.assertFalse(any(token in str(inserts) for token in ['ALTER TABLE','UPDATE products','customer_phone','delivery_address']))

    def test_unsupported_old_and_injected_region_never_reach_db(self):
        for region in ['', 'GYEONGSANG', 'gyeonggi', 'seoul', "SEOUL'); DROP TABLE orders;--"]:
            with self.subTest(region=region),patch.object(application,'get_db',side_effect=AssertionError('No DB')):
                self.assertTrue(post_order(self.client,data=dict(self.values,delivery_region=region)).location.endswith('/'))

    def test_all_order_views_show_db_region_in_a_fresh_browser(self):
        for url in ['/orders/complete/7','/lookup?order_number=7','/orders/7']:
            with self.subTest(url=url),patch.object(application,'fetch_order',return_value=self.order('SEOUL')),patch.object(application,'query',return_value=[]):
                html=application.app.test_client().get(url).get_data(as_text=True)
            self.assertIn('배송 권역 · DB 기준',html)
            self.assertIn('<dd>서울</dd>',html)
            self.assertNotIn('선택한 결제 수단',html)

    def test_cookie_cannot_override_db_region_or_fill_null_legacy_region(self):
        with self.client.session_transaction() as session:
            session['demo_orders']={'7':{'region':'CHUNGCHEONG','method':'wallet'}}
        for region, label in [('SEOUL','서울'),(None,'미등록')]:
            with patch.object(application,'fetch_order',return_value=self.order(region)):
                html=self.client.get('/orders/complete/7').get_data(as_text=True)
            self.assertIn('<dd>'+label+'</dd>',html)
            self.assertNotIn('<dd>충청도</dd>',html)

    def test_region_schema_failure_rolls_back_without_fallback_or_migration(self):
        connection=FakeConnection()
        original_execute=connection.cursor_instance.execute
        def execute(sql, params=None):
            if 'INSERT INTO orders' in sql:
                raise Error(msg="Unknown column 'delivery_region'",errno=1054)
            return original_execute(sql,params)
        connection.cursor_instance.execute=execute
        with patch.object(application,'get_db',return_value=connection):
            result=post_order(self.client,data=self.values)
        self.assertTrue(result.location.endswith('/'))
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)
        self.assertFalse(any('ALTER ' in sql or 'INSERT INTO order_items' in sql for sql,_ in connection.cursor_instance.queries))

    def test_region_query_reads_are_authoritative_and_filter_is_safe(self):
        connection=FakeConnection()
        connection.cursor_instance.fetchone=lambda: self.order('SEOUL')
        connection.cursor_instance.fetchall=lambda: []
        with patch.object(application,'get_db',return_value=connection):
            order=application.fetch_order(7)
        self.assertEqual(order['delivery_region'],'SEOUL')
        self.assertIn('delivery_region',connection.cursor_instance.queries[0][0])
        self.assertEqual(application.delivery_region_ko(None),'미등록')
        self.assertEqual(application.delivery_region_ko('UNKNOWN'),'확인 필요')

    def test_legacy_noncheckout_client_is_not_assigned_a_default_region(self):
        connection=FakeConnection()
        with patch.object(application,'get_db',return_value=connection):
            post_order(self.client,data={'quantity_1':'1','expected_price_1':'12000'})
        self.assertIn(("INSERT INTO orders (status) VALUES ('PENDING')",None),connection.cursor_instance.queries)


if __name__=='__main__': unittest.main()
