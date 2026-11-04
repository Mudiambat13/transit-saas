"""Règles métier de la billetterie : toutes les écritures sensibles sont atomiques."""
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.accounts.exceptions import BusinessError
from apps.audit import service as audit
from apps.fleet.models import Seat
from apps.trips.models import Trip
from apps.trips.services import SELLABLE

from . import qr
from .models import Passenger, PaymentRecord, Ticket, TicketCancellation, TicketStatus

PAYMENT_METHODS = {"CASH", "MOBILE_MONEY", "CARD", "BANK", "OTHER"}


def _validate_passenger(tenant, data):
    name = (data.get("full_name") or "").strip()
    if len(name) < 2:
        raise BusinessError("Le nom complet du passager est obligatoire.", code="passenger_name_required", status_code=400)
    phone = (data.get("phone") or "").strip()
    if tenant.setting("passenger_phone_required", False) and not phone:
        raise BusinessError("Le téléphone du passager est obligatoire pour cette compagnie.", code="passenger_phone_required", status_code=400)
    return {
        "full_name": name, "phone": phone,
        "id_type": (data.get("id_type") or "").strip(), "id_number": (data.get("id_number") or "").strip(),
        "extra_info": (data.get("extra_info") or "").strip(),
    }


@transaction.atomic
def create_ticket(*, tenant, actor, trip_id, passenger, seat_id=None, price=None, payment=None, agency_scope_id=None):
    """Vend un billet : verrou sur le voyage, contrôle de capacité et de siège, création atomique."""
    from apps.accounts.permissions import has_perm  # noqa: F401  (import local pour éviter les cycles)

    trip = Trip.objects.select_for_update().filter(pk=trip_id, tenant=tenant).first()
    if trip is None or (agency_scope_id and trip.agency_id != agency_scope_id):
        raise BusinessError("Voyage introuvable.", code="trip_not_found", status_code=404)
    if trip.status not in SELLABLE:
        raise BusinessError("Ce voyage n'est pas ouvert à la vente.", code="trip_not_sellable")

    pdata = _validate_passenger(tenant, passenger)

    active = Ticket.objects.filter(trip=trip, status=TicketStatus.ACTIVE)
    if active.count() >= trip.capacity:
        raise BusinessError("Le voyage est complet : plus aucune place disponible.", code="trip_full")

    seat = None
    if seat_id:
        seat = Seat.objects.filter(pk=seat_id, bus_id=trip.bus_id).first()
        if seat is None:
            raise BusinessError("Ce siège n'appartient pas au bus du voyage.", code="seat_invalid", status_code=400)
        if active.filter(seat=seat).exists():
            raise BusinessError("Ce siège est déjà vendu.", code="seat_taken")
    elif tenant.setting("seat_selection", True):
        taken = active.exclude(seat__isnull=True).values_list("seat_id", flat=True)
        seat = trip.bus.seats.exclude(id__in=list(taken)).order_by("id").first()
        if seat is None:
            raise BusinessError("Aucun siège libre sur ce bus.", code="trip_full")

    amount = Decimal(str(price)) if price not in (None, "") else trip.price
    if amount < 0:
        raise BusinessError("Le prix ne peut pas être négatif.", code="price_invalid", status_code=400)

    pay = payment or {}
    method = (pay.get("method") or "CASH").upper()
    if method not in PAYMENT_METHODS:
        raise BusinessError("Mode de paiement inconnu.", code="payment_method_invalid", status_code=400)

    pax = Passenger.objects.create(tenant=tenant, **pdata)
    ticket = None
    for _ in range(5):  # collisions de référence : quasi impossibles, mais gérées
        try:
            with transaction.atomic():
                ticket = Ticket.objects.create(
                    tenant=tenant, trip=trip, passenger=pax, seat=seat, price=amount, currency=trip.currency,
                    reference=qr.new_reference(), public_token=qr.new_token(), created_by=actor,
                )
            break
        except IntegrityError as exc:
            if "uniq_active_seat_per_trip" in str(exc) or (seat and "seat" in str(exc).lower()):
                raise BusinessError("Ce siège vient d'être vendu à un autre passager.", code="seat_taken")
            continue
    if ticket is None:
        raise BusinessError("Impossible de générer une référence de billet, réessayez.", code="reference_failed", status_code=500)

    PaymentRecord.objects.create(ticket=ticket, amount=amount, method=method, reference=(pay.get("reference") or "")[:60])
    audit.log("ticket.created", actor=actor, tenant=tenant, entity="Ticket", entity_id=ticket.id,
              trip=trip.reference, ref=ticket.reference, seat=seat.code if seat else None)
    return ticket


@transaction.atomic
def cancel_ticket(*, tenant, actor, ticket_id, reason, agency_scope_id=None):
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise BusinessError("Le motif d'annulation est obligatoire.", code="reason_required", status_code=400)
    ticket = Ticket.objects.select_for_update(of=("self",)).select_related("trip").filter(pk=ticket_id, tenant=tenant).first()
    if ticket is None or (agency_scope_id and ticket.trip.agency_id != agency_scope_id):
        raise BusinessError("Billet introuvable.", code="ticket_not_found", status_code=404)
    if ticket.status == TicketStatus.CANCELLED:
        raise BusinessError("Ce billet est déjà annulé.", code="already_cancelled")
    if ticket.trip.status in ("CLOSED", "COMPLETED"):
        raise BusinessError("Le voyage est clôturé : annulation impossible sans réouverture.", code="trip_closed")
    if ticket.boarding_events.filter(result="VALIDATED").exists():
        raise BusinessError("Ce passager est déjà embarqué : annulation impossible.", code="already_boarded")
    ticket.status = TicketStatus.CANCELLED
    ticket.save(update_fields=["status"])
    TicketCancellation.objects.create(ticket=ticket, reason=reason[:255], cancelled_by=actor)
    audit.log("ticket.cancelled", actor=actor, tenant=tenant, entity="Ticket", entity_id=ticket.id,
              ref=ticket.reference, reason=reason[:255])
    return ticket
