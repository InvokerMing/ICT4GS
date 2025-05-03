from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid
import os
from dotenv import load_dotenv
import psycopg
from psycopg import OperationalError, InterfaceError, DatabaseError
from psycopg_pool import ConnectionPool, PoolTimeout

# --- 数据库配置 (Database Configuration) ---
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL', None)

# --- 初始化数据库连接池 (Initialize Database Connection Pool) ---
pool = None
if DATABASE_URL is None:
    print("错误：未找到 DATABASE_URL 环境变量。请确保 .env 文件存在且包含 DATABASE_URL。")
    exit(1)
else:
    try:
        pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=5,
            # 可以添加 kwargs 来传递额外的 psycopg 连接参数
            # kwargs={'options': '-c timezone=UTC'}
            # 可以添加 configure 回调来设置新连接
            # configure=configure_connection,
            # 可以添加 check 回调来检查获取的连接
            # check=ConnectionPool.check_connection,
            timeout=10.0 # 获取连接的默认超时时间 (Default timeout for getting a connection)
        )
        # 检查连接池状态 (可选, 可以等待池准备好)
        # pool.wait() # 等待直到 min_size 连接可用，或超时
        print("数据库连接池创建成功。")
    except OperationalError as e:
        print(f"数据库连接失败: {e}")
        pool = None # 确保 pool 仍然是 None
    except Exception as e:
        print(f"初始化连接池时发生其他错误: {e}")
        pool = None # 确保 pool 仍然是 None

# --- Flask 应用设置 (Flask App Setup) ---
app = Flask(__name__)
CORS(app)

