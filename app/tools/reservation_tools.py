from datetime import date
from app.db.operations import (
    create_reservation,
    get_reservation,
    get_reservations_by_email,
    cancel_reservation
)


def _is_active(r: dict) -> bool:
    try:
        return (
            r["status"] == "CONFIRMED"
            and date.fromisoformat(str(r["check_out_date"])) >= date.today()
        )
    except (ValueError, TypeError):
        return False


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
        active = [r for r in reservations if _is_active(r)]
        if not active:
            return "You have no upcoming reservations. If you'd like to make a new booking, I'd be happy to help!"
        lines = []
        for r in active:
            lines.append(
                f"**Reservation #{r['reservation_id']}**\n"
                f"- Room: {r['room_type']}\n"
                f"- Check-in: {r['check_in_date']}\n"
                f"- Check-out: {r['check_out_date']}\n"
                f"- Status: ✅ CONFIRMED"
            )
        return {"reservation_list": active, "summary": "\n\n".join(lines)}

    reservation = get_reservation(reservation_id)
    if not reservation:
        return "Reservation not found."
    if reservation["email"].lower() != requester_email.lower():
        return "Access denied. This reservation does not belong to your email."
    status_icon = "✅" if reservation["status"] == "CONFIRMED" else "❌"
    return (
        f"**Reservation #{reservation['reservation_id']}**\n"
        f"- Room: {reservation['room_type']}\n"
        f"- Check-in: {reservation['check_in_date']}\n"
        f"- Check-out: {reservation['check_out_date']}\n"
        f"- Status: {status_icon} {reservation['status']}"
    )


def cancel_reservation_tool(reservation_id, requester_email):

    reservation = get_reservation(reservation_id)

    if not reservation:
        return "Reservation not found."

    if reservation["email"].lower() != requester_email.lower():
        return "Access denied. This reservation does not belong to your email."

    cancel_reservation(reservation_id)

    return f"Reservation {reservation_id} cancelled successfully."