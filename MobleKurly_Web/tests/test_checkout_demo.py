"""All checkout writes below target mocks, never the team MySQL database."""
import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import app as application
from checkout_demo import REGIONS, METHODS, remember_demo_order, validate_demo_checkout
from test_app import FakeConnection, PRODUCTS
from order_support import post_order


class DemoCheckoutTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY='checkout-test-key')
        self.client = application.app.test_client()
        with self.client.session_transaction() as session:
            session['demo_csrf'] = 'test-csrf'
        self.values = dict(checkout_mode='demo_v1', delivery_region='GYEONGGI',
                           payment_method='card', demo_ack='1', demo_csrf='test-csrf',
                           quantity_1='2', expected_price_1='12000')
        self.order = dict(order_id=7, status='PENDING', delivery_region='GYEONGGI', ordered_at=datetime(2026,10,19,15,0),
                          total=Decimal('24000.00'), items=[dict(name='DB 상품', color='red',
                          unit_price=Decimal('12000'), quantity=2, shipped_qty=0, line_total=Decimal('24000'))])

    def test_only_requested_regions_and_demo_methods(self):
        self.assertEqual(list(REGIONS.values()), ['서울', '경기도', '충청도'])
        for region in REGIONS:
            for method in METHODS:
                with self.subTest(region=region, method=method):
                    selected = validate_demo_checkout(dict(self.values, delivery_region=region, payment_method=method))
                    self.assertEqual(selected, {'region':region, 'method':method})

    def test_original_nonpayment_clients_are_compatible(self):
        self.assertIsNone(validate_demo_checkout({}))

    def test_invalid_mode_region_method_or_consent_rejected_before_db(self):
        for key, value in [('checkout_mode','real_payment'),('delivery_region',''),('delivery_region','seoul'),
                           ('payment_method','real_card'),('demo_ack','0'),('demo_csrf','wrong')]:
            with self.subTest(key=key, value=value):
                with patch.object(application, 'get_db', side_effect=AssertionError('No DB access')):
                    response=post_order(self.client, data=dict(self.values, **{key:value}))
                self.assertEqual(response.status_code,302)
                self.assertTrue(response.location.endswith('/'))

    def test_missing_csrf_rejected_before_db(self):
        values=dict(self.values); values.pop('demo_csrf')
        with patch.object(application, 'get_db', side_effect=AssertionError('No DB access')):
            self.assertEqual(post_order(self.client, data=values).status_code,302)

    def test_success_uses_existing_tables_and_db_price_only(self):
        connection=FakeConnection()
        values=dict(self.values, total='1', payment_amount='1', card_number='must-not-be-stored')
        with patch.object(application, 'get_db', return_value=connection):
            response=post_order(self.client,data=values)
        self.assertTrue(response.location.endswith('/orders/complete/7'))
        self.assertTrue(connection.committed)
        inserts=[(sql,params) for sql,params in connection.cursor_instance.queries if sql.startswith('INSERT')]
        self.assertEqual(len(inserts),3)
        self.assertIn('order_items',inserts[1][0])
        self.assertEqual(inserts[1][1],(7,1,2,Decimal('12000')))
        self.assertIn('delivery_region',inserts[0][0])
        self.assertEqual(inserts[0][1],('GYEONGGI',))
        self.assertFalse(any('payment' in sql.lower() for sql,_ in inserts))
        with self.client.session_transaction() as session:
            self.assertEqual(session['demo_orders'],{'7':{'region':'GYEONGGI','method':'card'}})
            self.assertNotIn('must-not-be-stored',str(dict(session)))

    def test_price_change_rolls_back_without_demo_success(self):
        connection=FakeConnection()
        with patch.object(application,'get_db',return_value=connection):
            response=post_order(self.client,data=dict(self.values,expected_price_1='1'))
        self.assertTrue(response.location.endswith('/'))
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)
        with self.client.session_transaction() as session:
            self.assertNotIn('demo_orders',session)

    def test_cookie_metadata_is_bounded_and_no_amount_or_personal_data(self):
        history={}
        for number in range(20):
            history=remember_demo_order(history,number,{'region':'GYEONGGI','method':'wallet'})
        self.assertEqual(len(history),8)
        self.assertIn('19',history)
        self.assertNotIn('0',history)
        self.assertEqual(set(history['19']),{'region','method'})

    def test_completion_shows_mock_label_and_authoritative_order_amount(self):
        with self.client.session_transaction() as session:
            session['demo_orders']={'7':{'region':'GYEONGGI','method':'wallet'}}
        with patch.object(application,'fetch_order',return_value=self.order):
            response=self.client.get('/orders/complete/7')
        html=response.get_data(as_text=True)
        for text in ['주문 선택 정보','실제 청구 및 문자 발송','경기도','간편결제','24,000원','DB의 결제 이력이나 영수증이 아닙니다']:
            self.assertIn(text,html)
        self.assertEqual(html.count('id="demo-receipt-title"'),1)

    def test_other_browser_does_not_invent_payment_receipt(self):
        with patch.object(application,'fetch_order',return_value=self.order):
            response=application.app.test_client().get('/orders/complete/7')
        self.assertNotIn('모의 결제 시연을 완료했어요',response.get_data(as_text=True))

    def test_same_browser_can_view_demo_on_lookup_and_operations_detail(self):
        with self.client.session_transaction() as session:
            session['demo_orders']={'7':{'region':'CHUNGCHEONG','method':'transfer'}}
        with patch.object(application,'fetch_order',return_value=self.order):
            with patch.object(application,'query',return_value=[]):
                for url in ['/lookup?order_number=7','/orders/7']:
                    with self.subTest(url=url):
                        response=self.client.get(url)
                        self.assertEqual(response.status_code,200)
                        html=response.get_data(as_text=True)
                        self.assertIn('경기도',html)  # DB wins over the cookie's region.
                        self.assertIn('계좌이체',html)
                        self.assertEqual(html.count('id="demo-receipt-title"'),1)

    def test_home_renders_checkout_without_extra_db_reads_or_card_collection(self):
        with patch.object(application,'fetch_products',return_value=PRODUCTS):
            with patch.object(application,'get_db',side_effect=AssertionError('No DB access')):
                html=self.client.get('/').get_data(as_text=True)
        for text in ['🍓','🫐','🥦','id="delivery-region"','서울','경기도','충청도','실제 청구 및 문자 발송은 이루어지지 않습니다','form="order-form"']:
            self.assertIn(text,html)
        self.assertNotIn('name="card_number"',html)
        self.assertNotIn('name="recipient"',html)
        self.assertNotIn('name="address"',html)
        self.assertNotIn('프로젝트용',html)
        self.assertNotIn('모의 결제',html)


if __name__=='__main__':
    unittest.main()
