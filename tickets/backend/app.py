from flask import Flask, request, jsonify, session
from flask_cors import CORS
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
SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'ict4gs') # 生产环境应使用更安全的密钥

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
            kwargs={'row_factory': dict_row} # 使查询结果返回字典
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
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax' # CSRF 保护
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1) # Session 超时
CORS(app, supports_credentials=True) # 允许跨域请求携带凭证 (用于 session)

# --- 邮件发送占位符 ---
def send_purchase_email(order_details):
    """预留的发送购买确认邮件的函数"""
    print(f"--- Sending Purchase Email (Placeholder) for Order {order_details.get('order_id')} ---")
    pass

# --- 数据库初始化 ---
def init_db():
    """初始化数据库表结构、示例数据和默认管理员"""
    if not pool: print("Database pool unavailable, cannot initialize DB."); return
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            print("Initializing database tables...")
            # 创建 users 表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id SERIAL PRIMARY KEY, username VARCHAR(80) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL, role VARCHAR(20) NOT NULL DEFAULT 'admin',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );""")
            # 创建 attractions 表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS attractions (
                    attraction_id VARCHAR(50) PRIMARY KEY, name_en VARCHAR(255) NOT NULL,
                    name_zh VARCHAR(255) NOT NULL, description_en TEXT, description_zh TEXT,
                    image_url TEXT, price NUMERIC(10, 2) NOT NULL DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );""")
            # 创建 orders 表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id VARCHAR(36) PRIMARY KEY, customer_names TEXT, customer_email VARCHAR(255),
                    usage_date DATE, purchase_time TIMESTAMP WITH TIME ZONE NOT NULL,
                    total_amount NUMERIC(10, 2) NOT NULL, status VARCHAR(50) DEFAULT 'completed',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );""")
            # 创建 order_items 表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS order_items (
                    item_id SERIAL PRIMARY KEY, order_id VARCHAR(36) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
                    attraction_id VARCHAR(50) NOT NULL, ticket_type VARCHAR(50) NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0), price_per_ticket NUMERIC(10, 2) NOT NULL
                );""")
            print("Tables checked/created.")

            # 添加默认管理员 (如果不存在)
            cur.execute("SELECT 1 FROM users WHERE username = %s", ('admin',))
            if not cur.fetchone():
                print("Adding default admin user (admin/password)...")
                hashed_password = generate_password_hash('password')
                cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                            ('admin', hashed_password, ADMIN_ROLE))

            # 添加示例景点 (如果不存在)
            cur.execute("SELECT 1 FROM attractions LIMIT 1;")
            if not cur.fetchone():
                print("Adding sample attractions...")
                sample_attractions = [
                    ('palace_a', 'Sultan Palace A', '苏丹宫殿 A', 'Experience Javanese royal culture.', '体验爪哇皇家文化。', 'https://placehold.co/600x400/eeddcc/775533?text=Palace+A', 50000.00),
                    ('museum_b', 'Batik Museum B', '蜡染博物馆 B', 'Explore Indonesian batik art.', '探索印尼蜡染艺术。', 'https://placehold.co/600x400/ddeeff/335577?text=Museum+B', 30000.00),
                    ('handicraft_c', 'Handicraft Center C', '手工艺中心 C', 'Shop for traditional crafts.', '购买传统手工艺品。', 'https://placehold.co/600x400/eeeedd/777755?text=Handicraft+C', 20000.00)
                ]
                insert_query = "INSERT INTO attractions (attraction_id, name_en, name_zh, description_en, description_zh, image_url, price) VALUES (%s, %s, %s, %s, %s, %s, %s);"
                cur.executemany(insert_query, sample_attractions)
                print(f"Added {cur.rowcount} sample attractions.")
        print("Database initialization complete.")
    except Exception as error:
        print(f"Database initialization error: {error}")

# --- API 端点 ---

# --- 公共 API ---
@app.route('/api/attractions', methods=['GET'])
def get_attractions():
    """获取所有景点信息 (支持语言)"""
    lang = request.args.get('lang', 'en')
    name_col, desc_col = (f"name_{lang}", f"description_{lang}") if lang == 'zh' else ("name_en", "description_en")
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection(timeout=5.0) as conn, conn.cursor() as cur:
            query = f"SELECT attraction_id, {name_col} AS name, {desc_col} AS description, image_url, price FROM attractions ORDER BY {name_col};"
            cur.execute(query)
            attractions = cur.fetchall()
            for a in attractions: a['price'] = float(a['price'] or 0.0) # 确保价格是浮点数
            return jsonify(attractions), 200
    except Exception as e: print(f"Error querying attractions: {e}"); return jsonify({"message": "Error retrieving attractions"}), 500

@app.route('/api/attractions/<string:attraction_id>', methods=['GET'])
def get_attraction_detail(attraction_id):
    """获取单个景点详情 (支持语言)"""
    lang = request.args.get('lang', 'en')
    name_col, desc_col = (f"name_{lang}", f"description_{lang}") if lang == 'zh' else ("name_en", "description_en")
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection(timeout=5.0) as conn, conn.cursor() as cur:
            query = f"SELECT attraction_id, {name_col} AS name, {desc_col} AS description, image_url, price FROM attractions WHERE attraction_id = %s;"
            cur.execute(query, (attraction_id,))
            attraction = cur.fetchone()
            if not attraction: return jsonify({"message": "Attraction not found"}), 404
            attraction['price'] = float(attraction['price'] or 0.0)
            return jsonify(attraction), 200
    except Exception as e: print(f"Error querying attraction detail: {e}"); return jsonify({"message": "Error retrieving attraction details"}), 500

@app.route('/api/purchase', methods=['POST'])
def handle_purchase():
    """处理购票请求"""
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    if not request.is_json: return jsonify({"message": "Request must be JSON"}), 400
    data = request.get_json()
    # 基本验证
    required = ["attraction_id", "quantities", "customer_names", "customer_email", "usage_date"]
    if not all(f in data for f in required): return jsonify({"message": "Missing required fields"}), 400
    attraction_id, quantities, names, email, date_str = data["attraction_id"], data.get("quantities",{}), data.get("customer_names",[]), data.get("customer_email"), data.get("usage_date")
    # 验证数量和类型
    total_q = 0
    if not isinstance(quantities, dict): return jsonify({"message": "Invalid quantities format"}), 400
    for type, q in quantities.items():
        if type not in TICKET_TYPES: return jsonify({"message": f"Invalid ticket type: {type}"}), 400
        try: total_q += int(q) if int(q) >= 0 else 0
        except: return jsonify({"message": f"Invalid quantity for {type}"}), 400
    # 验证总数和姓名数量匹配
    if not (0 < total_q <= 10): return jsonify({"message": "Total quantity must be 1-10"}), 400
    if not isinstance(names, list) or len(names) != total_q: return jsonify({"message": "Names count mismatch"}), 400
    if not all(isinstance(n, str) and n.strip() for n in names): return jsonify({"message": "Names cannot be empty"}), 400
    # 验证邮箱和日期
    if not email or "@" not in email: return jsonify({"message": "Invalid email"}), 400
    try: usage_date = date.fromisoformat(date_str); assert usage_date >= date.today()
    except: return jsonify({"message": "Invalid usage date"}), 400

    order_id, purchase_time, names_json = str(uuid.uuid4()), datetime.now(timezone.utc), json.dumps(names)
    try:
        with pool.connection(timeout=5.0) as conn, conn.cursor() as cur:
            # 获取景点价格
            cur.execute("SELECT price, name_en FROM attractions WHERE attraction_id = %s", (attraction_id,)); attraction = cur.fetchone(); assert attraction
            base_price, attraction_name = float(attraction['price'] or 0.0), attraction['name_en']
            # 计算总价和订单项
            total_amount, items = 0.0, []
            for type, q in quantities.items():
                if q > 0: price_per = base_price * TICKET_TYPES[type]["multiplier"]; total_amount += price_per * q; items.append((order_id, attraction_id, type, q, price_per))
            # 插入订单
            cur.execute("INSERT INTO orders (order_id, customer_names, customer_email, usage_date, purchase_time, total_amount) VALUES (%s, %s, %s, %s, %s, %s);",
                        (order_id, names_json, email, usage_date, purchase_time, total_amount))
            # 插入订单项
            cur.executemany("INSERT INTO order_items (order_id, attraction_id, ticket_type, quantity, price_per_ticket) VALUES (%s, %s, %s, %s, %s);", items)
        # 发送邮件 (占位符)
        send_purchase_email({"order_id": order_id, "customer_email": email, "attraction_name": attraction_name, "total_quantity": total_q, "usage_date": usage_date.isoformat(), "total_amount": total_amount, "items": items})
        return jsonify({"message": "Purchase successful", "order_id": order_id, "qr_data": order_id}), 201
    except AssertionError: return jsonify({"message": "Invalid attraction ID"}), 404
    except Exception as e: print(f"Purchase error: {e}"); return jsonify({"message": "Error processing purchase"}), 500

@app.route('/api/orders/<string:order_id>', methods=['GET'])
def get_order_details(order_id):
    """获取订单详情"""
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection(timeout=5.0) as conn, conn.cursor() as cur:
            # 获取订单主信息
            cur.execute("SELECT * FROM orders WHERE order_id = %s;", (order_id,)); order = cur.fetchone(); assert order
            # 获取订单项和景点名称
            cur.execute("SELECT oi.*, a.name_en AS attraction_name FROM order_items oi LEFT JOIN attractions a ON oi.attraction_id = a.attraction_id WHERE oi.order_id = %s ORDER BY oi.item_id;", (order_id,)); items = cur.fetchall()
            # 格式化结果
            details = dict(order)
            try: details['customer_names'] = json.loads(details['customer_names'] or '[]')
            except: details['customer_names'] = [n.strip() for n in (details.get('customer_names') or '').split(',') if n.strip()]
            for k in ['usage_date', 'purchase_time', 'created_at']: details[k] = details[k].isoformat() if details.get(k) else None
            details['total_amount'] = float(details['total_amount'] or 0.0)
            details['items'] = []
            for item in items:
                i_dict = dict(item); i_dict['price_per_ticket'] = float(i_dict['price_per_ticket'] or 0.0)
                i_dict['ticket_type_name_en'] = TICKET_TYPES.get(i_dict['ticket_type'], {}).get('name_en', i_dict['ticket_type'])
                i_dict['ticket_type_name_zh'] = TICKET_TYPES.get(i_dict['ticket_type'], {}).get('name_zh', i_dict['ticket_type'])
                details['items'].append(i_dict)
            return jsonify(details), 200
    except AssertionError: return jsonify({"message": "Order not found"}), 404
    except Exception as e: print(f"Order detail error: {e}"); return jsonify({"message": "Error retrieving order details"}), 500

@app.route('/api/stats', methods=['GET'])
# @login_required # 暂时移除登录检查
def get_stats():
    """获取销售统计 (总体, 今天/特定日期)"""
    target_date_str = request.args.get('date', date.today().isoformat())
    try: target_date = date.fromisoformat(target_date_str)
    except: return jsonify({"message": "Invalid date format (YYYY-MM-DD)"}), 400
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    stats = {"query_date": target_date.isoformat()}
    try:
        with pool.connection(timeout=10.0) as conn, conn.cursor() as cur:
            # 总体统计
            cur.execute("SELECT COALESCE(SUM(quantity), 0) AS total FROM order_items;")
            stats["overall_total_tickets"] = cur.fetchone()['total']
            cur.execute("""
                SELECT a.attraction_id, COALESCE(a.name_en, oi.attraction_id) AS name, SUM(oi.quantity) AS count
                FROM order_items oi LEFT JOIN attractions a ON oi.attraction_id = a.attraction_id
                GROUP BY a.attraction_id, a.name_en, oi.attraction_id
                ORDER BY count DESC, name;""")
            stats["overall_tickets_by_attraction"] = [{'id': r['attraction_id'], 'name': r['name'], 'count': int(r['count'])} for r in cur.fetchall()]
            # 特定日期统计 (基于 orders.purchase_time)
            date_filter = "DATE(o.purchase_time AT TIME ZONE 'UTC')" # 假设数据库时区为UTC
            cur.execute(f"SELECT COALESCE(SUM(oi.quantity), 0) AS total FROM order_items oi JOIN orders o ON oi.order_id = o.order_id WHERE {date_filter} = %s;", (target_date,))
            stats["specific_date_total_tickets"] = cur.fetchone()['total']
            cur.execute(f"""
                SELECT a.attraction_id, COALESCE(a.name_en, oi.attraction_id) AS name, SUM(oi.quantity) AS count
                FROM order_items oi JOIN orders o ON oi.order_id = o.order_id LEFT JOIN attractions a ON oi.attraction_id = a.attraction_id
                WHERE {date_filter} = %s
                GROUP BY a.attraction_id, a.name_en, oi.attraction_id
                ORDER BY count DESC, name;""", (target_date,))
            stats["specific_date_tickets_by_attraction"] = [{'id': r['attraction_id'], 'name': r['name'], 'count': int(r['count'])} for r in cur.fetchall()]
        return jsonify(stats), 200
    except Exception as e: print(f"Stats error: {e}"); return jsonify({"message": "Error retrieving statistics"}), 500

# --- 管理员 API ---
# 注意：以下 API 暂时没有 @login_required 保护

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    """管理员登录"""
    if not request.is_json: return jsonify({"message": "Request must be JSON"}), 400
    data = request.get_json(); username, password = data.get('username'), data.get('password')
    if not username or not password: return jsonify({"message": "Username and password required"}), 400
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT user_id, username, password_hash, role FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session.permanent = True; session['user_id'] = user['user_id']; session['username'] = user['username']; session['role'] = user['role']
                return jsonify({"message": "Login successful", "username": user['username'], "role": user['role']}), 200
            else: return jsonify({"message": "Invalid username or password"}), 401
    except Exception as e: print(f"Login error: {e}"); return jsonify({"message": "Error during login"}), 500

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    """管理员登出"""
    session.clear(); return jsonify({"message": "Logout successful"}), 200

@app.route('/api/admin/status', methods=['GET'])
def admin_status():
    """检查登录状态 (暂时无需登录也可访问)"""
    if 'user_id' in session:
        return jsonify({"logged_in": True, "user_id": session['user_id'], "username": session['username'], "role": session['role']}), 200
    else:
        # 即使没有登录装饰器，也返回未登录状态，以便前端判断
        return jsonify({"logged_in": False}), 200

@app.route('/api/admin/attractions', methods=['GET'])
# @login_required # 暂时移除
def admin_get_attractions():
    """获取所有景点信息 (管理员视图)"""
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT *, price::float FROM attractions ORDER BY name_en;") # 获取所有字段
            attractions = cur.fetchall()
            for a in attractions: a['created_at'] = a['created_at'].isoformat() if a.get('created_at') else None
            return jsonify(attractions), 200
    except Exception as e: print(f"Admin get attractions error: {e}"); return jsonify({"message": "Error fetching attractions"}), 500

@app.route('/api/admin/attractions', methods=['POST'])
# @login_required # 暂时移除
def admin_add_attraction():
    """添加新景点"""
    if not request.is_json: return jsonify({"message": "Request must be JSON"}), 400
    data = request.get_json(); required = ['attraction_id', 'name_en', 'name_zh', 'price']
    if not all(f in data and data[f] not in [None, ""] for f in required): return jsonify({"message": "Missing required fields"}), 400
    try: price = float(data['price']); assert price >= 0
    except: return jsonify({"message": "Invalid price"}), 400
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO attractions (attraction_id, name_en, name_zh, description_en, description_zh, image_url, price) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING attraction_id;",
                        (data['attraction_id'], data['name_en'], data['name_zh'], data.get('description_en'), data.get('description_zh'), data.get('image_url'), price))
            new = cur.fetchone()
            return jsonify({"message": "Attraction added", "attraction": new}), 201
    except DatabaseError as e: # 更具体的错误捕获
        if "duplicate key value violates unique constraint" in str(e): return jsonify({"message": f"ID '{data['attraction_id']}' already exists"}), 409
        print(f"DB error adding attraction: {e}"); return jsonify({"message": "Database error"}), 500
    except Exception as e: print(f"Error adding attraction: {e}"); return jsonify({"message": "Server error"}), 500

@app.route('/api/admin/attractions/<string:attraction_id>', methods=['PUT'])
# @login_required # 暂时移除
def admin_update_attraction(attraction_id):
    """更新景点信息"""
    if not request.is_json: return jsonify({"message": "Request must be JSON"}), 400
    data = request.get_json(); required = ['name_en', 'name_zh', 'price']
    if not all(f in data and data[f] not in [None, ""] for f in required): return jsonify({"message": "Missing required fields"}), 400
    try: price = float(data['price']); assert price >= 0
    except: return jsonify({"message": "Invalid price"}), 400
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE attractions SET name_en=%s, name_zh=%s, description_en=%s, description_zh=%s, image_url=%s, price=%s WHERE attraction_id=%s RETURNING attraction_id;",
                        (data['name_en'], data['name_zh'], data.get('description_en'), data.get('description_zh'), data.get('image_url'), price, attraction_id))
            updated = cur.fetchone()
            if updated: return jsonify({"message": "Attraction updated", "attraction_id": updated['attraction_id']}), 200
            else: return jsonify({"message": "Attraction not found"}), 404
    except Exception as e: print(f"Error updating attraction: {e}"); return jsonify({"message": "Error updating attraction"}), 500

@app.route('/api/admin/attractions/<string:attraction_id>', methods=['DELETE'])
# @login_required # 暂时移除
def admin_delete_attraction(attraction_id):
    """删除景点"""
    if not pool: return jsonify({"message": "Database service unavailable"}), 503
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM attractions WHERE attraction_id = %s RETURNING attraction_id;", (attraction_id,))
            deleted = cur.fetchone()
            if deleted: return jsonify({"message": "Attraction deleted", "attraction_id": deleted['attraction_id']}), 200
            else: return jsonify({"message": "Attraction not found"}), 404
    except DatabaseError as e: # 更具体的错误捕获
        if "violates foreign key constraint" in str(e): return jsonify({"message": "Cannot delete: referenced by orders"}), 409
        print(f"DB error deleting attraction: {e}"); return jsonify({"message": "Database error"}), 500
    except Exception as e: print(f"Error deleting attraction: {e}"); return jsonify({"message": "Server error"}), 500

# --- 应用启动 ---
if __name__ == '__main__':
    if pool is None:
        print("Error: Database pool not initialized. Exiting.")
        exit(1)
    init_db();
    app.run(host='0.0.0.0', port=5000, debug=True)

