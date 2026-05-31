import app

try:
    conn = app.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME")
    tables = cursor.fetchall()
    print('Database tables:')
    for table in tables:
        print(f'  - {table[0]}')
    conn.close()
except Exception as e:
    print(f'Database error: {e}')