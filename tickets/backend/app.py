from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid
import os
from dotenv import load_dotenv
import psycopg
from psycopg import OperationalError, InterfaceError, DatabaseError, ProgrammingError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout
from datetime import date, datetime

# --- 数据库配置 (Database Configuration) ---
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL', None)

# --- 全局常量 (Global Constants) ---
TICKET_TYPES = {
    "full": {"name": "全价票", "multiplier": 1.0},
    "discount": {"name": "优惠票", "multiplier": 0.5}, 
    "free": {"name": "免费票", "multiplier": 0.0}
}

# --- 初始化数据库连接池 (Initialize Database Connection Pool) ---
pool = None
if DATABASE_URL is None:
    print("Error: DATABASE_URL environment variable not found.")
    exit(1)
else:
    try:
        pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=5,
            timeout=10.0,
            kwargs={'row_factory': dict_row}
        )
        print("Database ConnectionPool Created.")
    except OperationalError as e:
        print(f"Database connection failed: {e}")
        pool = None
    except Exception as e:
        print(f"Error initializing connection pool: {e}")
        pool = None

# --- Flask 应用设置 (Flask App Setup) ---
app = Flask(__name__)
CORS(app)

# --- 邮件发送占位符 (Placeholder for Email Sending) ---
def send_purchase_email(order_details):
    """预留的发送购买确认邮件的函数 (Placeholder function to send purchase confirmation email)"""
    print(f"--- Sending Purchase Email (Placeholder) ---")
    print(f"To: {order_details.get('customer_email')}")
    print(f"Order ID: {order_details.get('order_id')}")
    print(f"Attraction: {order_details.get('attraction_name')}")
    print(f"Quantity: {order_details.get('quantity')}")
    print(f"Ticket Type: {order_details.get('ticket_type_name')}")
    print(f"Usage Date: {order_details.get('usage_date')}")
    print(f"Total Amount: {order_details.get('total_amount')}")
    print(f"--- Email End ---")
    # 在实际应用中，这里会集成邮件发送库 (e.g., smtplib, Flask-Mail)
    # In a real application, integrate an email library here
    pass

