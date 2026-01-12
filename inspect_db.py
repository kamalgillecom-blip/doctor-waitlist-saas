import sqlite3

conn = sqlite3.connect('waitlist.db')
cursor = conn.cursor()

# Get all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print("Tables:", [t[0] for t in tables])

# Get schema for each table
for table in tables:
    print(f"\nSchema for {table[0]}:")
    cursor.execute(f"PRAGMA table_info({table[0]})")
    columns = cursor.fetchall()
    for col in columns:
        print(col)

conn.close()
