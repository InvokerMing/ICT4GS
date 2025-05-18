from flask import Flask, request, jsonify, session, render_template_string
from flask_cors import CORS
from flask_mail import Mail, Message
import uuid
import os
from dotenv import load_dotenv
from psycopg import OperationalError, DatabaseError, ProgrammingError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import json

# --- 配置 ---
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL', None)
SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'ict4gs')
DEFAULT_LANGUAGE = os.getenv('DEFAULT_LANGUAGE', 'en')

# --- 常量 ---
TICKET_TYPES = {
    "full": {"name_en": "Full Price", "name_zh": "全价票", "multiplier": 1.0},
    "discount": {"name_en": "Discount", "name_zh": "优惠票", "multiplier": 0.5},
    "free": {"name_en": "Free", "name_zh": "免费票", "multiplier": 0.0}
}
ADMIN_ROLE = "admin"

# --- 数据库连接池 ---
pool = None
if DATABASE_URL is None:
    print("Error: DATABASE_URL environment variable not found.")
    exit(1)
else:
    try:
        pool = ConnectionPool(
            conninfo=DATABASE_URL, min_size=1, max_size=5, timeout=10.0,
            kwargs={'row_factory': dict_row}
        )
        print("Database ConnectionPool Created.")
    except Exception as e:
        print(f"Error initializing connection pool: {e}")
        pool = None
        exit(1)

# --- Flask 应用 ---
frontend_folder_path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'frontend'))
app = Flask(__name__, static_folder=frontend_folder_path, static_url_path='/')

app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
CORS(app, supports_credentials=True)

