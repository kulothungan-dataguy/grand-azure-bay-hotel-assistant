from app.db.operations import (
    create_reservation,
    get_reservation,
    get_reservations_by_email,
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
    if reservation_id is None and requester_email:
        reservations = get_reservations_by_email(requester_email)
        if not reservations:
            return "No reservations found for that email."
        lines = []
        for r in reservations:
            status_icon = "✅" if r["status"] == "CONFIRMED" else "❌"
            lines.append(
                f"**Reservation #{r['reservation_id']}**\n"
                f"- Room: {r['room_type']}\n"
                f"- Check-in: {r['check_in_date']}\n"
                f"- Check-out: {r['check_out_date']}\n"
                f"- Status: {status_icon} {r['status']}"
            )
        return {"reservation_list": reservations, "summary": "\n\n".join(lines)}

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