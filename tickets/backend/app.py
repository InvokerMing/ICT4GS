from flask import Flask, request, jsonify
from flask_cors import CORS
import datetime
import uuid
from collections import Counter
import psycopg2
import psycopg2.pool
import os
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from dotenv import load_dotenv


# --- 数据库配置 ---
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL', None)
db_params = {}
if DATABASE_URL:
    try:
        # 确保密码正确编码
        parsed_url = urlparse(DATABASE_URL)
        password = parsed_url.password
        if password:
            # 对特殊字符进行 URL 解码
            from urllib.parse import unquote
            password = unquote(password)
            
        print(f"原始 DATABASE_URL: {DATABASE_URL.replace(parsed_url.password, '****') if parsed_url.password else DATABASE_URL}")
        
        db_params = {
            'database': parsed_url.path[1:],
            'user': parsed_url.username,
            'password': password,
            'host': parsed_url.hostname,
            'port': parsed_url.port or 5432,
            'client_encoding': 'UTF8',
        }
        
        # 移除所有 None 值的参数
        db_params = {k: v for k, v in db_params.items() if v is not None}
        
        debug_params = db_params.copy()
        if 'password' in debug_params:
            debug_params['password'] = '****'
        print(f"解析后的数据库参数: {debug_params}")

    except Exception as e:
        print(f"解析 DATABASE_URL 时出错: {e}")
        db_params = None
else:
    print("错误: DATABASE_URL 环境变量未设置")
    db_params = None

# --- 初始化数据库连接池 ---
try:
    pool = psycopg2.pool.SimpleConnectionPool(1, 5, **db_params)
    print("数据库连接池创建成功。")
except psycopg2.OperationalError as e:
    print(f"数据库连接失败: {e}")
    pool = None


app = Flask(__name__)
CORS(app)


def get_db_connection():
    """从连接池获取一个数据库连接"""
    if pool:
        try:
            conn = pool.getconn()
            conn.autocommit = False
            # 验证连接是否有效并设置客户端编码（双重保险）
            try:
                with conn.cursor() as cur:
                    cur.execute("SET client_encoding TO 'UTF8';")
                conn.commit() # 提交 SET 命令
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as conn_err:
                print(f"设置 client_encoding 失败或连接无效: {conn_err}")
                pool.putconn(conn, close=True)
            return conn
        except psycopg2.pool.PoolError as e:
            print(f"获取数据库连接失败: {e}")
            return None
        except Exception as e: # 捕获其他获取连接时的错误
            print(f"获取连接时发生未知错误: {e}")
            return None
    else:
        print("数据库连接池不可用。")
        return None

def release_db_connection(conn):
    """将数据库连接放回连接池"""
    if pool and conn:
        try:
            if not conn.closed and conn.status == psycopg2.extensions.STATUS_READY:
                conn.rollback() # 回滚
                pool.putconn(conn)
            else:
                # 如果连接已关闭或状态不佳，则关闭它而不是放回池中
                print("连接状态异常，将关闭而不是放回池中。")
                pool.putconn(conn, close=True)
        except (psycopg2.pool.PoolError, psycopg2.InterfaceError, Exception) as e:
            print(f"释放数据库连接失败: {e}")
            # 尝试强制关闭连接
            if conn and not conn.closed:
                try:
                    pool.putconn(conn, close=True)
                except:
                    pass # 忽略关闭时的错误


def init_db():
    """初始化数据库"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        if not conn:
            print("无法获取数据库连接以初始化数据库。")
            return

        cur = conn.cursor()

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
                total_amount NUMERIC(10, 2) NOT NULL, -- 使用 NUMERIC 存储金额更精确
                status VARCHAR(50) DEFAULT 'completed',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("检查/创建 orders 表完成。")

        # 创建 order_items 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                item_id SERIAL PRIMARY KEY, -- 自动增长的主键
                order_id VARCHAR(36) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
                attraction_id VARCHAR(50) NOT NULL, -- 暂不强制外键，允许添加未知景点，或先插入attractions表
                ticket_type VARCHAR(50) NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                price_per_ticket NUMERIC(10, 2) NOT NULL,
                -- 可以考虑添加外键: FOREIGN KEY (attraction_id) REFERENCES attractions(attraction_id)
                UNIQUE (order_id, attraction_id, ticket_type) -- 防止同一订单重复记录同类票
            );
        """)
        print("检查/创建 order_items 表完成。")

        # --- 添加示例景点数据 (如果 attractions 表为空) ---
        cur.execute("SELECT COUNT(*) FROM attractions;")
        attraction_count = cur.fetchone()[0]
        if attraction_count == 0:
            print("Attractions 表为空，正在添加示例数据...")
            sample_attractions = [
                ('palace_a', '苏丹宫殿 A'),
                ('museum_b', '蜡染博物馆 B'),
                ('handicraft_c', '手工艺中心 C')
            ]
            insert_query = "INSERT INTO attractions (attraction_id, name) VALUES (%s, %s);"
            cur.executemany(insert_query, sample_attractions)
            print(f"已添加 {len(sample_attractions)} 个示例景点。")
        # --- 示例数据添加结束 ---

        conn.commit()
        print("数据库表结构初始化/检查完成。")

    except (Exception, psycopg2.DatabaseError) as error:
        print(f"数据库初始化错误: {error}")
        if conn:
            conn.rollback() # 回滚
    finally:
        if cur:
            cur.close()
        if conn:
            release_db_connection(conn)