app.config['Mail_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.example.com')
app.config['Mail_PORT'] = os.getenv('MAIL_PORT', 587)
app.config['Mail_USERNAME'] = os.getenv('MAIL_USERNAME', '')
app.config['Mail_PASSWORD'] = os.getenv('MAIL_PASSWORD', '')
app.config['Mail_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'true').lower() in ['true', '1', 'yes']
app.config['Mail_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'false').lower() in ['true', '1', 'yes']
app.config['Mail_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', app.config['Mail_USERNAME'])
mail = Mail(app)

# --- 邮件发送 ---
def send_purchase_email(order_details):
    """发送购买确认邮件"""
    print(f"--- Sending Purchase Email for Order {order_details.get('order_id')} ---")
    # return 
    if not app.config.get('Mail_USERNAME') or not app.config.get('Mail_PASSWORD'):
        print("Email configuration missing, skipping email sending.")
        return
    
    subject = f"Ticket Purchase Confirmation - Order {order_details.get('order_id')}"
    recipient = [order_details.get('customer_email')]

    html_body = render_template_string("""
        <!DOCTYPE html>
        <html>
        <head><title>{{ subject }}</title></head>
        <body>
            <h2>Thank you for your purchase!</h2>
            <p><strong>Order ID:</strong> {{ order.order_id }}</p>
            <p><strong>Attraction:</strong> {{ order.attraction_name }}</p>
            <p><strong>Usage Date:</strong> {{ order.usage_date }}</p>
            <p><strong>Customer Names:</strong> {{ names }}</p>
            <p><strong>Total Amount:</strong> Rp {{ "%.2f"|format(order.total_amount) }}</p>
            <hr>
            <h3>Order Items:</h3>
            <ul>
            {% for item in order.items %}
                <li>{{ item[3] }} x {{ item[2] }} ticket(s) @ Rp {{ "%.2f"|format(item[4]) }} each</li>
            {% endfor %}
            </ul>
            <hr>
            <p>Please present your order ID or QR code (if provided separately) upon arrival.</p>
            <p>Thank you!</p>
        </body>
        </html>
    """, subject=subject, order=order_details, names=", ".join(order_details.get('customer_names', [])))
                                       
    msg = Message(subject=subject,
                  sender=app.config['MAIL_DEFAULT_SENDER'],
                  recipients=[recipient],
                  html=html_body)
    try:
        with app.app_context():
            mail.send(msg)
        print(f"Confirmation email sent successfully to {recipient} for order {order_details.get('order_id')}.")
    except Exception as e:
        print(f"Error sending email to: {e}")

# --- 数据库初始化 ---
def init_db():
    """初始化数据库表结构、示例数据和默认管理员"""
    if not pool:
        print("Database pool unavailable, cannot initialize DB.")
        return
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            print("Initializing database tables...")
            # 创建 users 表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id SERIAL PRIMARY KEY,
                    username VARCHAR(80) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'admin',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );""")
            # 创建 attractions 表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS attractions (
                    attraction_id VARCHAR(50) PRIMARY KEY,
                    name JSONB,
                    summary JSONB,
                    details JSONB,
                    contact_info TEXT,
                    address_info TEXT,
                    transport_info TEXT,
                    image_url TEXT,
                    price NUMERIC(10, 2) NOT NULL DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );""")
            # 创建 orders 表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id VARCHAR(36) PRIMARY KEY,
                    customer_names TEXT,
                    customer_email VARCHAR(255),
                    usage_date DATE,
                    purchase_time TIMESTAMP WITH TIME ZONE NOT NULL,
                    total_amount NUMERIC(10, 2) NOT NULL,
                    status VARCHAR(50) DEFAULT 'completed',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );""")
            # 创建 order_items 表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS order_items (
                    item_id SERIAL PRIMARY KEY,
                    order_id VARCHAR(36) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
                    attraction_id VARCHAR(50) NOT NULL, -- No direct FK to allow flexibility if attractions are removed, but orders remain
                    ticket_type VARCHAR(50) NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    price_per_ticket NUMERIC(10, 2) NOT NULL
                );""")
            # 创建 individual_tickets 表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS individual_tickets (
                    individual_ticket_id VARCHAR(36) PRIMARY KEY,
                    order_item_id INTEGER NOT NULL REFERENCES order_items(item_id) ON DELETE CASCADE,
                    customer_name TEXT NOT NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'active', -- e.g., active, used, cancelled
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );""")
            # Trigger for updated_at on individual_tickets
            cur.execute("""
                CREATE OR REPLACE FUNCTION update_individual_ticket_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                   NEW.updated_at = NOW(); 
                   RETURN NEW;
                END;
                $$ language 'plpgsql';
                DROP TRIGGER IF EXISTS update_individual_ticket_updated_at ON individual_tickets;
                CREATE TRIGGER update_individual_ticket_updated_at
                BEFORE UPDATE ON individual_tickets
                FOR EACH ROW
                EXECUTE FUNCTION update_individual_ticket_updated_at_column();
            """)
            print("Tables checked/created.")

            # 添加默认管理员
            cur.execute("SELECT 1 FROM users WHERE username = %s", ('admin',))
            if not cur.fetchone():
                print("Adding default admin user (admin/password)...")
                hashed_password = generate_password_hash('password')
                cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                            ('admin', hashed_password, ADMIN_ROLE))

            # 添加示例景点
            cur.execute("SELECT 1 FROM attractions LIMIT 1;")
            if not cur.fetchone():
                print("Attractions table is empty. Attempting to load from JSON...")
                json_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'backend', 'res', 'default_attractions.json'))
                if os.path.exists(json_file_path):
                    try:
                        with open(json_file_path, 'r', encoding='utf-8') as f:
                            attractions_from_json = json.load(f)

                        attractions_to_insert = []
                        for attraction_data in attractions_from_json:
                            attraction_id = attraction_data.get('id')
                            if not attraction_id:
                                print(f"Skipping attraction due to missing 'id': {attraction_data}")
                                continue

                            # Helper to ensure we get English string, whether from a direct string or {"en": "text"}
                            def get_english_from_json_field(data, field_name, default_value=''):
                                value = data.get(field_name, default_value)
                                if isinstance(value, dict):
                                    return value.get('en', str(value.get(DEFAULT_LANGUAGE, default_value))) # Fallback to default lang or empty
                                return str(value) # Assume it's already the string we want (English)

                            name_en = get_english_from_json_field(attraction_data, 'name', attraction_id)
                            # Map 'description' to 'summary' and 'history' to 'details'
                            summary_en = get_english_from_json_field(attraction_data, 'description', '')
                            details_en = get_english_from_json_field(attraction_data, 'history', '')

                            # Store as JSONB object with 'en' key
                            name_jsonb = json.dumps({'en': name_en})
                            summary_jsonb = json.dumps({'en': summary_en})
                            details_jsonb = json.dumps({'en': details_en})
                            
                            contact = attraction_data.get('contact')
                            address = attraction_data.get('address')
                            transport = attraction_data.get('transportation')
                            image = attraction_data.get('image_url')
                            price = float(attraction_data.get('price', 0.0))

                            attractions_to_insert.append((
                                attraction_id, name_jsonb, summary_jsonb, details_jsonb,
                                contact, address, transport, image, price
                            ))

                        if attractions_to_insert:
                            insert_query = """
                                INSERT INTO attractions (
                                    attraction_id, name, summary, details, contact_info, address_info,
                                    transport_info, image_url, price
                                ) VALUES (%s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s);
                            """
                            cur.executemany(insert_query, attractions_to_insert)
                            print(f"Added {cur.rowcount} sample attractions from {json_file_path}.")
                        else:
                            print("No valid attractions found in JSON file.")

                    except json.JSONDecodeError as json_err:
                        print(f"Error decoding JSON from {json_file_path}: {json_err}")
                    except IOError as io_err:
                        print(f"Error reading file {json_file_path}: {io_err}")
                    except Exception as e: 
                        print(f"An unexpected error occurred while loading attractions from JSON: {e}")
                else:
                    print(f"Warning: Default attractions JSON file not found at {json_file_path}. No sample attractions loaded.")
            else:
                print("Attractions table already contains data. Skipping sample data loading.")
        print("Database initialization complete.")
    except Exception as error:
        print(f"Database initialization error: {error}")

# --- API 端点 ---
# --- 调试 API ---

# --- 公共 API ---
@app.route('/api/attractions', methods=['GET'])
def get_attractions():
    """获取所有景点信息"""
    lang = request.args.get('lang', DEFAULT_LANGUAGE) # lang is kept for potential future use or other fields, but name/summary are now EN only from DB
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection(timeout=5.0) as conn, conn.cursor() as cur:
            # Always fetch English name and summary from DB
            query = f"""
                SELECT
                    attraction_id,
                    name->>'en' AS name,
                    summary->>'en' AS summary,
                    image_url, price::float
                FROM attractions ORDER BY name->>'en';
            """
            cur.execute(query) # No lang parameters needed for name/summary
            attractions = cur.fetchall()
            return jsonify(attractions), 200
    except Exception as e: print(f"Error querying attractions: {e}"); return jsonify({"message": "Error retrieving attractions"}), 500

@app.route('/api/attractions/<string:attraction_id>', methods=['GET'])
def get_attraction_detail(attraction_id):
    """获取单个景点详情"""
    lang = request.args.get('lang', DEFAULT_LANGUAGE) # lang kept for potential future use
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection(timeout=5.0) as conn, conn.cursor() as cur:
            # Always fetch English name, summary, and details from DB
            query = f"""
                SELECT
                    attraction_id,
                    name->>'en' AS name,
                    summary->>'en' AS summary,
                    details->>'en' AS details,
                    image_url, price::float, contact_info, address_info, transport_info
                FROM attractions WHERE attraction_id = %s;
            """
            cur.execute(query, (attraction_id,)) # No lang parameters needed for these fields
            attraction = cur.fetchone()
            if not attraction: return jsonify({"message": "Attraction not found"}), 404
            return jsonify(attraction), 200
    except Exception as e: print(f"Error querying attraction detail: {e}"); return jsonify({"message": "Error retrieving attraction details"}), 500

@app.route('/api/purchase', methods=['POST'])
def handle_purchase():
    """处理购票请求"""
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    if not request.is_json: return jsonify({"message": "Request must be JSON"}), 400
    data = request.get_json()
    required = ["attraction_id", "quantities", "customer_names", "customer_email", "usage_date"]
    if not all(f in data for f in required): return jsonify({"message": "Missing required fields"}), 400
    attraction_id, quantities, names, email, date_str = data["attraction_id"], data.get("quantities",{}), data.get("customer_names",[]), data.get("customer_email"), data.get("usage_date")
    total_q = 0
    if not isinstance(quantities, dict): return jsonify({"message": "Invalid quantities format"}), 400
    for type, q in quantities.items():
        if type not in TICKET_TYPES: return jsonify({"message": f"Invalid ticket type: {type}"}), 400
        try: total_q += int(q) if int(q) >= 0 else 0
        except: return jsonify({"message": f"Invalid quantity for {type}"}), 400
    if not (0 < total_q <= 10): return jsonify({"message": "Total quantity must be 1-10"}), 400
    if not isinstance(names, list) or len(names) != total_q: return jsonify({"message": "Names count mismatch"}), 400
    if not all(isinstance(n, str) and n.strip() for n in names): return jsonify({"message": "Names cannot be empty"}), 400
    if not email or "@" not in email: return jsonify({"message": "Invalid email"}), 400
    try:
        usage_date = date.fromisoformat(date_str)
        assert usage_date >= date.today()
    except:
        return jsonify({"message": "Invalid usage date"}), 400

    order_id, purchase_time, names_json = str(uuid.uuid4()), datetime.now(timezone.utc), json.dumps(names)
    try:
        with pool.connection(timeout=5.0) as conn, conn.cursor() as cur:
            # 获取景点价格和英文名称 (用于邮件)
            cur.execute("SELECT price, name->>'en' AS name FROM attractions WHERE attraction_id = %s", (attraction_id,))
            attraction = cur.fetchone()
            assert attraction
            base_price, attraction_name = float(attraction['price'] or 0.0), attraction['name'] or attraction_id # Fallback name is English

            total_amount, items = 0.0, []
            for type, q in quantities.items():
                if q > 0:
                    price_per = base_price * TICKET_TYPES[type]["multiplier"]
                    total_amount += price_per * q
                    items.append((order_id, attraction_id, type, q, price_per))

            cur.execute("INSERT INTO orders (order_id, customer_names, customer_email, usage_date, purchase_time, total_amount) VALUES (%s, %s, %s, %s, %s, %s);", (order_id, names_json, email, usage_date, purchase_time, total_amount))
            cur.executemany("INSERT INTO order_items (order_id, attraction_id, ticket_type, quantity, price_per_ticket) VALUES (%s, %s, %s, %s, %s);", items)

        email_details = { "order_id": order_id, "customer_email": email, "attraction_name": attraction_name, "customer_names": names, "total_quantity": total_q, "usage_date": usage_date.isoformat(), "total_amount": total_amount, "items": items }
        send_purchase_email(email_details)
        return jsonify({"message": "Purchase successful", "order_id": order_id, "qr_data": order_id}), 201
    except AssertionError: return jsonify({"message": "Invalid attraction ID"}), 404
    except Exception as e: print(f"Purchase error: {e}"); return jsonify({"message": "Error processing purchase"}), 500
@app.route('/api/orders/<string:order_id>', methods=['GET'])
def get_order_details(order_id):

    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection(timeout=5.0) as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM orders WHERE order_id = %s;", (order_id,)) 
            order = cur.fetchone() 
            assert order
            # Fetch attraction_name in English
            cur.execute("SELECT oi.*, COALESCE(a.name->>'en', oi.attraction_id) AS attraction_name FROM order_items oi LEFT JOIN attractions a ON oi.attraction_id = a.attraction_id WHERE oi.order_id = %s ORDER BY oi.item_id;", (order_id,))
            items = cur.fetchall()
            details = dict(order)
            try: details['customer_names'] = json.loads(details['customer_names'] or '[]')
            except: details['customer_names'] = [n.strip() for n in (details.get('customer_names') or '').split(',') if n.strip()]
            for k in ['usage_date', 'purchase_time', 'created_at']: details[k] = details[k].isoformat() if details.get(k) else None
            details['total_amount'] = float(details['total_amount'] or 0.0)
            details['items'] = []
            for item in items:
                i_dict = dict(item)
                i_dict['price_per_ticket'] = float(i_dict['price_per_ticket'] or 0.0)
                i_dict['ticket_type_name_en'] = TICKET_TYPES.get(i_dict['ticket_type'], {}).get('name_en', i_dict['ticket_type'])
                i_dict['ticket_type_name_zh'] = TICKET_TYPES.get(i_dict['ticket_type'], {}).get('name_zh', i_dict['ticket_type'])
                details['items'].append(i_dict)
            return jsonify(details), 200
    except AssertionError: return jsonify({"message": "Order not found"}), 404
    except Exception as e: print(f"Order detail error: {e}"); return jsonify({"message": "Error retrieving order details"}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    target_date_str = request.args.get('date', date.today().isoformat())
    try: target_date = date.fromisoformat(target_date_str)
    except: return jsonify({"message": "Invalid date format (YYYY-MM-DD)"}), 400
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    stats = {"query_date": target_date.isoformat()}
    try:
        with pool.connection(timeout=10.0) as conn, conn.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(quantity), 0) AS total FROM order_items;")
            stats["overall_total_tickets"] = cur.fetchone()['total']
            # 使用英文名称
            cur.execute("SELECT a.attraction_id, COALESCE(a.name->>'en', oi.attraction_id) AS name, SUM(oi.quantity) AS count FROM order_items oi LEFT JOIN attractions a ON oi.attraction_id = a.attraction_id GROUP BY a.attraction_id, name, oi.attraction_id ORDER BY count DESC, name;")
            stats["overall_tickets_by_attraction"] = [{'id': r['attraction_id'], 'name': r['name'], 'count': int(r['count'])} for r in cur.fetchall()]
            date_filter = "DATE(o.purchase_time AT TIME ZONE 'UTC')"
            cur.execute(f"SELECT COALESCE(SUM(oi.quantity), 0) AS total FROM order_items oi JOIN orders o ON oi.order_id = o.order_id WHERE {date_filter} = %s;", (target_date,))
            stats["specific_date_total_tickets"] = cur.fetchone()['total']
            
            cur.execute(f"SELECT a.attraction_id, COALESCE(a.name->>'en', oi.attraction_id) AS name, SUM(oi.quantity) AS count FROM order_items oi JOIN orders o ON oi.order_id = o.order_id LEFT JOIN attractions a ON oi.attraction_id = a.attraction_id WHERE {date_filter} = %s GROUP BY a.attraction_id, name, oi.attraction_id ORDER BY count DESC, name;", (target_date,))
            stats["specific_date_tickets_by_attraction"] = [{'id': r['attraction_id'], 'name': r['name'], 'count': int(r['count'])} for r in cur.fetchall()]
        return jsonify(stats), 200
    except Exception as e: print(f"Stats error: {e}"); return jsonify({"message": "Error retrieving statistics"}), 500

# --- 管理员 API ---
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    if not request.is_json: return jsonify({"message": "Request must be JSON"}), 400
    data = request.get_json()
    username, password = data.get('username'), data.get('password')
    if not username or not password: return jsonify({"message": "Username and password required"}), 400
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT user_id, username, password_hash, role FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session.permanent = True
                session['user_id'] = user['user_id']
                session['username'] = user['username']
                session['role'] = user['role']
                return jsonify({"message": "Login successful", "username": user['username'], "role": user['role']}), 200
            else: return jsonify({"message": "Invalid username or password"}), 401
    except Exception as e: print(f"Login error: {e}"); return jsonify({"message": "Error during login"}), 500

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.clear()
    return jsonify({"message": "Logout successful"}), 200

@app.route('/api/admin/status', methods=['GET'])
def admin_status():
    if 'user_id' in session:
        return jsonify({"logged_in": True, "user_id": session['user_id'], "username": session['username'], "role": session['role']}), 200
    else:
        return jsonify({"logged_in": False}), 200

@app.route('/api/admin/attractions', methods=['GET'])
def admin_get_attractions():
    """获取所有景点信息 (管理员视图, 返回完整 JSONB)"""
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            # 返回英文文本供前端编辑
            cur.execute("""
                SELECT attraction_id, name->>'en' as name, summary->>'en' as summary, details->>'en' as details,
                       contact_info, address_info, transport_info, image_url, price::float, created_at
                FROM attractions ORDER BY name->>'en';
            """)
            attractions = cur.fetchall()
            for a in attractions: a['created_at'] = a['created_at'].isoformat() if a.get('created_at') else None
            return jsonify(attractions), 200
    except Exception as e: print(f"Admin get attractions error: {e}"); return jsonify({"message": "Error fetching attractions"}), 500

@app.route('/api/admin/attractions', methods=['POST'])
def admin_add_attraction():
    """添加新景点 (接收纯英文文本 for name, summary, details)"""
    if not request.is_json: return jsonify({"message": "Request must be JSON"}), 400
    data = request.get_json()
    required = ['attraction_id', 'price', 'name'] # Name is now a simple string
    if not all(f in data and data[f] not in [None, ""] for f in required): return jsonify({"message": "Missing attraction_id, price, or name"}), 400
    
    try:
        price = float(data['price'])
        assert price >= 0
    except:
        return jsonify({"message": "Invalid price"}), 400

    # Store name, summary, details as {"en": "text"} in JSONB
    name_jsonb = json.dumps({'en': data.get('name','')}) # name is required
    summary_jsonb = json.dumps({'en': data.get('summary','')})
    details_jsonb = json.dumps({'en': data.get('details','')})

    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO attractions (
                    attraction_id, name, summary, details, contact_info, address_info,
                    transport_info, image_url, price
                ) VALUES (%s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)
                RETURNING attraction_id;
            """, (
                data['attraction_id'], name_jsonb, summary_jsonb, details_jsonb,
                data.get('contact_info'), data.get('address_info'), data.get('transport_info'),
                data.get('image_url'), price
            ))
            new = cur.fetchone()
            return jsonify({"message": "Attraction added", "attraction": new}), 201
    except DatabaseError as e:
        if "duplicate key value violates unique constraint" in str(e): return jsonify({"message": f"ID '{data['attraction_id']}' already exists"}), 409
        print(f"DB error adding attraction: {e}")
        return jsonify({"message": "Database error"}), 500
    except Exception as e: print(f"Error adding attraction: {e}"); return jsonify({"message": "Server error"}), 500

