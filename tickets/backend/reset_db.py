import os
import psycopg
from psycopg import OperationalError
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL', None)

TABLES_TO_DROP = [
    "order_items",
    "orders",
    "attractions",
    "users"
]

def reset_database():
    if not DATABASE_URL:
        print("Error: DATABASE_URL environment variable not found. Cannot reset database.")
        return

    conn = None
    try:
        conn = psycopg.connect(DATABASE_URL)
        print("Successfully connected to the database.")

        with conn.cursor() as cur:
            print("Attempting to drop tables...")
            for table_name in TABLES_TO_DROP:
                try:
                    drop_command = f"DROP TABLE IF EXISTS {table_name} CASCADE;"
                    cur.execute(drop_command)
                    print(f" - Table '{table_name}' dropped successfully (if it existed).")
                except OperationalError as drop_err:
                    print(f" ! Error dropping table '{table_name}': {drop_err}")
                except Exception as general_err:
                    print(f" ! Unexpected error dropping table '{table_name}': {general_err}")

            print("Table dropping process completed.")
        conn.commit()

    except OperationalError as e:
        print(f"Database connection error: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    confirm = input("WARNING: This will delete all ticketing system tables (users, attractions, orders, order_items).\nAre you sure you want to continue? (yes/no): ")
    if confirm.lower() == 'yes':
        print("Proceeding with database reset...")
        reset_database()
        print("Database reset script finished.")
        print("You may need to restart the Flask application to re-initialize the tables and default data.")
    else:
        print("Database reset cancelled.")

