from app.db.database import get_connection


def create_reservation(
    guest_name,
    email,
    room_type,
    check_in_date,
    check_out_date
):

    conn = get_connection()

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

    reservation_id = cursor.lastrowid

    conn.close()

    return reservation_id


def get_reservation(reservation_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
    SELECT * FROM reservations
    WHERE reservation_id = ?
    """, (reservation_id,))

    reservation = cursor.fetchone()

    conn.close()

    return reservation


def get_reservations_by_email(email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM reservations
    WHERE LOWER(email) = LOWER(?)
    ORDER BY reservation_id
    """, (email,))
    reservations = cursor.fetchall()
    conn.close()
    return [dict(r) for r in reservations]


def cancel_reservation(reservation_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
    UPDATE reservations
    SET status = 'CANCELLED'
    WHERE reservation_id = ?
    """, (reservation_id,))

    conn.commit()

    found = cursor.rowcount > 0

    conn.close()

    return found