@app.route('/api/admin/attractions/<string:attraction_id>', methods=['PUT'])
def admin_update_attraction(attraction_id):
    """更新景点信息 (接收纯英文文本 for name, summary, details)"""
    if not request.is_json: return jsonify({"message": "Request must be JSON"}), 400
    data = request.get_json()
    
    if not data.get('price') or not data.get('name'): return jsonify({"message": "Missing price or name"}), 400
    try:
        price = float(data['price'])
        assert price >= 0
    except:
        return jsonify({"message": "Invalid price"}), 400

    # Store name, summary, details as {"en": "text"} in JSONB
    name_jsonb = json.dumps({'en': data.get('name','')})
    summary_jsonb = json.dumps({'en': data.get('summary','')})
    details_jsonb = json.dumps({'en': data.get('details','')})

    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE attractions SET
                    name=%s::jsonb, summary=%s::jsonb, details=%s::jsonb,
                    contact_info=%s, address_info=%s, transport_info=%s,
                    image_url=%s, price=%s
                WHERE attraction_id=%s RETURNING attraction_id;
            """, (
                name_jsonb, summary_jsonb, details_jsonb,
                data.get('contact_info'), data.get('address_info'), data.get('transport_info'),
                data.get('image_url'), price, attraction_id
            ))
            updated = cur.fetchone()
            if updated: return jsonify({"message": "Attraction updated", "attraction_id": updated['attraction_id']}), 200
            else: return jsonify({"message": "Attraction not found"}), 404
    except Exception as e: print(f"Error updating attraction: {e}"); return jsonify({"message": "Error updating attraction"}), 500

@app.route('/api/admin/attractions/<string:attraction_id>', methods=['DELETE'])
def admin_delete_attraction(attraction_id):
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM attractions WHERE attraction_id = %s RETURNING attraction_id;", (attraction_id,))
            deleted = cur.fetchone()
            if deleted: return jsonify({"message": "Attraction deleted", "attraction_id": deleted['attraction_id']}), 200
            else: return jsonify({"message": "Attraction not found"}), 404
    except DatabaseError as e:
        if "violates foreign key constraint" in str(e): return jsonify({"message": "Cannot delete: referenced by orders"}), 409 #TODO: check if this is still true or if orders should be cascade deleted or prevented
        print(f"DB error deleting attraction: {e}")
        return jsonify({"message": "Database error"}), 500
    except Exception as e: print(f"Error deleting attraction: {e}"); return jsonify({"message": "Server error"}), 500

# --- Language List API ---
@app.route('/api/languages', methods=['GET'])
def get_languages():
    """获取可用的语言列表"""
    languages_dir = os.path.join(frontend_folder_path, 'languages')
    available_languages = []
    try:
        if os.path.exists(languages_dir) and os.path.isdir(languages_dir):
            for filename in os.listdir(languages_dir):
                if filename.endswith(".json"):
                    lang_code = filename[:-5] # remove .json
                    # Validate lang_code format if necessary (e.g., 2 letters, or 2-2 format)
                    if lang_code: # Basic check
                        available_languages.append(lang_code)
        return jsonify(available_languages), 200
    except Exception as e:
        print(f"Error listing languages: {e}")
        return jsonify({"message": "Error fetching language list"}), 500

# --- 应用启动 ---
if __name__ == '__main__':
    if pool is None:
        print("Error: Database pool not initialized. Exiting.")
        exit(1)
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)

