"""Idempotency scenarios: temp SQLite + mocked MySQL only, never real orders."""
import re
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

from mysql.connector import Error
import app as application
from order_requests import OrderRequestLedger, fingerprint
from test_app import FakeConnection


class OrderRequestTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True,SECRET_KEY='stable-test-key-only')
        self.folder=TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'requests.sqlite3'
        self.ledger=OrderRequestLedger(self.path)
        patcher=patch.object(application,'get_order_ledger',return_value=self.ledger)
        patcher.start();self.addCleanup(patcher.stop)
        self.client=application.app.test_client()
        self.values=self.form(self.client)

    def form(self, client):
        with patch.object(application,'fetch_products',return_value=[]):
            html=client.get('/').get_data(as_text=True)
        token=re.search(r'name="order_request_token" value="([^"]+)"',html).group(1)
        with client.session_transaction() as session: csrf=session['demo_csrf']
        return dict(order_request_token=token,checkout_mode='demo_v1',demo_csrf=csrf,
                    delivery_region='GYEONGGI',payment_method='card',demo_ack='1',
                    quantity_1='2',expected_price_1='12000')

    def post(self, values=None, client=None):
        return (client or self.client).post('/orders',data=values or self.values)

    def request_id(self):
        with self.client.session_transaction() as session:return session['order_request_id']

    def test_twenty_identical_posts_create_one_order_and_redirect_to_same_number(self):
        connection=FakeConnection()
        with patch.object(application,'get_db',return_value=connection) as get_db:
            responses=[self.post() for _ in range(20)]
        self.assertEqual(get_db.call_count,1)
        self.assertEqual({r.status_code for r in responses},{303})
        self.assertEqual({r.location for r in responses},{'/orders/complete/7'})
        inserts=[sql for sql,_ in connection.cursor_instance.queries if sql.startswith('INSERT')]
        self.assertEqual(len(inserts),3)  # One order + one item + one job.

    def test_simultaneous_claims_from_independent_instances_have_one_winner(self):
        with ThreadPoolExecutor(max_workers=12) as pool:
            results=list(pool.map(lambda _:OrderRequestLedger(self.path).claim('same','digest'),range(24)))
        self.assertEqual(sum(state=='claimed' for state,_ in results),1)
        self.assertEqual(sum(state=='processing' for state,_ in results),23)

    def test_processing_request_never_opens_a_second_mysql_connection(self):
        request_id=self.request_id()
        digest=fingerprint({1:2},self.values,{'region':'GYEONGGI','method':'card'})
        self.ledger.claim(request_id,digest)
        with patch.object(application,'get_db',side_effect=AssertionError('No second DB')):
            self.assertEqual(self.post().status_code,302)

    def test_completed_request_survives_ledger_recreation_and_lost_response_cookie(self):
        with self.client.session_transaction() as session: original_session=dict(session)
        with patch.object(application,'get_db',return_value=FakeConnection()):self.post()
        retry=application.app.test_client()
        with retry.session_transaction() as session:session.update(original_session)
        with patch.object(application,'get_order_ledger',return_value=OrderRequestLedger(self.path)),patch.object(application,'get_db',side_effect=AssertionError('Already saved')):
            self.assertEqual(self.post(client=retry).location,'/orders/complete/7')

    def test_same_key_with_changed_quantity_region_method_or_price_is_blocked(self):
        with patch.object(application,'get_db',return_value=FakeConnection()):self.post()
        for changes in [{'quantity_1':'1'},{'delivery_region':'SEOUL'},{'payment_method':'wallet'},{'expected_price_1':'1'}]:
            with self.subTest(changes=changes),patch.object(application,'get_db',side_effect=AssertionError('Do not write')):
                self.assertEqual(self.post(dict(self.values,**changes)).location,'/')

    def test_price_validation_rollback_allows_corrected_retry(self):
        connection=FakeConnection()
        with patch.object(application,'get_db',return_value=connection):
            self.assertEqual(self.post(dict(self.values,expected_price_1='1')).location,'/')
        self.assertTrue(connection.rolled_back)
        with patch.object(application,'get_db',return_value=FakeConnection()):
            self.assertEqual(self.post().location,'/orders/complete/7')

    def test_commit_connection_error_blocks_retry_even_after_restart(self):
        connection=FakeConnection()
        connection.commit=lambda: (_ for _ in ()).throw(Error('Connection lost during commit'))
        with patch.object(application,'get_db',return_value=connection):self.post()
        with patch.object(application,'get_order_ledger',return_value=OrderRequestLedger(self.path)),patch.object(application,'get_db',side_effect=AssertionError('Unknown commit result')):
            self.assertEqual(self.post().location,'/')
        with self.ledger.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM order_requests').fetchone()[0],'uncertain')

    def test_crash_processing_record_is_never_expired_or_reclaimed(self):
        self.ledger.claim('crashed','digest')
        with self.ledger.connect() as db:db.execute("UPDATE order_requests SET created_at='2000-01-01',updated_at='2000-01-01'")
        self.assertEqual(OrderRequestLedger(self.path).claim('crashed','digest'),('processing',None))

    def test_mysql_commit_then_local_completion_failure_never_recreates_order(self):
        connection=FakeConnection()
        with patch.object(self.ledger,'complete',side_effect=OSError('Disk full')),patch.object(application,'get_db',return_value=connection):
            self.post()
        self.assertTrue(connection.committed)
        with patch.object(application,'get_db',side_effect=AssertionError('Must not duplicate')):
            self.assertEqual(self.post().location,'/')

    def test_missing_tampered_and_other_browser_tokens_are_rejected_before_db(self):
        invalid=[dict(self.values,order_request_token=''),dict(self.values,order_request_token='invalid')]
        for values in invalid:
            with patch.object(application,'get_db',side_effect=AssertionError('No DB')):
                self.assertEqual(self.post(values).location,'/')
        other=application.app.test_client(); other_values=self.form(other)
        with patch.object(application,'get_db',side_effect=AssertionError('No DB')):
            self.assertEqual(self.post(dict(other_values,order_request_token=self.values['order_request_token']),other).location,'/')

    def test_ledger_unavailable_fails_closed_before_mysql(self):
        with patch.object(self.ledger,'claim',side_effect=OSError('Cannot open file')),patch.object(application,'get_db',side_effect=AssertionError('No DB')):
            self.assertEqual(self.post().location,'/')

    def test_distinct_intent_after_success_is_allowed(self):
        with patch.object(application,'get_db',return_value=FakeConnection()):self.post()
        next_values=self.form(self.client)
        self.assertNotEqual(next_values['order_request_token'],self.values['order_request_token'])
        with patch.object(application,'get_db',return_value=FakeConnection()) as get_db:
            self.assertEqual(self.post(next_values).status_code,303)
        self.assertEqual(get_db.call_count,1)

    def test_local_record_contains_no_names_phones_requests_or_sms(self):
        private=dict(self.values,recipient_name='PRIVATE-NAME',recipient_phone='01012345678',delivery_request='PRIVATE-REQUEST',sms_consent='yes')
        with patch.object(application,'get_db',return_value=FakeConnection()):self.post(private)
        with self.ledger.connect() as db:
            rows=str(db.execute('SELECT * FROM order_requests').fetchall())
        for value in ['PRIVATE-NAME','01012345678','PRIVATE-REQUEST','sms_consent',self.values['order_request_token']]:
            self.assertNotIn(value,rows)

    def test_two_overlapping_posts_start_only_one_mysql_transaction(self):
        with self.client.session_transaction() as session:original=dict(session)
        retry=application.app.test_client()
        with retry.session_transaction() as session:session.update(original)
        entered=Event(); release=Event(); connection=FakeConnection()
        def pause_transaction():
            entered.set()
            if not release.wait(5): raise RuntimeError('Test synchronization timeout')
        connection.start_transaction=pause_transaction
        with patch.object(application,'get_db',return_value=connection) as get_db:
            with ThreadPoolExecutor(max_workers=1) as pool:
                first=pool.submit(self.post)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(self.post(client=retry).location,'/')
                    self.assertEqual(get_db.call_count,1)
                finally:release.set()
                self.assertEqual(first.result(timeout=5).status_code,303)


if __name__=='__main__':unittest.main()
