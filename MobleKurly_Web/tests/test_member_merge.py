"""Member/points merge regressions with isolated ledger and mocked MySQL only."""
from decimal import Decimal
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import app as application
from order_requests import OrderRequestLedger, fingerprint
from test_app import FakeConnection, FakeCursor


class MemberCursor(FakeCursor):
    def execute(self, sql, params=None):
        super().execute(sql, params)
        compact = ' '.join(sql.split())
        if 'FROM users' in compact:
            self.results = [dict(name='테스트', phone='010-0000-0000',
                                 postal_code='', address='시험주소', address_detail='')]


class MemberMergeTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY='member-offline-only')
        self.client = application.app.test_client()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = OrderRequestLedger(Path(self.temp.name) / 'requests.sqlite3')
        for name, value in [('get_order_ledger', self.ledger)]:
            patcher = patch.object(application, name, return_value=value)
            patcher.start(); self.addCleanup(patcher.stop)
        guard = patch.object(application, 'get_db', side_effect=AssertionError('Real DB forbidden'))
        guard.start(); self.addCleanup(guard.stop)

    def signed_form(self, member=True):
        with self.client.session_transaction() as state:
            if member:
                state.update(member_id=10, member_name='테스트')
            state['demo_csrf'] = 'demo-test'
        with self.client.session_transaction() as state:
            state['order_owner'] = 'test-owner'
            state['order_request_id'] = 'request-1'
        from itsdangerous import URLSafeSerializer
        token = URLSafeSerializer(application.app.secret_key, salt='order-request-v1').dumps(
            dict(id='request-1', owner='test-owner'))
        return dict(order_request_token=token, checkout_mode='demo_v1', demo_csrf='demo-test',
                    delivery_region='GYEONGGI', payment_method='card', demo_ack='1',
                    quantity_1='2', expected_price_1='12000', points_to_use='500')

    def connection(self):
        conn = FakeConnection()
        conn.cursor_instance = MemberCursor()
        return conn

    def test_member_discount_points_shipping_and_jobs_commit_together(self):
        form = self.signed_form()
        conn = self.connection()
        with patch.object(application, 'get_db', return_value=conn), patch.object(application, 'point_balance', return_value=700):
            response = self.client.post('/orders', data=form)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(conn.committed)
        statements = conn.cursor_instance.queries
        order_insert = next(p for s, p in statements if s.startswith('INSERT INTO orders'))
        self.assertEqual(order_insert, ('GYEONGGI', 10))
        item = next(p for s, p in statements if s.startswith('INSERT INTO order_items'))
        self.assertEqual(item[-1], Decimal('11400'))
        self.assertTrue(any(s.startswith('UPDATE orders SET points_used') and p == (500, 7) for s, p in statements))
        self.assertTrue(any('recipient_name=' in s for s, _ in statements))
        self.assertTrue(any('FROM users' in s and 'FOR UPDATE' in s for s, _ in statements))
        self.assertTrue(any('INSERT INTO outbound_jobs' in s for s, _ in statements))

    def test_points_over_balance_and_payable_are_rejected_before_writes(self):
        for points, balance in [('701', 700), ('30000', 50000)]:
            with self.subTest(points=points):
                form = dict(self.signed_form(), points_to_use=points)
                conn = self.connection()
                with patch.object(application, 'get_db', return_value=conn), patch.object(application, 'point_balance', return_value=balance):
                    response = self.client.post('/orders', data=form)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(conn.rolled_back)
                self.assertFalse(any(s.startswith('INSERT') for s, _ in conn.cursor_instance.queries))

    def test_guest_cannot_spend_member_points(self):
        conn = self.connection()
        form = self.signed_form(member=False)
        with patch.object(application, 'get_db', return_value=conn):
            response = self.client.post('/orders', data=form)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(conn.committed)

    def test_changed_points_or_member_cannot_reuse_request(self):
        base = dict(expected_price_1='1000', points_to_use='10')
        original = fingerprint({1: 1}, base, None, member_id=10)
        self.assertNotEqual(original, fingerprint({1: 1}, dict(base, points_to_use='0'), None, member_id=10))
        self.assertNotEqual(original, fingerprint({1: 1}, base, None, member_id=11))
        self.assertEqual(fingerprint({1: 1}, {'expected_price_1': '1000'}, None),
                         fingerprint({1: 1}, {'expected_price_1': '1000', 'points_to_use': '0'}, None))

    def test_negative_or_invalid_point_amount_is_rejected(self):
        for points in ('-1', '1.1', 'NaN', '9' * 100, '2147483648'):
            with self.subTest(points=points), self.assertRaises(ValueError):
                fingerprint({1: 1}, dict(expected_price_1='1000', points_to_use=points), None, member_id=10)

    def test_point_balance_excludes_uncompleted_earnings_and_reserves_pending_spend(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [dict(earned_base=Decimal('10000')), dict(redeemed=500), dict(spent=60)]
        self.assertEqual(application.point_balance(cursor, 10), 35)
        self.assertIn("status='COMPLETED'", cursor.execute.call_args_list[0].args[0])
        self.assertNotIn('status=', cursor.execute.call_args_list[2].args[0])

    def test_csrf_required_on_member_writes(self):
        for path in ('/register', '/login', '/logout'):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, data={}).status_code, 400)

    def test_malformed_csrf_is_rejected_without_server_error(self):
        with self.client.session_transaction() as state:
            state['member_csrf'] = 'csrf-test'
        self.assertEqual(self.client.post('/login', data=dict(csrf_token='한글토큰')).status_code, 400)

    def test_registration_stores_hash_and_never_plain_password(self):
        with self.client.session_transaction() as state:
            state['member_csrf'] = 'csrf-test'
        conn = self.connection()
        with patch.object(application, 'get_db', return_value=conn):
            response = self.client.post('/register', data=dict(csrf_token='csrf-test',
                username='test01', password='Ab9!xy', password_confirm='Ab9!xy',
                name='테스트', email='test@example.invalid', phone='01000000000', terms='yes', privacy='yes'))
        self.assertTrue(response.location.endswith('/login'))
        insert = next(p for s, p in conn.cursor_instance.queries if s.startswith('INSERT INTO users'))
        self.assertNotIn('Ab9!xy', insert)
        self.assertTrue(application.check_password_hash(insert[1], 'Ab9!xy'))
        self.assertTrue(conn.committed)
        self.assertTrue(conn.cursor_instance.closed)

    def test_order_receipt_subtracts_recorded_points_not_current_product_price(self):
        conn = MagicMock()
        cur = conn.cursor.return_value
        cur.fetchone.return_value = dict(order_id=7, points_used=500)
        cur.fetchall.return_value = [dict(line_total=Decimal('22800'))]
        with patch.object(application, 'get_db', return_value=conn):
            order = application.fetch_order(7)
        self.assertEqual(order['subtotal'], Decimal('22800'))
        self.assertEqual(order['total'], Decimal('22300'))

    def test_mypage_requires_login(self):
        self.assertTrue(self.client.get('/mypage').location.endswith('/login'))

    def test_reorder_rejects_another_members_order(self):
        with self.client.session_transaction() as state:
            state.update(member_id=10, member_name='테스트', member_csrf='csrf-test')
        with patch.object(application, 'query', return_value=[]) as query:
            response = self.client.post('/mypage/reorder/99', data=dict(csrf_token='csrf-test'))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(query.call_args.args[1], (99, 10))

    def test_login_rotates_session_and_logout_clears_identity(self):
        from werkzeug.security import generate_password_hash
        with self.client.session_transaction() as state:
            state.update(member_csrf='csrf-test', order_owner='old-owner')
        user = dict(user_id=10, username='test01', name='테스트', password_hash=generate_password_hash('Ab9!xy'))
        with patch.object(application, 'query', return_value=[user]):
            response = self.client.post('/login', data=dict(csrf_token='csrf-test', username='test01', password='Ab9!xy'))
        self.assertTrue(response.location.endswith('/mypage'))
        with self.client.session_transaction() as state:
            self.assertEqual(state['member_id'], 10)
            self.assertNotIn('order_owner', state)
            state['member_csrf'] = 'new-csrf'
        self.client.post('/logout', data=dict(csrf_token='new-csrf'))
        with self.client.session_transaction() as state:
            self.assertNotIn('member_id', state)

    def test_member_home_preserves_all_cart_views_and_thumbnail_assets(self):
        from test_cart_photos import fixture_product
        conn = self.connection()
        with self.client.session_transaction() as state:
            state.update(member_id=10, member_name='테스트')
        with patch.object(application, 'query', return_value=[]), patch.object(application, 'point_balance', return_value=500), patch.object(application, 'get_db', return_value=conn), patch.object(application, 'fetch_products', return_value=[fixture_product()]):
            html = self.client.get('/').get_data(as_text=True)
        for element in ('floating-cart', 'cart-drawer', 'cart-edit-items', 'inline-cart-items', 'points-cancel'):
            self.assertEqual(len(re.findall(r'id="' + element + '"', html)), 1)
        self.assertIn('/static/images/products/strawberry.webp', html)
        self.assertIn('window.MOBLE_MEMBER_DISCOUNT = 5', html)


if __name__ == '__main__':
    unittest.main()
