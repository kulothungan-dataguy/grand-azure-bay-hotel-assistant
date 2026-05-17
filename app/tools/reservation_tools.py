from app.db.operations import (
    create_reservation,
    get_reservation,
    cancel_reservation
)


def create_reservation_tool(
    guest_name,
    email,
    room_type,
    check_in_date,
    check_out_date
):

    reservation_id = create_reservation(
        guest_name,
        email,
        room_type,
        check_in_date,
        check_out_date
    )

    return {
        "message": (
            f"Reservation created successfully. "
            f"Reservation ID: {reservation_id}"
        ),
        "reservation_id": reservation_id
    }


def view_reservation_tool(reservation_id, requester_email):

    reservation = get_reservation(reservation_id)

    if not reservation:
        return "Reservation not found."

    if reservation["email"].lower() != requester_email.lower():
        return "Access denied. This reservation does not belong to your email."

    return {
        "reservation_id": reservation["reservation_id"],
        "room_type": reservation["room_type"],
        "check_in_date": reservation["check_in_date"],
        "check_out_date": reservation["check_out_date"],
        "status": reservation["status"]
    }


def cancel_reservation_tool(reservation_id, requester_email):

    reservation = get_reservation(reservation_id)

    if not reservation:
        return "Reservation not found."

    if reservation["email"].lower() != requester_email.lower():
        return "Access denied. This reservation does not belong to your email."

    cancel_reservation(reservation_id)

    return f"Reservation {reservation_id} cancelled successfully."