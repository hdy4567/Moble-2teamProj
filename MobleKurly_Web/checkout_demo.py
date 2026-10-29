"""Non-financial checkout choices; no schema mutation or payment gateway.

Only region and method codes are retained in the browser's signed Flask cookie.
They are presentation metadata, never proof of payment or a delivery address.
The authoritative order region is orders.delivery_region, not cookie metadata.
"""

REGIONS = {'SEOUL': '서울', 'GYEONGGI': '경기도', 'CHUNGCHEONG': '충청도'}
METHODS = {'card': '신용·체크카드', 'wallet': '간편결제', 'transfer': '계좌이체'}
MODE = 'demo_v1'


def validate_demo_checkout(values):
    mode = values.get('checkout_mode', '')
    if not mode:
        return None  # Existing non-payment order clients remain compatible.
    if mode != MODE:
        raise ValueError('지원하지 않는 결제 방식입니다. 페이지를 새로고침해 주세요.')
    region = values.get('delivery_region', '')
    method = values.get('payment_method', '')
    if region not in REGIONS:
        raise ValueError('배송 권역을 선택해 주세요: 서울, 경기도, 충청도.')
    if method not in METHODS:
        raise ValueError('결제 수단을 다시 선택해 주세요.')
    if values.get('demo_ack') != '1':
        raise ValueError('주문 상품과 입력 정보를 확인해 주세요.')
    return {'region': region, 'method': method}


def remember_demo_order(previous, order_id, choices):
    """Bound cookie size; store neither addresses, card data nor amounts."""
    orders = dict(previous) if isinstance(previous, dict) else {}
    orders[str(order_id)] = dict(choices)
    return dict(list(orders.items())[-8:])
