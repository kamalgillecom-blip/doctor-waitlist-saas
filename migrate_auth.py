import sqlite3
import hashlib

import config

def get_db():
    return sqlite3.connect(config.DATABASE_PATH)

def migrate():
    conn = get_db()
    cursor = conn.cursor()
    
    print("Checking for users table...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
    if not cursor.fetchone():
        print("Creating users table...")
        cursor.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("Users table created.")
    else:
        print("Users table already exists. Checking schema...")
        cursor.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'email' not in columns:
            print("Adding email column...")
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
                cursor.execute("CREATE UNIQUE INDEX idx_users_email ON users (email)")
            except Exception as e:
                print(f"Error adding email: {e}")

        if 'password_hash' not in columns:
            print("Adding password_hash column...")
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            except Exception as e:
                print(f"Error adding password_hash: {e}")

        if 'name' not in columns:
            print("Adding name column...")
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN name TEXT")
            except Exception as e:
                print(f"Error adding name: {e}")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    migrate()