@app.route('/api/purchase', methods=['POST'])
def handle_purchase():
    """处理购票请求 API - 使用 PostgreSQL"""
    if not request.is_json:
        return jsonify({"message": "请求必须是 JSON 格式"}), 400

    data = request.get_json()

    required_fields = ["attraction_id", "quantity", "ticket_type", "total_price", "purchase_time"]
    if not all(field in data for field in required_fields):
        return jsonify({"message": "缺少必要的字段"}), 400
    if not isinstance(data.get("quantity"), int) or data["quantity"] < 1:
         return jsonify({"message": "数量必须是正整数"}), 400
    if not isinstance(data.get("attraction_id"), str) or not data["attraction_id"]:
         return jsonify({"message": "景点ID不能为空"}), 400
    if not isinstance(data.get("total_price"), (int, float)) or data["total_price"] < 0:
         return jsonify({"message": "总价必须是有效的数字"}), 400

    conn = None
    cur = None
    order_id = str(uuid.uuid4()) # 生成UUID作为订单号

    try:
        conn = get_db_connection()
        if not conn:
             return jsonify({"message": "数据库连接失败，请稍后重试"}), 500

        cur = conn.cursor()

        # 1. 插入订单主表 (orders)
        sql_order = """
            INSERT INTO orders (order_id, purchase_time, total_amount, status)
            VALUES (%s, %s, %s, %s);
        """
        # 将前端传来的 ISO 格式时间字符串转换为 datetime 对象或直接传递
        # PostgreSQL 通常能解析 ISO 8601 格式
        purchase_time_dt = data["purchase_time"]
        total_price = data["total_price"]
        order_status = 'completed' # 假设购买即完成

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
        # 计算单价
        price_per_ticket = total_price / quantity if quantity > 0 else 0

        cur.execute(sql_item, (order_id, attraction_id, ticket_type, quantity, price_per_ticket))
        print(f"订单项 (景点: {attraction_id}) 插入 order_items 表成功。")

        # 3. 提交事务
        conn.commit()
        print(f"订单 {order_id} 事务提交成功。")

        # 返回成功响应
        return jsonify({
            "message": "购买记录成功",
            "order_id": order_id
        }), 201

    except (Exception, psycopg2.DatabaseError) as error:
        print(f"数据库操作错误: {error}")
        if conn:
            conn.rollback() # 发生错误时回滚事务
        return jsonify({"message": f"处理购买请求时发生错误: {error}"}), 500
    finally:
        # 确保游标和连接被关闭/释放
        if cur:
            cur.close()
        if conn:
            release_db_connection(conn)


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取销售统计数据 API - 从 PostgreSQL 查询"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        if not conn:
             return jsonify({"message": "数据库连接失败，请稍后重试"}), 500

        cur = conn.cursor()

        # 查询总票数
        cur.execute("SELECT SUM(quantity) FROM order_items;")
        total_tickets_result = cur.fetchone()
        # fetchone() 返回一个元组，例如 (Decimal('10'),)，如果表为空则返回 (None,)
        total_tickets = int(total_tickets_result[0]) if total_tickets_result and total_tickets_result[0] is not None else 0

        # 查询每个景点的售票数
        cur.execute("""
            SELECT attraction_id, SUM(quantity) as count
            FROM order_items
            GROUP BY attraction_id;
        """)
        attraction_results = cur.fetchall()
        # fetchall() 返回元组列表，例如 [('palace_a', Decimal('5')), ('museum_b', Decimal('3'))]

        tickets_by_attraction = {row[0]: int(row[1]) for row in attraction_results}

        # 返回统计结果
        return jsonify({
            "total_tickets": total_tickets,
            "tickets_by_attraction": tickets_by_attraction
        }), 200

    except (Exception, psycopg2.DatabaseError) as error:
        print(f"查询统计数据时出错: {error}")
        return jsonify({"message": f"获取统计数据时发生错误: {error}"}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            release_db_connection(conn)


if __name__ == '__main__':
    print("正在初始化数据库...")
    init_db()
    print("数据库初始化完成。")

    if pool is None:
        print("错误：数据库连接池未成功初始化，应用可能无法正常工作。请检查数据库配置和连接。")
        exit(1)

    print("启动 Flask 应用...")
    # 运行在 0.0.0.0 上允许外部访问 (开发时方便)
    app.run(host='0.0.0.0', port=5000, debug=True) # 生产环境应关闭 debug
