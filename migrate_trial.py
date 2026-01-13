import sqlite3
import config

def get_db():
    return sqlite3.connect(config.DATABASE_PATH)

def migrate():
    conn = get_db()
    cursor = conn.cursor()
    
    print("Checking users table schema for trial features...")
    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    
    # New columns to add
    new_columns = {
        'is_verified': 'BOOLEAN DEFAULT 0',
        'verification_token': 'TEXT',
        'trial_start': 'TIMESTAMP',
        'subscription_status': "TEXT DEFAULT 'trial'",
        'stripe_customer_id': 'TEXT'
    }
    
    for col_name, col_type in new_columns.items():
        if col_name not in columns:
            print(f"Adding {col_name} column...")
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
            except Exception as e:
                print(f"Error adding {col_name}: {e}")
        else:
            print(f"Column {col_name} already exists.")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == '__main__':
    migrate()
