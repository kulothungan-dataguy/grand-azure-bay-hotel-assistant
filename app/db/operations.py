from app.db.database import get_connection


def create_reservation(
    guest_name: str,
    email: str,
    room_type: str,
    check_in_date: str,
    check_out_date: str,
) -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO reservations (
            guest_name,
            email,
            room_type,
            check_in_date,
            check_out_date
        )
        VALUES (?, ?, ?, ?, ?)
        """, (
            guest_name,
            email,
            room_type,
            str(check_in_date),
            str(check_out_date)
        ))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_reservation(reservation_id: int) -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM reservations
        WHERE reservation_id = ?
        """, (reservation_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_reservations_by_email(email: str) -> list[dict]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM reservations
        WHERE LOWER(email) = LOWER(?)
        ORDER BY reservation_id
        """, (email,))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def create_escalation(
    conversation_id: str,
    query: str,
    guest_email: str | None = None,
) -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO escalations (conversation_id, guest_email, query)
        VALUES (?, ?, ?)
        """, (conversation_id, guest_email, query))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_pending_escalations() -> list[dict]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM escalations
        WHERE status = 'PENDING'
        ORDER BY created_at DESC
        """)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def resolve_escalation(escalation_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE escalations SET status = 'RESOLVED'
        WHERE id = ?
        """, (escalation_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def cancel_reservation(reservation_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE reservations
        SET status = 'CANCELLED'
        WHERE reservation_id = ?
        """, (reservation_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
