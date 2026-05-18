from app.db.database import get_connection


def create_tables():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reservations (

        reservation_id INTEGER PRIMARY KEY AUTOINCREMENT,

        guest_name TEXT NOT NULL,

        email TEXT NOT NULL,

        room_type TEXT NOT NULL,

        check_in_date TEXT NOT NULL,

        check_out_date TEXT NOT NULL,

        status TEXT DEFAULT 'CONFIRMED',

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS escalations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        guest_email TEXT,
        query TEXT NOT NULL,
        status TEXT DEFAULT 'PENDING',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()

    conn.close()