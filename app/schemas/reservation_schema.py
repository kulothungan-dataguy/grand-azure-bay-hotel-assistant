from pydantic import BaseModel
from datetime import date
from typing import Optional


class ReservationData(BaseModel):

    guest_name: Optional[str] = None
    email: Optional[str] = None
    room_type: Optional[str] = None
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None