# --- 数据库初始化函数 (Database Initialization Function) ---
def init_db():
    """初始化数据库表结构和示例数据 (Initializes database table structure and sample data)"""
    if not pool:
        print("数据库连接池不可用，无法初始化数据库。")
        return

    # 使用 'pool.connection()' 上下文管理器获取连接
    # 它会自动处理连接的获取和释放，以及事务
    try:
        with pool.connection() as conn:
            # conn.autocommit 默认为 False，适合事务操作
            with conn.cursor() as cur:
                print("开始初始化数据库表...")
                # 创建 attractions 表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS attractions (
                        attraction_id VARCHAR(50) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
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
                        attraction_id VARCHAR(50) NOT NULL,
                        ticket_type VARCHAR(50) NOT NULL,
                        quantity INTEGER NOT NULL CHECK (quantity > 0),
                        price_per_ticket NUMERIC(10, 2) NOT NULL,
                        UNIQUE (order_id, attraction_id, ticket_type)
                    );
                """)
                print("检查/创建 order_items 表完成。")

                # --- 添加示例景点数据 (如果 attractions 表为空) ---
                cur.execute("SELECT COUNT(*) FROM attractions;")
                attraction_count_result = cur.fetchone()
                attraction_count = attraction_count_result[0] if attraction_count_result else 0

                if attraction_count == 0:
                    print("Attractions 表为空，正在添加示例数据...")
                    sample_attractions = [
                        ('palace_a', '苏丹宫殿 A'),
                        ('museum_b', '蜡染博物馆 B'),
                        ('handicraft_c', '手工艺中心 C')
                    ]
                    insert_query = "INSERT INTO attractions (attraction_id, name) VALUES (%s, %s);"
                    # executemany 用于批量插入
                    cur.executemany(insert_query, sample_attractions)
                    print(f"已添加 {cur.rowcount} 个示例景点。") # cur.rowcount 显示影响的行数
                # --- 示例数据添加结束 ---

            # 上下文管理器退出时，如果没有异常，事务会自动提交 (conn.commit())
            print("数据库表结构初始化/检查成功完成。")

    except PoolTimeout:
        print("获取数据库连接超时，无法初始化数据库。")
    except (OperationalError, DatabaseError) as error:
        print(f"数据库初始化错误: {error}")
        # 上下文管理器退出时，如果发生异常，事务会自动回滚 (conn.rollback())
    except Exception as error:
        print(f"初始化数据库时发生未知错误: {error}")


# --- API 端点 (API Endpoints) ---

@app.route('/api/purchase', methods=['POST'])
def handle_purchase():
    """处理购票请求 API - 使用连接池"""
    if not pool:
         return jsonify({"message": "数据库服务暂时不可用"}), 503 # Service Unavailable

    if not request.is_json:
        return jsonify({"message": "请求必须是 JSON 格式"}), 400

    data = request.get_json()

    # --- 输入验证 (Input Validation) ---
    required_fields = ["attraction_id", "quantity", "ticket_type", "total_price", "purchase_time"]
    if not all(field in data for field in required_fields):
        missing = [field for field in required_fields if field not in data]
        return jsonify({"message": f"缺少必要的字段: {', '.join(missing)}"}), 400
    if not isinstance(data.get("quantity"), int) or data["quantity"] < 1:
         return jsonify({"message": "数量 (quantity) 必须是正整数"}), 400
    if not isinstance(data.get("attraction_id"), str) or not data["attraction_id"]:
         return jsonify({"message": "景点ID (attraction_id) 不能为空字符串"}), 400
    if not isinstance(data.get("total_price"), (int, float)) or data["total_price"] < 0:
         return jsonify({"message": "总价 (total_price) 必须是有效的非负数字"}), 400
    if not isinstance(data.get("ticket_type"), str) or not data["ticket_type"]:
         return jsonify({"message": "票种 (ticket_type) 不能为空字符串"}), 400
    # 可以添加对 purchase_time 格式的验证
    # try:
    #     datetime.fromisoformat(data["purchase_time"].replace('Z', '+00:00'))
    # except (ValueError, TypeError):
    #      return jsonify({"message": "购买时间 (purchase_time) 格式无效"}), 400

    order_id = str(uuid.uuid4()) # 生成唯一的订单 ID

    try:
        # 使用 'pool.connection()' 上下文管理器
        with pool.connection(timeout=5.0) as conn: # 可以覆盖默认超时
            with conn.cursor() as cur:
                # 1. 插入订单主表 (orders)
                sql_order = """
                    INSERT INTO orders (order_id, purchase_time, total_amount, status)
                    VALUES (%s, %s, %s, %s);
                """
                purchase_time_dt = data["purchase_time"] # PostgreSQL 通常能解析 ISO 8601
                total_price = data["total_price"]
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
                quantity = data["quantity"]
                # 计算单价 (Calculate unit price)
                price_per_ticket = total_price / quantity if quantity > 0 else 0

                cur.execute(sql_item, (order_id, attraction_id, ticket_type, quantity, price_per_ticket))
                print(f"订单项 (景点: {attraction_id}) 插入 order_items 表成功。")

            # 事务在 with 代码块成功结束时自动提交

        # 返回成功响应
        return jsonify({
            "message": "购买记录成功",
            "order_id": order_id
        }), 201

    except PoolTimeout:
         print(f"处理订单 {order_id} 时获取数据库连接超时")
         return jsonify({"message": "数据库请求超时，请稍后重试"}), 504 # Gateway Timeout
    except (OperationalError, DatabaseError) as error:
        # 事务在发生异常时自动回滚
        print(f"数据库操作错误 (订单 {order_id}): {error}")
        # 可以根据错误类型返回更具体的错误信息，但避免暴露过多细节
        return jsonify({"message": "处理购买请求时发生数据库错误"}), 500
    except Exception as error:
        # 捕获其他可能的错误
        print(f"处理购买请求时发生未知错误 (订单 {order_id}): {error}")
        return jsonify({"message": "处理购买请求时发生内部错误"}), 500
    # finally 块不再需要手动关闭 cur 或释放 conn，上下文管理器会处理


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取销售统计数据 API - 使用连接池"""
    if not pool:
         return jsonify({"message": "数据库服务暂时不可用"}), 503

    try:
        # 使用 'pool.connection()' 上下文管理器
        with pool.connection(timeout=5.0) as conn:
            # 使用只读事务可能更合适，如果数据库支持
            # conn.read_only = True
            with conn.cursor() as cur:
                # 查询总票数
                cur.execute("SELECT SUM(quantity) FROM order_items;")
                total_tickets_result = cur.fetchone()
                # 处理可能为 None 的结果 (当表为空时)
                total_tickets = int(total_tickets_result[0]) if total_tickets_result and total_tickets_result[0] is not None else 0

                # 查询每个景点的售票数
                cur.execute("""
                    SELECT attraction_id, SUM(quantity) as count
                    FROM order_items
                    GROUP BY attraction_id;
                """)
                attraction_results = cur.fetchall()
                # 将结果转换为字典
                tickets_by_attraction = {row[0]: int(row[1]) for row in attraction_results}

        # 返回统计结果
        return jsonify({
            "total_tickets": total_tickets,
            "tickets_by_attraction": tickets_by_attraction
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
    # finally 块不再需要手动关闭 cur 或释放 conn


# --- 应用启动入口 (Application Entry Point) ---
if __name__ == '__main__':
    print("正在初始化数据库...")
    init_db()
    print("数据库初始化流程完成。") # 不保证一定成功，检查前面的日志

    if pool is None:
        print("错误：数据库连接池未成功初始化，应用无法启动。请检查数据库配置和连接。")
        exit(1) # 如果数据库是必须的，则退出

    print("启动 Flask 应用...")
    # 运行在 0.0.0.0 上允许外部访问 (开发时方便)
    # 生产环境应关闭 debug=True，并使用生产级 WSGI 服务器（如 Gunicorn, uWSGI）
    app.run(host='0.0.0.0', port=5000, debug=True)
