"""Issue a real signed form token; isolate all request records in temp files."""
import re
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
import app as application
from order_requests import OrderRequestLedger


def post_order(client, data, **kwargs):
    with patch.object(application,'fetch_products',return_value=[]):
        html=client.get('/').get_data(as_text=True)
    token=re.search(r'name="order_request_token" value="([^"]+)"',html).group(1)
    with TemporaryDirectory() as folder:
        with patch.object(application,'get_order_ledger',return_value=OrderRequestLedger(Path(folder)/'requests.sqlite3')):
            return client.post('/orders',data={**data,'order_request_token':token},**kwargs)
