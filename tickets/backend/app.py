from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid
import os
from dotenv import load_dotenv
import psycopg
from psycopg import OperationalError, InterfaceError, DatabaseError
from psycopg.rows import dict_row # Import dict_row for dictionary cursors
from psycopg_pool import ConnectionPool, PoolTimeout

# --- 数据库配置 (Database Configuration) ---
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL', None)

# --- 初始化数据库连接池 (Initialize Database Connection Pool) ---
pool = None
if DATABASE_URL is None:
    print("错误：未找到 DATABASE_URL 环境变量。请确保 .env 文件存在且包含 DATABASE_URL。")
    exit(1) # Exit if DB URL is not found
else:
    try:
        pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=5,
            timeout=10.0,
            # Use dict_row for cursors by default in this pool
            kwargs={'row_factory': dict_row}
        )
        print("数据库连接池创建成功 (使用字典游标)。")
    except OperationalError as e:
        print(f"数据库连接失败: {e}")
        pool = None
    except Exception as e:
        print(f"初始化连接池时发生其他错误: {e}")
        pool = None

# --- Flask 应用设置 (Flask App Setup) ---
app = Flask(__name__)
# Allow all origins for simplicity in development.
# For production, restrict this to your frontend's origin.
CORS(app)

# --- 数据库初始化函数 (Database Initialization Function) ---
def init_db():
    """初始化数据库表结构和示例数据"""
    if not pool:
        print("数据库连接池不可用，无法初始化数据库。")
        return

    try:
        # Use a connection from the pool
        with pool.connection() as conn:
            # Cursors created from this connection will use the pool's row_factory (dict_row)
            with conn.cursor() as cur:
                print("开始初始化数据库表...")
                # 创建 attractions 表 (添加 description 和 price)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS attractions (
                        attraction_id VARCHAR(50) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,          -- 添加描述字段 (Added description field)
                        price NUMERIC(10, 2) NOT NULL DEFAULT 0, -- 添加价格字段 (Added price field)
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                print("检查/创建 attractions 表完成。")

                # 创建 orders 表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        order_id VARCHAR(36) PRIMARY KEY,
                        purchase_time TIMESTAMP WITH TIME ZONE NOT NULL,
                        total_amount NUMERIC(10, 2) NOT NULL,
                        status VARCHAR(50) DEFAULT 'completed',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                print("检查/创建 orders 表完成。")

                # 创建 order_items 表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS order_items (
                        item_id SERIAL PRIMARY KEY,
                        order_id VARCHAR(36) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
                        attraction_id VARCHAR(50) NOT NULL, -- Consider adding FOREIGN KEY REFERENCES attractions(attraction_id)
                        ticket_type VARCHAR(50) NOT NULL,
                        quantity INTEGER NOT NULL CHECK (quantity > 0),
                        price_per_ticket NUMERIC(10, 2) NOT NULL,
                        UNIQUE (order_id, attraction_id, ticket_type)
                    );
                """)
                print("检查/创建 order_items 表完成。")

                # --- 添加示例景点数据 (如果 attractions 表为空) ---
                cur.execute("SELECT COUNT(*) AS count FROM attractions;") # Use alias for clarity
                attraction_count_result = cur.fetchone()
                attraction_count = attraction_count_result['count'] if attraction_count_result else 0

                if attraction_count == 0:
                    print("Attractions 表为空，正在添加示例数据...")
                    # Add sample data including description and price
                    sample_attractions = [
                        ('palace_a', '苏丹宫殿 A', '体验爪哇皇家文化。', 50000.00),
                        ('museum_b', '蜡染博物馆 B', '探索印尼蜡染艺术。', 30000.00),
                        ('handicraft_c', '手工艺中心 C', '购买传统手工艺品。', 20000.00)
                    ]
                    # Update insert query for new columns
                    insert_query = """
                        INSERT INTO attractions (attraction_id, name, description, price)
                        VALUES (%s, %s, %s, %s);
                    """
                    cur.executemany(insert_query, sample_attractions)
                    print(f"已添加 {cur.rowcount} 个示例景点。")
                # --- 示例数据添加结束 ---

            # Transaction is committed automatically if no exceptions occurred
            print("数据库表结构初始化/检查成功完成。")

    except PoolTimeout:
        print("获取数据库连接超时，无法初始化数据库。")
    except (OperationalError, DatabaseError) as error:
        print(f"数据库初始化错误: {error}")
        # Transaction is rolled back automatically on exception
    except Exception as error:
        print(f"初始化数据库时发生未知错误: {error}")


# --- API 端点 (API Endpoints) ---

@app.route('/api/attractions', methods=['GET'])
def get_attractions():
    """获取所有景点信息的 API"""
    if not pool:
         return jsonify({"message": "数据库服务暂时不可用"}), 503

    try:
        with pool.connection(timeout=5.0) as conn:
            with conn.cursor() as cur:
                # Select all necessary fields from attractions table
                cur.execute("SELECT attraction_id, name, description, price FROM attractions ORDER BY name;")
                attractions = cur.fetchall() # fetchall() returns a list of dictionaries due to dict_row
                # Convert price from Decimal to float for JSON serialization if necessary
                # (jsonify might handle Decimal, but explicit conversion is safer)
                for attraction in attractions:
                    if 'price' in attraction and attraction['price'] is not None:
                        attraction['price'] = float(attraction['price'])
                return jsonify(attractions), 200
    except PoolTimeout:
         print("获取景点列表时连接超时")
         return jsonify({"message": "数据库请求超时，请稍后重试"}), 504
    except (OperationalError, DatabaseError) as error:
        print(f"查询景点列表时出错: {error}")
        return jsonify({"message": "获取景点信息时发生数据库错误"}), 500
    except Exception as error:
        print(f"获取景点列表时发生未知错误: {error}")
        return jsonify({"message": "获取景点信息时发生内部错误"}), 500


@app.route('/api/purchase', methods=['POST'])
def handle_purchase():
    """处理购票请求 API - 使用连接池"""
    if not pool:
         return jsonify({"message": "数据库服务暂时不可用"}), 503

    if not request.is_json:
        return jsonify({"message": "请求必须是 JSON 格式"}), 400

    data = request.get_json()

    # --- 输入验证 (Input Validation) ---
    required_fields = ["attraction_id", "quantity", "ticket_type", "total_price", "purchase_time"]
    if not all(field in data for field in required_fields):
        missing = [field for field in required_fields if field not in data]
        return jsonify({"message": f"缺少必要的字段: {', '.join(missing)}"}), 400
    # Add more specific validation as needed
    try:
        quantity = int(data["quantity"])
        total_price = float(data["total_price"])
        if quantity < 1:
            raise ValueError("数量必须是正整数")
        if total_price < 0:
             raise ValueError("总价必须是非负数")
        # Validate attraction_id format if needed
        # Validate ticket_type if there are specific allowed types
        # Validate purchase_time format (ISO 8601 expected by PostgreSQL)
        from datetime import datetime
        datetime.fromisoformat(data["purchase_time"].replace('Z', '+00:00'))

    except (ValueError, TypeError) as ve:
         return jsonify({"message": f"输入数据无效: {ve}"}), 400
    except Exception as e: # Catch potential date parsing errors
         return jsonify({"message": f"输入数据格式错误: {e}"}), 400


    order_id = str(uuid.uuid4()) # Generate unique order ID

    try:
        with pool.connection(timeout=5.0) as conn:
            with conn.cursor() as cur:
                # Optional: Verify attraction_id exists and maybe fetch price server-side
                # cur.execute("SELECT price FROM attractions WHERE attraction_id = %s", (data["attraction_id"],))
                # attraction_info = cur.fetchone()
                # if not attraction_info:
                #     return jsonify({"message": f"无效的景点 ID: {data['attraction_id']}"}), 404
                # server_price = float(attraction_info['price'])
                # server_total = server_price * quantity
                # # Compare server_total with data['total_price'] for consistency check if desired

                # 1. 插入订单主表 (orders)
                sql_order = """
                    INSERT INTO orders (order_id, purchase_time, total_amount, status)
                    VALUES (%s, %s, %s, %s);
                """
                purchase_time_dt = data["purchase_time"]
                order_status = 'completed'
                cur.execute(sql_order, (order_id, purchase_time_dt, total_price, order_status))
                print(f"订单 {order_id} 插入 orders 表成功。")

                # 2. 插入订单项表 (order_items)
                sql_item = """
                    INSERT INTO order_items (order_id, attraction_id, ticket_type, quantity, price_per_ticket)
                    VALUES (%s, %s, %s, %s, %s);
                """
                attraction_id = data["attraction_id"]
                ticket_type = data["ticket_type"]
                # Calculate unit price server-side for consistency
                price_per_ticket = total_price / quantity if quantity > 0 else 0
                cur.execute(sql_item, (order_id, attraction_id, ticket_type, quantity, price_per_ticket))
                print(f"订单项 (景点: {attraction_id}) 插入 order_items 表成功。")

            # Transaction committed automatically

        return jsonify({
            "message": "购买记录成功",
            "order_id": order_id
        }), 201

    except PoolTimeout:
         print(f"处理订单 {order_id} 时获取数据库连接超时")
         return jsonify({"message": "数据库请求超时，请稍后重试"}), 504
    except (OperationalError, DatabaseError) as error:
        print(f"数据库操作错误 (订单 {order_id}): {error}")
        # Check for specific constraint violations, e.g., UNIQUE constraint
        # if "unique constraint" in str(error).lower():
        #     return jsonify({"message": "处理请求时发生唯一性冲突错误"}), 409 # Conflict
        return jsonify({"message": "处理购买请求时发生数据库错误"}), 500
    except Exception as error:
        print(f"处理购买请求时发生未知错误 (订单 {order_id}): {error}")
        return jsonify({"message": "处理购买请求时发生内部错误"}), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取销售统计数据 API - 包含景点名称"""
    if not pool:
         return jsonify({"message": "数据库服务暂时不可用"}), 503

    try:
        with pool.connection(timeout=5.0) as conn:
            with conn.cursor() as cur:
                # 查询总票数
                cur.execute("SELECT COALESCE(SUM(quantity), 0) AS total_tickets FROM order_items;")
                total_tickets_result = cur.fetchone()
                total_tickets = total_tickets_result['total_tickets'] # Already an integer or 0

                # 查询每个景点的售票数，并连接 attractions 表获取名称
                cur.execute("""
                    SELECT
                        oi.attraction_id,
                        COALESCE(a.name, oi.attraction_id) AS name, -- Fallback to ID if name is missing
                        SUM(oi.quantity) AS count
                    FROM order_items oi
                    LEFT JOIN attractions a ON oi.attraction_id = a.attraction_id
                    GROUP BY oi.attraction_id, a.name
                    ORDER BY count DESC, name;
                """)
                attraction_results = cur.fetchall() # List of dictionaries

        # Format the results for the frontend
        tickets_by_attraction = [
            {'id': row['attraction_id'], 'name': row['name'], 'count': int(row['count'])}
            for row in attraction_results
        ]

        return jsonify({
            "total_tickets": total_tickets,
            "tickets_by_attraction": tickets_by_attraction # Return list of objects
        }), 200

    except PoolTimeout:
         print("获取统计数据时获取数据库连接超时")
         return jsonify({"message": "数据库请求超时，请稍后重试"}), 504
    except (OperationalError, DatabaseError) as error:
        print(f"查询统计数据时出错: {error}")
        return jsonify({"message": "获取统计数据时发生数据库错误"}), 500
    except Exception as error:
        print(f"获取统计数据时发生未知错误: {error}")
        return jsonify({"message": "获取统计数据时发生内部错误"}), 500


# --- 应用启动入口 (Application Entry Point) ---
if __name__ == '__main__':
    # Ensure pool is initialized before running init_db
    if pool is None:
        print("错误：数据库连接池未成功初始化，无法继续。请检查数据库配置和连接。")
        exit(1)

    print("正在初始化数据库...")
    init_db()
    print("数据库初始化流程完成。") # Check logs above for success/failure

    print("启动 Flask 应用...")
    # Use debug=False in production and run with a proper WSGI server like Gunicorn
    app.run(host='0.0.0.0', port=5000, debug=True)

