from pydantic import BaseModel
from typing import Optional


class IntentOutput(BaseModel):

    intent: str


class ReservationIDOutput(BaseModel):

    reservation_id: Optional[int] = None
    email: Optional[str] = None