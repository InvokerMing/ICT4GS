import os
from psycopg import OperationalError, DatabaseError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL', None)

TABLES_TO_DROP = [
    "individual_tickets",
    "order_items",
    "orders",
    "attractions",
    "users"
]

TRIGGERS_TO_DROP = [
    {"trigger": "update_individual_ticket_updated_at", "table": "individual_tickets"}
]

FUNCTIONS_TO_DROP = [
    "update_individual_ticket_updated_at_column"
]

def reset_database():
    if not DATABASE_URL:
        print("Error: DATABASE_URL environment variable not found. Cannot reset database.")
        return

    try:
        pool = ConnectionPool(
            conninfo=DATABASE_URL, min_size=1, max_size=1, timeout=10.0,
            kwargs={'row_factory': dict_row}
        )
        print("Successfully connected to the database.")

        with pool.connection() as conn, conn.cursor() as cur:
            print("Dropping triggers...")
            for trigger_info in TRIGGERS_TO_DROP:
                try:
                    drop_command = f"DROP TRIGGER IF EXISTS {trigger_info['trigger']} ON {trigger_info['table']};"
                    cur.execute(drop_command)
                    print(f" - Trigger '{trigger_info['trigger']}' dropped successfully (if it existed).")
                except Exception as err:
                    print(f" ! Error dropping trigger '{trigger_info['trigger']}': {err}")

            print("Dropping tables...")
            for table_name in TABLES_TO_DROP:
                try:
                    drop_command = f"DROP TABLE IF EXISTS {table_name} CASCADE;"
                    cur.execute(drop_command)
                    print(f" - Table '{table_name}' dropped successfully (if it existed).")
                except Exception as err:
                    print(f" ! Error dropping table '{table_name}': {err}")

            print("Dropping functions...")
            for function_name in FUNCTIONS_TO_DROP:
                try:
                    drop_command = f"DROP FUNCTION IF EXISTS {function_name}();"
                    cur.execute(drop_command)
                    print(f" - Function '{function_name}' dropped successfully (if it existed).")
                except Exception as err:
                    print(f" ! Error dropping function '{function_name}': {err}")

            print("Database reset process completed.")
        
        pool.close()
        print("Database connection closed.")

    except OperationalError as e:
        print(f"Database connection error: {e}")
    except DatabaseError as e:
        print(f"Database operation error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    confirm = input("WARNING: This will delete all ticketing system tables, triggers, and functions.\nAre you sure you want to continue? (yes/no): ")
    if confirm.lower() == 'yes':
        print("Proceeding with database reset...")
        reset_database()
        print("Database reset script finished.")
        print("You may need to restart the Flask application to re-initialize the tables and default data.")
    else:
        print("Database reset cancelled.")

