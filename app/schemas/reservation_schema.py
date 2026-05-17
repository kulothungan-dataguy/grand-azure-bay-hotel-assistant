from pydantic import (
    BaseModel,
    EmailStr
)

from datetime import date


class ReservationData(BaseModel):

    guest_name: str

    email: EmailStr

    room_type: str

    check_in_date: date

    check_out_date: date