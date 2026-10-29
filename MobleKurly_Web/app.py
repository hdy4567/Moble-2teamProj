import os
import re
import secrets
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from db import DATABASE_NAME, DB_CONFIG, get_db
from inventory import LOGISTICS_SQL, build_logistics_payload
from checkout_demo import REGIONS, METHODS, validate_demo_checkout, remember_demo_order
from itsdangerous import URLSafeSerializer, BadSignature
from order_requests import OrderRequestLedger, fingerprint
from product_guides import load_guides, guide_for


MEMBER_DISCOUNT = Decimal("0.05")
REWARD_RATE = Decimal("0.01")

app = Flask(__name__)
configured_secret = os.getenv("SECRET_KEY", "")
app.config["SECRET_KEY"] = configured_secret if len(configured_secret) >= 32 else secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"


def point_balance(cursor, member_id):
    """Earned on completed orders minus points already used on any order.
    The caller locks the users row for writes to serialize spending.
    """
    cursor.execute("""SELECT COALESCE(SUM(oi.unit_price * oi.quantity), 0) AS earned_base
        FROM orders o JOIN order_items oi ON oi.order_id=o.order_id
        WHERE o.user_id=%s AND o.status='COMPLETED'""", (member_id,))
    earned_base = Decimal(str(cursor.fetchone()['earned_base']))
    cursor.execute("SELECT COALESCE(SUM(points_used), 0) AS redeemed FROM orders WHERE user_id=%s AND status='COMPLETED'", (member_id,))
    redeemed = Decimal(str(cursor.fetchone()['redeemed']))
    earned = int((max(Decimal('0'), earned_base - redeemed) * REWARD_RATE).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    cursor.execute('SELECT COALESCE(SUM(points_used), 0) AS spent FROM orders WHERE user_id=%s', (member_id,))
    spent = int(cursor.fetchone()['spent'])
    return max(0, earned - spent)


def valid_password(password):
    if not re.fullmatch(r"[A-Za-z0-9!@#$%^&*]{6,8}", password or ""):
        return False
    if not (re.search(r"[A-Za-z]", password) and re.search(r"[0-9]", password) and re.search(r"[!@#$%^&*]", password)):
        return False
    for i in range(len(password)-2):
        triple=password[i:i+3]
        if triple.isdigit() and (int(triple[1])-int(triple[0]) == int(triple[2])-int(triple[1])) and abs(int(triple[1])-int(triple[0]))==1:
            return False
    return True


def member_required(func):
    @wraps(func)
    def inner(*args, **kwargs):
        if not session.get('member_id'):
            flash('로그인이 필요합니다.', 'error')
            return redirect(url_for('member_login'))
        return func(*args, **kwargs)
    return inner


def member_csrf():
    if 'member_csrf' not in session:
        session['member_csrf'] = secrets.token_urlsafe(32)
    return session['member_csrf']


def check_member_csrf():
    stored = session.get('member_csrf', '')
    supplied = request.form.get('csrf_token', '')
    return bool(stored and supplied and len(supplied) <= 256 and
                secrets.compare_digest(stored.encode('utf-8'), supplied.encode('utf-8')))


@app.context_processor
def inject_member():
    return {'member_csrf': member_csrf, 'logged_in_member': session.get('member_name'), 'member_discount_percent': 5}


@app.route('/register', methods=['GET','POST'])
def member_register():
    if request.method == 'POST':
        if not check_member_csrf(): abort(400)
        username=request.form.get('username','').strip()
        password=request.form.get('password','')
        name=request.form.get('name','').strip()
        email=request.form.get('email','').strip().lower()
        phone=request.form.get('phone','').strip()
        if not re.fullmatch(r'[A-Za-z0-9]{6,20}',username):
            flash('아이디는 영문과 숫자 6~20자리로 입력해 주세요.', 'error')
        elif not valid_password(password):
            flash('비밀번호는 6~8자리 영문·숫자·특수기호를 포함하고 3자리 연속 숫자를 사용할 수 없습니다.', 'error')
        elif password != request.form.get('password_confirm'):
            flash('비밀번호 확인이 일치하지 않습니다.', 'error')
        elif not name or len(name)>60 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or len(email)>254 or not re.fullmatch(r'01[016789]-?\d{3,4}-?\d{4}',phone):
            flash('이름, 이메일, 휴대전화 정보를 확인해 주세요.', 'error')
        elif request.form.get('terms')!='yes' or request.form.get('privacy')!='yes':
            flash('필수 약관에 동의해 주세요.', 'error')
        else:
            conn=None
            cur=None
            try:
                conn=get_db(); cur=conn.cursor()
                cur.execute("""INSERT INTO users (username,password_hash,name,email,phone,postal_code,address,address_detail,marketing_consent)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (username,generate_password_hash(password),name,email,phone,request.form.get('postal_code','')[:12],request.form.get('address','')[:255],request.form.get('address_detail','')[:255],int(request.form.get('marketing')=='yes')))
                conn.commit(); flash('회원가입이 완료되었습니다. 로그인해 주세요.','success')
                return redirect(url_for('member_login'))
            except Error as exc:
                if conn: conn.rollback()
                flash('이미 사용 중인 아이디 또는 이메일이거나 회원 DB가 준비되지 않았습니다.' if getattr(exc,'errno',None)==1062 else '회원정보를 저장하지 못했습니다. DB 설치 여부를 확인해 주세요.','error')
            finally:
                if cur: cur.close()
                if conn: conn.close()
    return render_template('member_form.html', mode='register')


@app.post('/mypage/reorder/<int:order_id>')
@member_required
def member_reorder(order_id):
    if not check_member_csrf():
        abort(400)
    try:
        own = query('SELECT order_id FROM orders WHERE order_id=%s AND user_id=%s', (order_id, session['member_id']))
        if not own:
            abort(404)
        items = query("""SELECT oi.product_id, oi.quantity, p.stock FROM order_items oi
            JOIN products p ON p.product_id=oi.product_id WHERE oi.order_id=%s""", (order_id,))
        if not items:
            flash('재주문할 상품이 없습니다.', 'error')
            return redirect(url_for('member_mypage'))
        # 서버가 확인한 상품/수량만 JSON으로 전달. 구매는 고객이 장바구니에서 다시 확인합니다.
        quantities = {str(item['product_id']): min(item['quantity'], item['stock']) for item in items if item['stock'] > 0}
        if not quantities:
            flash('현재 재주문할 수 있는 재고가 없습니다.', 'error')
            return redirect(url_for('member_mypage'))
        session['reorder_cart'] = quantities
        flash('이전 주문 상품을 장바구니로 불러왔습니다. 수량과 현재 가격을 확인해 주세요.', 'success')
        return redirect(url_for('index', reorder='1') + '#products')
    except Error:
        flash('재주문 상품을 불러오지 못했습니다.', 'error')
        return redirect(url_for('member_mypage'))


@app.get('/api/reorder-cart')
@member_required
def reorder_cart():
    return jsonify(cart=session.pop('reorder_cart', {}))


@app.route('/login', methods=['GET','POST'])
def member_login():
    if request.method=='POST':
        if not check_member_csrf(): abort(400)
        try:
            rows=query('SELECT user_id, username, name, password_hash FROM users WHERE username=%s', (request.form.get('username',''),))
            if rows and check_password_hash(rows[0]['password_hash'],request.form.get('password','')):
                session.clear(); session['member_id']=rows[0]['user_id']; session['member_name']=rows[0]['name']
                flash('로그인되었습니다.','success'); return redirect(url_for('member_mypage'))
            flash('아이디 또는 비밀번호가 올바르지 않습니다.','error')
        except Error:
            flash('회원 DB에 연결할 수 없습니다.','error')
    return render_template('member_form.html',mode='login')


@app.post('/logout')
def member_logout():
    if not check_member_csrf(): abort(400)
    session.clear(); flash('로그아웃되었습니다.','success')
    return redirect(url_for('index'))


@app.route('/mypage',methods=['GET','POST'])
@member_required
def member_mypage():
    if request.method=='POST':
        if not check_member_csrf(): abort(400)
        phone = request.form.get('phone', '').strip()
        if not re.fullmatch(r'01[016789]-?\d{3,4}-?\d{4}', phone):
            flash('휴대전화 정보를 확인해 주세요.', 'error')
            return redirect(url_for('member_mypage'))
        conn = None
        cur = None
        try:
            conn=get_db(); cur=conn.cursor()
            cur.execute('UPDATE users SET phone=%s,postal_code=%s,address=%s,address_detail=%s WHERE user_id=%s', (phone,request.form.get('postal_code','')[:12],request.form.get('address','')[:255],request.form.get('address_detail','')[:255],session['member_id']))
            conn.commit(); flash('회원정보가 수정되었습니다.','success')
        except Error:
            if conn: conn.rollback()
            flash('회원정보 수정에 실패했습니다.','error')
        finally:
            if cur: cur.close()
            if conn: conn.close()
        return redirect(url_for('member_mypage'))
    try:
        users=query('SELECT username,name,email,phone,postal_code,address,address_detail FROM users WHERE user_id=%s',(session['member_id'],))
        orders=query('SELECT order_id,status,ordered_at AS created_at,points_used FROM orders WHERE user_id=%s ORDER BY order_id DESC LIMIT 100',(session['member_id'],))
        order_ids = [order['order_id'] for order in orders]
        if order_ids:
            placeholders = ','.join(['%s'] * len(order_ids))
            order_items = query(
                'SELECT oi.order_id, oi.product_id, oi.quantity, oi.unit_price, '
                'p.name AS product_name FROM order_items oi '
                'JOIN products p ON p.product_id=oi.product_id '
                f'WHERE oi.order_id IN ({placeholders}) ORDER BY oi.item_id',
                tuple(order_ids)
            )
            items_by_order = {order_id: [] for order_id in order_ids}
            for item in order_items:
                item['line_total'] = item['unit_price'] * item['quantity']
                items_by_order[item['order_id']].append(item)
            for order in orders:
                order['items'] = items_by_order[order['order_id']]
                order['subtotal'] = sum((item['line_total'] for item in order['items']), Decimal('0'))
                order['total_price'] = order['subtotal'] - Decimal(str(order.get('points_used') or 0))
        else:
            for order in orders:
                order['items'] = []
                order['total_price'] = Decimal('0')
        conn = get_db()
        try:
            cur = conn.cursor(dictionary=True)
            reward_points = point_balance(cur, session['member_id'])
        finally:
            conn.close()
    except Error:
        flash('회원 DB를 확인해 주세요.','error'); return redirect(url_for('index'))
    if not users: session.clear(); return redirect(url_for('member_login'))
    return render_template('mypage.html',member=users[0],member_orders=orders, reward_points=reward_points)


def get_order_ledger():
    return OrderRequestLedger(Path(__file__).with_name('runtime') / 'order_requests.sqlite3')


def issue_order_token():
    if 'order_owner' not in session:
        session['order_owner']=secrets.token_urlsafe(24)
    if 'order_request_id' not in session:
        session['order_request_id']=secrets.token_urlsafe(32)
    return URLSafeSerializer(app.secret_key,salt='order-request-v1').dumps(
        {'id':session['order_request_id'],'owner':session['order_owner']})


def validate_order_token(token):
    try:
        if not token or len(token)>512: raise ValueError
        data=URLSafeSerializer(app.secret_key,salt='order-request-v1').loads(token)
        owner=session.get('order_owner','')
        if not isinstance(data,dict) or not isinstance(data.get('id'),str) or not isinstance(data.get('owner'),str): raise ValueError
        if not owner or not secrets.compare_digest(data['owner'],owner): raise ValueError
        return data['id']
    except (BadSignature, ValueError, TypeError):
        raise ValueError('주문 요청을 확인하지 못했습니다. 페이지를 새로고침한 뒤 다시 확인해 주세요.')


def finish_order_request(order_id, request_id, choices):
    if session.get('order_request_id')==request_id:
        session.pop('order_request_id',None)
    if choices:
        session['demo_orders']=remember_demo_order(session.get('demo_orders'),order_id,choices)
    return redirect(url_for('order_complete',order_id=order_id),code=303)

STATUS_KO = {
    "PENDING": "주문 접수", "PROCESSING": "출고 중", "ERROR": "확인 필요",
    "COMPLETED": "출고 완료", "WAITING": "출고 대기", "RUNNING": "진행 중",
    "RETRY_WAIT": "재시도 대기", "DONE": "작업 완료", "SUCCESS": "정상",
    "UNKNOWN": "미확인", "NORMAL": "정상 출고", "ERROR_BIN": "오류 수거함",
}


def query(sql, params=()):
    """Execute a read-only view query and always return its connection."""
    connection = get_db()
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        try:
            if cursor is not None:
                cursor.close()
        finally:
            connection.close()


@app.template_filter("status_ko")
def status_ko(value):
    return STATUS_KO.get(value, value or "-")


@app.template_filter("datetime_ko")
def datetime_ko(value):
    if not value:
        return "-"
    return value.strftime("%Y.%m.%d %H:%M") if hasattr(value, "strftime") else str(value)


@app.template_filter("delivery_region_ko")
def delivery_region_ko(value):
    return REGIONS.get(value, "확인 필요" if value else "미등록")


def display_order_number(order_id):
    return f"MK-{int(order_id):06d}"


def parse_order_number(value):
    """MK-000123, 000123, 123을 모두 주문 ID 123으로 변환한다."""
    normalized = re.sub(r"[\s-]", "", (value or "").upper())
    if normalized.startswith("MK"):
        normalized = normalized[2:]
    if not re.fullmatch(r"[0-9]{1,10}", normalized):
        return None
    order_id = int(normalized)
    return order_id if 1 <= order_id <= 2147483647 else None


@app.template_filter("won")
def won(value):
    number = format(Decimal(value or 0), ",f")
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    return f"{number}원"


@app.context_processor
def inject_helpers():
    guides=load_guides() if request.endpoint in {'index','products_api'} else {}
    if 'demo_csrf' not in session:
        session['demo_csrf'] = secrets.token_urlsafe(24)
    return {"display_order_number": display_order_number,
            "demo_regions": REGIONS, "demo_methods": METHODS,
            "demo_csrf": session['demo_csrf'], "demo_for_order": demo_for_order,
            "order_request_token": issue_order_token() if request.endpoint=='index' else None,
            "product_guide": lambda product: guide_for(product,guides)}


def demo_for_order(order_id):
    orders = session.get('demo_orders', {})
    data = orders.get(str(order_id)) if isinstance(orders, dict) else None
    return data if isinstance(data, dict) and data.get('region') in REGIONS and data.get('method') in METHODS else None


def fetch_products():
    """Read the current catalog from MySQL, without seeded or cached values."""
    return query(
        """
        SELECT product_id, name, color, price, stock
        FROM products
        ORDER BY product_id
        """
    )


@app.after_request
def prevent_stale_catalog(response):
    if request.endpoint in {"index", "products_api", "logistics_api", "order_complete", "lookup", "order_detail",
                            "member_register", "member_login", "member_mypage", "reorder_cart"}:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    try:
        delivery_profile = None
        if session.get('member_id'):
            found = query('SELECT name,phone,postal_code,address,address_detail FROM users WHERE user_id=%s', (session['member_id'],))
            delivery_profile = found[0] if found else None
        available_points = 0
        if session.get('member_id'):
            conn = get_db()
            try:
                available_points = point_balance(conn.cursor(dictionary=True), session['member_id'])
            finally:
                conn.close()
        return render_template("index.html", products=fetch_products(), delivery_profile=delivery_profile, available_points=available_points)
    except Error:
        app.logger.exception("상품 목록 조회 실패")
        return render_template("db_error.html", error=None), 503


@app.get("/api/products")
def products_api():
    try:
        products = fetch_products()
        return jsonify(
            database=DATABASE_NAME,
            products=[{
                "product_id": product["product_id"],
                "name": product["name"],
                "color": product["color"],
                "price": str(product["price"]),
                "stock": product["stock"],
            } for product in products],
            html=render_template("partials/product_cards.html", products=products),
        )
    except Error:
        app.logger.exception("최신 상품 정보 조회 실패")
        return jsonify(error="상품 정보를 확인하지 못했어요. 잠시 후 다시 시도해 주세요."), 503


def fetch_logistics():
    """Read stock and receipt/order history without inventing missing dates."""
    return build_logistics_payload(query(LOGISTICS_SQL))


@app.get("/api/logistics")
def logistics_api():
    try:
        return jsonify(fetch_logistics())
    except Error:
        app.logger.exception("상품 물류 정보 조회 실패")
        return jsonify(error="물류 정보를 불러오지 못했어요. 잠시 후 다시 확인해 주세요."), 503


@app.post("/orders")
def create_order():
    try:
        demo_choices = validate_demo_checkout(request.form)
        if demo_choices:
            expected = session.get('demo_csrf', '')
            provided = request.form.get('demo_csrf', '')
            if not expected or not provided or not secrets.compare_digest(provided, expected):
                raise ValueError('페이지를 새로고침한 뒤 주문서를 다시 확인해 주세요.')
        request_id=validate_order_token(request.form.get('order_request_token',''))
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('index'))
    quantities = {}
    for key, value in request.form.items():
        match = re.fullmatch(r"quantity_(\d+)", key)
        if not match:
            continue
        try:
            quantity = int(value)
        except (TypeError, ValueError):
            quantity = 0
        if quantity > 0:
            quantities[int(match.group(1))] = quantity

    if not quantities:
        flash("상품을 한 개 이상 선택해 주세요.", "error")
        return redirect(url_for("index"))
    try:
        digest=fingerprint(quantities,request.form,demo_choices, member_id=session.get('member_id'))
        ledger=get_order_ledger()
        state, previous_order=ledger.claim(request_id,digest)
    except ValueError as exc:
        flash(str(exc),'error')
        return redirect(url_for('index'))
    except Exception:
        app.logger.exception('주문 중복 확인 기록 접근 실패')
        flash('중복 주문 여부를 확인하지 못해 접수를 중단했습니다. 잠시 후 다시 확인해 주세요.','error')
        return redirect(url_for('index'))
    if state=='complete':
        flash('이미 접수된 요청입니다. 기존 주문 내역으로 안내합니다.','info')
        return finish_order_request(previous_order,request_id,demo_choices)
    if state!='claimed':
        flash('같은 요청의 상품 또는 배송 정보가 달라졌습니다. 기존 주문을 먼저 조회한 뒤 새 주문을 시작해 주세요.' if state=='conflict' else
              '이 요청은 처리 중이거나 접수 결과 확인이 필요합니다. 중복 접수를 막았습니다. 주문현황을 먼저 확인해 주세요.','error')
        return redirect(url_for('index'))
    connection = None
    commit_started=False
    writes_started=False
    def settle_failure():
        rolled_back=False
        if connection:
            try:
                connection.rollback()
                rolled_back=True
            except Exception:
                app.logger.exception('주문 롤백 결과 확인 실패')
        try:
            if not commit_started and (rolled_back or not writes_started):
                ledger.release(request_id)
            else:
                ledger.uncertain(request_id)
        except Exception:
            # A durable processing record still blocks retries if settlement fails.
            app.logger.exception('주문 요청 기록 정리 실패; 자동 재접수 차단')
    try:
        connection = get_db()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        placeholders = ",".join(["%s"] * len(quantities))
        cursor.execute(
            f"""
            SELECT product_id, name, price, stock
            FROM products
            WHERE product_id IN ({placeholders})
            FOR UPDATE
            """,
            tuple(quantities),
        )
        products = {row["product_id"]: row for row in cursor.fetchall()}

        if len(products) != len(quantities):
            raise ValueError("존재하지 않는 상품이 포함되어 있습니다.")
        for product_id, product in products.items():
            try:
                expected_price = Decimal(request.form.get(f"expected_price_{product_id}", ""))
            except (InvalidOperation, ValueError):
                raise ValueError("상품 가격을 다시 확인해 주세요. 페이지를 새로고침한 뒤 주문해 주세요.")
            if not expected_price.is_finite() or expected_price != product["price"]:
                raise ValueError("상품 가격이 변경되었습니다. 최신 가격을 확인한 뒤 다시 주문해 주세요.")
        insufficient = [
            product["name"]
            for product_id, product in products.items()
            if quantities[product_id] > product["stock"]
        ]
        if insufficient:
            raise ValueError(f"재고가 부족한 상품: {', '.join(insufficient)}")

        # 회원의 저장 배송지를 서버에서 직접 조회하여 주문에 기록합니다.
        shipping = None
        if session.get('member_id'):
            # Lock before the first non-locking read: a waiting transaction must
            # not calculate points from an older REPEATABLE READ snapshot.
            cursor.execute('SELECT name,phone,postal_code,address,address_detail FROM users WHERE user_id=%s FOR UPDATE', (session['member_id'],))
            shipping = cursor.fetchone()
            if not shipping:
                raise ValueError('회원정보를 찾을 수 없습니다. 다시 로그인해 주세요.')
        points_used = 0
        if session.get('member_id'):
            # Lock the member row to prevent concurrent orders from spending the same points.
            balance = point_balance(cursor, session['member_id'])
            try:
                points_used = int(request.form.get('points_to_use', '0'))
            except (ValueError, TypeError):
                raise ValueError('적립금 사용액을 확인해 주세요.')
            if points_used < 0 or points_used > balance:
                raise ValueError('사용 가능한 적립금을 초과했습니다. 새로고침 후 다시 시도해 주세요.')
            discounted_total = sum(
                (products[pid]['price'] * (Decimal('1') - MEMBER_DISCOUNT)).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * qty
                for pid, qty in quantities.items()
            )
            if points_used > int(discounted_total):
                raise ValueError('적립금은 주문금액을 초과할 수 없습니다.')
        elif request.form.get('points_to_use', '0') not in ('', '0'):
            raise ValueError('적립금은 회원만 사용할 수 있습니다.')
        writes_started=True
        if demo_choices and session.get('member_id'):
            cursor.execute(
                "INSERT INTO orders (status, delivery_region, user_id) VALUES ('PENDING', %s, %s)",
                (demo_choices['region'], session.get('member_id')),
            )
        elif session.get('member_id'):
            # Legacy non-checkout clients have no region; never invent one.
            cursor.execute("INSERT INTO orders (status, user_id) VALUES ('PENDING', %s)", (session.get('member_id'),))
        elif demo_choices:
            cursor.execute("INSERT INTO orders (status, delivery_region) VALUES ('PENDING', %s)", (demo_choices['region'],))
        else:
            cursor.execute("INSERT INTO orders (status) VALUES ('PENDING')")
        order_id = cursor.lastrowid
        if points_used:
            cursor.execute('UPDATE orders SET points_used=%s WHERE order_id=%s', (points_used, order_id))
        if shipping:
            cursor.execute('''UPDATE orders SET recipient_name=%s, recipient_phone=%s,
                shipping_postal_code=%s, shipping_address=%s, shipping_address_detail=%s
                WHERE order_id=%s''', (shipping['name'], shipping['phone'], shipping['postal_code'],
                shipping['address'], shipping['address_detail'], order_id))

        for product_id, quantity in quantities.items():
            cursor.execute(
                """
                INSERT INTO order_items (order_id, product_id, quantity, unit_price)
                VALUES (%s, %s, %s, %s)
                """,
                (order_id, product_id, quantity,
                 (products[product_id]["price"] * (Decimal('1') - MEMBER_DISCOUNT)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
                 if session.get('member_id') else products[product_id]["price"]),
            )
            item_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO outbound_jobs (item_id, status) VALUES (%s, 'WAITING')",
                (item_id,),
            )

        commit_started=True
        connection.commit()
        ledger.complete(request_id,order_id)
        return finish_order_request(order_id,request_id,demo_choices)
    except ValueError as exc:
        settle_failure()
        flash(str(exc), "error")
        return redirect(url_for("index"))
    except Exception:
        settle_failure()
        app.logger.exception("주문 저장 실패")
        flash('접수 결과를 확정하지 못했습니다. 중복 주문을 막기 위해 다시 접수하지 말고 주문현황을 확인해 주세요.' if commit_started else
              "주문을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.", "error")
        return redirect(url_for("index"))
    finally:
        if connection and connection.is_connected():
            connection.close()


def fetch_order(order_id):
    connection = get_db()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT order_id, status, ordered_at, approved_at, completed_at, delivery_region, points_used
            FROM orders
            WHERE order_id = %s
            """,
            (order_id,),
        )
        order = cursor.fetchone()
        if not order:
            return None

        cursor.execute(
            """
            SELECT oi.item_id, oi.product_id, p.name, p.color, oi.quantity, oi.shipped_qty, oi.unit_price,
                   (oi.quantity * oi.unit_price) AS line_total
            FROM order_items oi
            JOIN products p ON p.product_id = oi.product_id
            WHERE oi.order_id = %s
            ORDER BY oi.item_id
            """,
            (order_id,),
        )
        order["items"] = cursor.fetchall()
        order["subtotal"] = sum((item["line_total"] for item in order["items"]), Decimal("0"))
        order["total"] = order['subtotal'] - Decimal(str(order.get('points_used') or 0))
        return order
    finally:
        connection.close()


@app.get("/orders/complete/<int:order_id>")
def order_complete(order_id):
    try:
        order = fetch_order(order_id)
    except Error:
        app.logger.exception("주문 완료 페이지 조회 실패")
        abort(503)
    if not order:
        abort(404)
    return render_template("order_complete.html", order=order)


@app.route("/lookup", methods=["GET", "POST"])
def lookup():
    order = None
    searched = False
    entered_number = request.values.get("order_number", "").strip()
    lookup_error = None
    if request.method == "POST" or entered_number:
        searched = True
        order_id = parse_order_number(entered_number)
        if order_id:
            try:
                order = fetch_order(order_id)
            except Error:
                app.logger.exception("주문 조회 실패")
                lookup_error = "주문을 확인하지 못했어요. 잠시 후 다시 시도해 주세요."
        else:
            lookup_error = "주문번호를 확인해 주세요. 예: MK-000001 또는 1"
    return render_template(
        "lookup.html", order=order, searched=searched, entered_number=entered_number,
        lookup_error=lookup_error
    )


@app.get("/orders")
def orders():
    search = request.args.get("order_id", "").strip()
    order_id = parse_order_number(search) if search else None
    if search and order_id is None:
        return render_template(
            "order_status.html", orders=[], search=search,
            error="주문번호를 확인해 주세요. 숫자 또는 MK-000001 형식으로 입력할 수 있어요.",
        )
    sql = """
        SELECT o.order_id, o.status, o.ordered_at, o.approved_at, o.completed_at, o.delivery_region,
               COUNT(oi.item_id) AS item_types,
               COALESCE(SUM(oi.quantity), 0) AS total_qty,
               COALESCE(SUM(oi.shipped_qty), 0) AS shipped_qty,
               COALESCE(SUM(oi.quantity * oi.unit_price), 0) - COALESCE(o.points_used, 0) AS total_amount
        FROM orders o
        LEFT JOIN order_items oi ON oi.order_id = o.order_id
    """
    params = ()
    if order_id is not None:
        sql += " WHERE o.order_id = %s"
        params = (order_id,)
    sql += """
        GROUP BY o.order_id, o.status, o.ordered_at, o.approved_at, o.completed_at, o.delivery_region, o.points_used
        ORDER BY o.ordered_at DESC, o.order_id DESC LIMIT 200
    """
    try:
        rows = query(sql, params)
        return render_template("order_status.html", orders=rows, search=search, error=None)
    except Error:
        app.logger.exception("주문 목록 조회 실패")
        return render_template(
            "order_status.html", orders=[], search=search,
            error="주문 목록을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.",
        ), 503


@app.get("/orders/<int:order_id>")
def order_detail(order_id):
    try:
        order = fetch_order(order_id)
        if not order:
            return render_template(
                "order_detail.html", order=None, items=[], jobs=[],
                error="해당 주문을 찾을 수 없어요. 주문번호를 확인해 주세요.",
            ), 404
        jobs = query(
            """
            SELECT oj.job_id, oj.item_id, p.name AS product_name, oj.status,
                   oj.retry_count, oj.created_at, oj.started_at, oj.completed_at
            FROM outbound_jobs oj
            JOIN order_items oi ON oi.item_id = oj.item_id
            JOIN products p ON p.product_id = oi.product_id
            WHERE oi.order_id = %s
            ORDER BY oj.job_id DESC
            """,
            (order_id,),
        )
        items = [dict(item, product_name=item["name"]) for item in order["items"]]
        return render_template(
            "order_detail.html", order=order, items=items, jobs=jobs, error=None,
        )
    except Error:
        app.logger.exception("주문 상세 및 출고 작업 조회 실패")
        return render_template(
            "order_detail.html", order=None, items=[], jobs=[],
            error="주문 상세를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.",
        ), 503


@app.get("/inquiry")
def inquiry():
    try:
        products = query(
            "SELECT product_id, name, color, price, stock, min_stock FROM products ORDER BY product_id"
        )
        jobs = query(
            """
            SELECT oj.job_id, oi.order_id, p.name AS product_name, oj.status,
                   oj.retry_count, oj.created_at
            FROM outbound_jobs oj
            JOIN order_items oi ON oi.item_id = oj.item_id
            JOIN products p ON p.product_id = oi.product_id
            ORDER BY oj.created_at DESC, oj.job_id DESC LIMIT 100
            """
        )
        logs = query(
            """
            SELECT ol.log_id, oi.order_id, p.name AS expected_name,
                   dp.name AS detected_name, ol.result, ol.destination, ol.created_at
            FROM outbound_logs ol
            JOIN outbound_jobs oj ON oj.job_id = ol.job_id
            JOIN order_items oi ON oi.item_id = oj.item_id
            JOIN products p ON p.product_id = ol.expected_product_id
            LEFT JOIN products dp ON dp.product_id = ol.detected_product_id
            ORDER BY ol.created_at DESC, ol.log_id DESC LIMIT 100
            """
        )
        return render_template(
            "inquiry.html", products=products, jobs=jobs, logs=logs, error=None,
        )
    except Error:
        app.logger.exception("물류 정보 조회 실패")
        return render_template(
            "inquiry.html", products=[], jobs=[], logs=[],
            error="물류 정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.",
        ), 503


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


@app.errorhandler(503)
def unavailable(_error):
    return render_template("db_error.html", error=None), 503


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)

