"""Mock booking: confirms the chosen flight and hotel with fake confirmation codes.

Real booking APIs need payment and commercial approval, so this only shows where booking
fits in the graph. The graph only reaches this node after approval; the check below is a
second safety net.
"""

import secrets
import uuid
from datetime import datetime

from trippilot.schemas import BookingConfirmation, Money
from trippilot.state import TripState


def booking(state: TripState) -> dict:
    if state.get("approval") != "approved":  # never book without approval
        return {"errors": ["booking: refused, the plan was not approved"]}

    bookings = []
    flight = state.get("selected_flight")
    if flight:
        bookings.append(_confirm("flight", flight.id, flight.price))
    hotel = state.get("selected_hotel")
    if hotel:
        bookings.append(_confirm("hotel", hotel.id, hotel.total_price))
    return {"bookings": bookings}


def _confirm(kind: str, item_id: str, amount: Money) -> BookingConfirmation:
    return BookingConfirmation(
        booking_id=str(uuid.uuid4()),
        kind=kind,
        item_id=item_id,
        status="confirmed",
        confirmation_code=secrets.token_hex(3).upper(),  # e.g. "4F9A1C"
        amount=amount,
        created_at=datetime.now(),
    )
