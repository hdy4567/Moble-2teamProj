"""Local durable request ledger. Never stores customer fields or changes MySQL.

Processing entries are NEVER automatically stolen/expired: after a crash the
MySQL commit outcome may be unknown. Block retry rather than risk a duplicate.
Keep this file on the single web host, including across deployments/restarts.
"""
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def fingerprint(quantities, values, choices, member_id=None):
    from decimal import Decimal, InvalidOperation
    items=[]
    for product_id, quantity in sorted(quantities.items()):
        try:
            price=Decimal(values.get(f'expected_price_{product_id}', ''))
            if not price.is_finite(): raise ValueError
            price=format(price.normalize(),'f')
        except (InvalidOperation, ValueError):
            raise ValueError('상품 가격을 다시 확인해 주세요.')
        items.append((product_id,quantity,price))
    payload={'items':items,'choices':choices}
    # Preserve old guest fingerprints; bind new member pricing/points to the
    # request so a changed redemption cannot reuse a completed order token.
    if member_id is not None or values.get('points_to_use', '0') not in ('', '0'):
        try:
            points_text = values.get('points_to_use', '0') or '0'
            if not re.fullmatch(r'[0-9]{1,10}', points_text):
                raise ValueError
            points = int(points_text)
            if points > 2147483647:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError('적립금 사용액을 확인해 주세요.')
        payload['member_id'] = member_id
        payload['points_used'] = points
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class OrderRequestLedger:
    def __init__(self, path):
        self.path=Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        connection=sqlite3.connect(self.path,timeout=5,isolation_level=None)
        try:
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('''CREATE TABLE IF NOT EXISTS order_requests (
                request_hash TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                state TEXT NOT NULL, order_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            yield connection
        finally: connection.close()

    def claim(self, request_id, digest):
        key=hashlib.sha256(request_id.encode()).hexdigest()
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row=connection.execute('SELECT fingerprint,state,order_id FROM order_requests WHERE request_hash=?',(key,)).fetchone()
            if row:
                result=('conflict',None) if row[0]!=digest else (row[1],row[2])
            else:
                connection.execute("INSERT INTO order_requests (request_hash,fingerprint,state) VALUES (?,?,'processing')",(key,digest))
                result=('claimed',None)
            connection.commit()
            return result

    def complete(self, request_id, order_id):
        self._update(request_id,"UPDATE order_requests SET state='complete',order_id=?,updated_at=CURRENT_TIMESTAMP WHERE request_hash=? AND state='processing'",(order_id,))

    def uncertain(self, request_id):
        self._update(request_id,"UPDATE order_requests SET state='uncertain',updated_at=CURRENT_TIMESTAMP WHERE request_hash=? AND state='processing'")

    def release(self, request_id):
        # Only use after a known rollback, or before any MySQL write was attempted.
        self._update(request_id,"DELETE FROM order_requests WHERE request_hash=? AND state='processing'")

    def _update(self, request_id, sql, params=()):
        key=hashlib.sha256(request_id.encode()).hexdigest()
        with self.connect() as connection:
            cursor=connection.execute(sql,(*params,key))
            if cursor.rowcount!=1: raise RuntimeError('Order request state changed')