# --- 数据库初始化函数 (Database Initialization Function) ---
def init_db():
    """初始化数据库表结构和示例数据"""
    if not pool:
        print("Database pool unavailable, cannot initialize DB.")
        return

    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                print("开始初始化数据库表...")
                # 创建 attractions 表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS attractions (
                        attraction_id VARCHAR(50) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,
                        price NUMERIC(10, 2) NOT NULL DEFAULT 0, -- Base price for a full ticket
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                print("Table attractions Created")

                # 创建 orders 表 (添加 customer_name, customer_email, usage_date)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        order_id VARCHAR(36) PRIMARY KEY,
                        customer_name VARCHAR(255),       -- 添加客户姓名 (Added customer name)
                        customer_email VARCHAR(255),      -- 添加客户邮箱 (Added customer email)
                        usage_date DATE,                  -- 添加使用日期 (Added usage date)
                        purchase_time TIMESTAMP WITH TIME ZONE NOT NULL,
                        total_amount NUMERIC(10, 2) NOT NULL,
                        status VARCHAR(50) DEFAULT 'completed',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                print("Table orders Created")

                # 创建 order_items 表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS order_items (
                        item_id SERIAL PRIMARY KEY,
                        order_id VARCHAR(36) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
                        attraction_id VARCHAR(50) NOT NULL, -- Consider adding FOREIGN KEY
                        ticket_type VARCHAR(50) NOT NULL, -- e.g., 'full', 'discount', 'free'
                        quantity INTEGER NOT NULL CHECK (quantity > 0),
                        price_per_ticket NUMERIC(10, 2) NOT NULL, -- Price actually paid per ticket
                        UNIQUE (order_id, attraction_id, ticket_type) -- Allow different ticket types for same attraction in one order? Maybe remove uniqueness on ticket_type? For now, keep it.
                    );
                """)
                print("Table order_items Created")

                # --- 添加示例景点数据 ---
                cur.execute("SELECT COUNT(*) AS count FROM attractions;")
                attraction_count_result = cur.fetchone()
                attraction_count = attraction_count_result['count'] if attraction_count_result else 0

                if attraction_count == 0:
                    print("Attractions 表为空，正在添加示例数据...")
                    sample_attractions = [
                        ('palace_a', '苏丹宫殿 A', '体验爪哇皇家文化。', 50000.00),
                        ('museum_b', '蜡染博物馆 B', '探索印尼蜡染艺术。', 30000.00),
                        ('handicraft_c', '手工艺中心 C', '购买传统手工艺品。', 20000.00)
                    ]
                    insert_query = """
                        INSERT INTO attractions (attraction_id, name, description, price)
                        VALUES (%s, %s, %s, %s);
                    """
                    cur.executemany(insert_query, sample_attractions)
                    print(f"已添加 {cur.rowcount} 个示例景点。")
                # --- 示例数据添加结束 ---

            print("数据库表结构初始化/检查成功完成。")

    except PoolTimeout:
        print("DB connection timeout during init.")
    except (OperationalError, DatabaseError, ProgrammingError) as error: # Added ProgrammingError
        print(f"Database initialization error: {error}")
    except Exception as error:
        print(f"Unknown error during DB init: {error}")


# --- API 端点 (API Endpoints) ---

@app.route('/api/attractions', methods=['GET'])
def get_attractions():
    """获取所有景点信息的 API (Get API for all attractions)"""
    if not pool:
        return jsonify({"message": "Database service unavailable"}), 503

    try:
        with pool.connection(timeout=5.0) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT attraction_id, name, description, price FROM attractions ORDER BY name;")
                attractions = cur.fetchall()
                for attraction in attractions:
                    if 'price' in attraction and attraction['price'] is not None:
                        attraction['price'] = float(attraction['price'])
                    else:
                         attraction['price'] = 0.0
                return jsonify(attractions), 200
    except PoolTimeout:
        print("Timeout getting attractions list")
        return jsonify({"message": "Database request timed out"}), 504
    except (OperationalError, DatabaseError) as error:
        print(f"Error querying attractions: {error}")
        return jsonify({"message": "Database error retrieving attractions"}), 500
    except Exception as error:
        print(f"Unknown error getting attractions: {error}")
        return jsonify({"message": "Internal server error retrieving attractions"}), 500


@app.route('/api/purchase', methods=['POST'])
def handle_purchase():
    """处理购票请求 API (Handle ticket purchase API)"""
    if not pool:
        return jsonify({"message": "Database service unavailable"}), 503

    if not request.is_json:
        return jsonify({"message": "Request must be JSON"}), 400

    data = request.get_json()

    # --- 输入验证 (Input Validation) ---
    required_fields = ["attraction_id", "quantity", "ticket_type", "customer_name", "customer_email", "usage_date"]
    if not all(field in data and data[field] not in [None, ""] for field in required_fields):
        missing_or_empty = [field for field in required_fields if field not in data or data[field] in [None, ""]]
        return jsonify({"message": f"Missing or empty required fields: {', '.join(missing_or_empty)}"}), 400

    if data["ticket_type"] not in TICKET_TYPES:
        return jsonify({"message": f"Invalid ticket type: {data['ticket_type']}. Allowed types: {', '.join(TICKET_TYPES.keys())}"}), 400

    try:
        quantity = int(data["quantity"])
        if quantity < 1:
            raise ValueError("Quantity must be a positive integer")
        # Validate usage_date format (YYYY-MM-DD)
        usage_date = date.fromisoformat(data["usage_date"])
        # Basic email format check (not exhaustive)
        if "@" not in data["customer_email"] or "." not in data["customer_email"]:
            raise ValueError("Invalid email format")

    except (ValueError, TypeError) as ve:
        return jsonify({"message": f"Invalid input data: {ve}"}), 400

    order_id = str(uuid.uuid4())
    attraction_id = data["attraction_id"]
    ticket_type = data["ticket_type"]
    customer_name = data["customer_name"]
    customer_email = data["customer_email"]
    purchase_time = datetime.now() # Use server time

    try:
        with pool.connection(timeout=5.0) as conn:
            with conn.cursor() as cur:
                # 1. 获取景点基础价格 (Fetch base price for the attraction)
                cur.execute("SELECT price, name FROM attractions WHERE attraction_id = %s", (attraction_id,))
                attraction_info = cur.fetchone()
                if not attraction_info:
                    return jsonify({"message": f"Invalid attraction ID: {attraction_id}"}), 404 # Not Found

                base_price = float(attraction_info['price']) if attraction_info['price'] is not None else 0.0
                attraction_name = attraction_info['name']

                # 2. 计算价格 (Calculate price based on ticket type)
                multiplier = TICKET_TYPES[ticket_type]["multiplier"]
                price_per_ticket = base_price * multiplier
                total_amount = price_per_ticket * quantity

                # 3. 插入订单主表 (Insert into orders table)
                sql_order = """
                    INSERT INTO orders (order_id, customer_name, customer_email, usage_date, purchase_time, total_amount, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """
                order_status = 'completed'
                cur.execute(sql_order, (order_id, customer_name, customer_email, usage_date, purchase_time, total_amount, order_status))
                print(f"订单 {order_id} 插入 orders 表成功。")

                # 4. 插入订单项表 (Insert into order_items table)
                sql_item = """
                    INSERT INTO order_items (order_id, attraction_id, ticket_type, quantity, price_per_ticket)
                    VALUES (%s, %s, %s, %s, %s);
                """
                cur.execute(sql_item, (order_id, attraction_id, ticket_type, quantity, price_per_ticket))
                print(f"订单项 (景点: {attraction_id}, 类型: {ticket_type}) 插入 order_items 表成功。")

            # Transaction committed automatically

        # 5. 准备邮件所需信息并调用占位符 (Prepare email details and call placeholder)
        email_details = {
            "order_id": order_id,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "attraction_name": attraction_name,
            "quantity": quantity,
            "ticket_type_name": TICKET_TYPES[ticket_type]["name"],
            "usage_date": usage_date.isoformat(),
            "total_amount": total_amount,
            "purchase_time": purchase_time.isoformat()
        }
        send_purchase_email(email_details)

        # 6. 返回成功响应 (Return success response)
        return jsonify({
            "message": "Purchase successful",
            "order_id": order_id,
            "qr_data": order_id # Data to be encoded in QR code by frontend
        }), 201

    except PoolTimeout:
        print(f"Timeout processing purchase for order {order_id}")
        return jsonify({"message": "Database request timed out"}), 504
    except (OperationalError, DatabaseError) as error:
        print(f"Database error during purchase (Order {order_id}): {error}")
        # Consider more specific error checking, e.g., foreign key violation
        return jsonify({"message": "Database error processing purchase"}), 500
    except Exception as error:
        print(f"Unknown error during purchase (Order {order_id}): {error}")
        return jsonify({"message": "Internal server error processing purchase"}), 500


@app.route('/api/orders/<string:order_id>', methods=['GET'])
def get_order_details(order_id):
    """获取特定订单详情 API (Get details for a specific order API)"""
    if not pool:
        return jsonify({"message": "Database service unavailable"}), 503

    try:
        with pool.connection(timeout=5.0) as conn:
            with conn.cursor() as cur:
                # 查询订单主信息 (Query main order info)
                cur.execute("""
                    SELECT order_id, customer_name, customer_email, usage_date,
                           purchase_time, total_amount, status, created_at
                    FROM orders
                    WHERE order_id = %s;
                """, (order_id,))
                order = cur.fetchone()

                if not order:
                    return jsonify({"message": "Order not found"}), 404

                # 查询订单项信息并连接景点名称 (Query order items and join attraction name)
                cur.execute("""
                    SELECT
                        oi.item_id, oi.attraction_id, a.name AS attraction_name,
                        oi.ticket_type, oi.quantity, oi.price_per_ticket
                    FROM order_items oi
                    LEFT JOIN attractions a ON oi.attraction_id = a.attraction_id
                    WHERE oi.order_id = %s
                    ORDER BY oi.item_id;
                """, (order_id,))
                items = cur.fetchall()

                # 格式化数据 (Format data)
                order_details = dict(order) # Convert Row object to dict
                # Convert datetime/date objects to ISO strings for JSON
                order_details['usage_date'] = order_details['usage_date'].isoformat() if order_details.get('usage_date') else None
                order_details['purchase_time'] = order_details['purchase_time'].isoformat() if order_details.get('purchase_time') else None
                order_details['created_at'] = order_details['created_at'].isoformat() if order_details.get('created_at') else None
                order_details['total_amount'] = float(order_details['total_amount']) if order_details.get('total_amount') is not None else 0.0

                order_details['items'] = []
                for item in items:
                    item_dict = dict(item)
                    item_dict['price_per_ticket'] = float(item_dict['price_per_ticket']) if item_dict.get('price_per_ticket') is not None else 0.0
                     # Add ticket type display name
                    item_dict['ticket_type_name'] = TICKET_TYPES.get(item_dict['ticket_type'], {}).get('name', item_dict['ticket_type'])
                    order_details['items'].append(item_dict)

                return jsonify(order_details), 200

    except PoolTimeout:
        print(f"Timeout fetching order details for {order_id}")
        return jsonify({"message": "Database request timed out"}), 504
    except (OperationalError, DatabaseError) as error:
        print(f"Database error fetching order {order_id}: {error}")
        return jsonify({"message": "Database error retrieving order details"}), 500
    except Exception as error:
        print(f"Unknown error fetching order {order_id}: {error}")
        return jsonify({"message": "Internal server error retrieving order details"}), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取销售统计数据 API (Get sales statistics API)"""
    if not pool:
         return jsonify({"message": "Database service unavailable"}), 503

    try:
        with pool.connection(timeout=5.0) as conn:
            with conn.cursor() as cur:
                # 查询总票数 (Query total tickets sold)
                cur.execute("SELECT COALESCE(SUM(quantity), 0) AS total_tickets FROM order_items;")
                total_tickets_result = cur.fetchone()
                total_tickets = total_tickets_result['total_tickets']

                # 查询每个景点的售票数 (Query tickets sold per attraction)
                cur.execute("""
                    SELECT
                        oi.attraction_id,
                        COALESCE(a.name, oi.attraction_id) AS name,
                        SUM(oi.quantity) AS count
                    FROM order_items oi
                    LEFT JOIN attractions a ON oi.attraction_id = a.attraction_id
                    GROUP BY oi.attraction_id, a.name
                    ORDER BY count DESC, name;
                """)
                attraction_results = cur.fetchall()

        tickets_by_attraction = [
            {'id': row['attraction_id'], 'name': row['name'], 'count': int(row['count'])}
            for row in attraction_results
        ]

        return jsonify({
            "total_tickets": total_tickets,
            "tickets_by_attraction": tickets_by_attraction
        }), 200

    except PoolTimeout:
        print("Timeout getting statistics")
        return jsonify({"message": "Database request timed out"}), 504
    except (OperationalError, DatabaseError) as error:
        print(f"Error querying statistics: {error}")
        return jsonify({"message": "Database error retrieving statistics"}), 500
    except Exception as error:
        print(f"Unknown error getting statistics: {error}")
        return jsonify({"message": "Internal server error retrieving statistics"}), 500


# --- 应用启动入口 (Application Entry Point) ---
if __name__ == '__main__':
    if pool is None:
        print("Error: Database pool not initialized. Exiting.")
        exit(1)

    print("正在初始化数据库...")
    init_db()
    print("数据库初始化流程完成。")

    print("启动 Flask 应用...")
    app.run(host='0.0.0.0', port=5000, debug=True) # Use debug=False in production
