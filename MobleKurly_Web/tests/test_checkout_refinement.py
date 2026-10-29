"""Checkout privacy/markup tests. No live database writes or SMS messages."""
import unittest
from html.parser import HTMLParser
from unittest.mock import patch

import app as application
from test_app import PRODUCTS, FakeConnection
from order_support import post_order


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.nodes={}; self.slides=[]; self.feed(html)
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if attrs.get('id'): self.nodes[attrs['id']]=(tag,attrs)
        if 'data-ad-slide' in attrs: self.slides.append(attrs)


class CheckoutRefinementTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True,SECRET_KEY='refinement-test')
        self.client=application.app.test_client()

    def home(self):
        with patch.object(application,'fetch_products',return_value=PRODUCTS):
            with patch.object(application,'get_db',side_effect=AssertionError('No real database')):
                return self.client.get('/').get_data(as_text=True)

    def test_private_fields_are_outside_order_form_without_submission_names(self):
        html=self.home(); elements=Elements(html)
        for field in ['recipient-name','recipient-phone','delivery-request','sms-consent']:
            with self.subTest(field=field):
                _tag,attrs=elements.nodes[field]
                self.assertNotIn('name',attrs)
                self.assertNotIn('form',attrs)
                self.assertNotIn('id="'+field+'"',html.split('id="order-form"',1)[1].split('</form>',1)[0])
        self.assertEqual(elements.nodes['recipient-phone'][1]['type'],'tel')
        self.assertEqual(elements.nodes['delivery-request'][1]['maxlength'],'200')

    def test_sms_is_optional_default_off_and_plain_notice_is_present(self):
        html=self.home(); attrs=Elements(html).nodes['sms-consent'][1]
        self.assertNotIn('checked',attrs);self.assertNotIn('required',attrs)
        self.assertIn('실제 청구 및 문자 발송은 이루어지지 않습니다',html)
        self.assertIn('서버에 전송하거나 저장하지 않습니다',html)
        self.assertNotIn('프로젝트용',html)
        self.assertNotIn('모의 결제',html)

    def test_logistics_only_remains_in_product_detail_not_checkout(self):
        html=self.home()
        self.assertNotIn('id="confirm-logistics"',html)
        self.assertIn('id="detail-logistics"',html)
        checkout=html.split('id="confirm-dialog"',1)[1].split('</dialog>',1)[0]
        self.assertNotIn('입고 기록',checkout)
        self.assertIn('받는 분 이름',checkout)

    def test_editorial_is_in_top_advertising_with_accessible_inactive_slide(self):
        html=self.home(); elements=Elements(html)
        self.assertEqual(len(elements.slides),2)
        self.assertNotIn('hidden',elements.slides[0])
        self.assertIn('hidden',elements.slides[1]);self.assertIn('inert',elements.slides[1])
        self.assertNotIn('class="shopping-editorial',html)
        self.assertIn('하나씩 골라 담아,',html.split('id="advertising-carousel"',1)[1].split('</section>',1)[0])
        self.assertIn('data-ad-prev',html);self.assertIn('data-ad-next',html);self.assertIn('data-ad-toggle',html)
        image=self.client.get('/static/images/hero-table.png');self.addCleanup(image.close)
        self.assertEqual(image.status_code,200);self.assertTrue(image.data.startswith(b'\x89PNG'))

    def test_unexpected_personal_post_fields_are_not_saved_in_cookie_or_sql(self):
        with self.client.session_transaction() as session:session['demo_csrf']='csrf'
        values=dict(checkout_mode='demo_v1',delivery_region='GYEONGGI',payment_method='wallet',demo_ack='1',demo_csrf='csrf',
                    quantity_1='1',expected_price_1='12000',recipient_name='PRIVATE-RECIPIENT',
                    recipient_phone='01000000000',delivery_request='PRIVATE-REQUEST',sms_consent='yes')
        connection=FakeConnection()
        with patch.object(application,'get_db',return_value=connection):
            response=post_order(self.client,data=values)
        self.assertTrue(response.location.endswith('/orders/complete/7'))
        with self.client.session_transaction() as session:
            self.assertEqual(session['demo_orders']['7'],{'region':'GYEONGGI','method':'wallet'})
            stored=str(dict(session))
        sql=str(connection.cursor_instance.queries)
        for text in ['PRIVATE-RECIPIENT','01000000000','PRIVATE-REQUEST','sms_consent']:
            self.assertNotIn(text,stored);self.assertNotIn(text,sql)


if __name__=='__main__':unittest.main()
