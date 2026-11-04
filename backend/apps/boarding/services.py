"""Validation d'embarquement : décision côté serveur, atomique, idempotente et auditée."""
from django.db import IntegrityError, transaction

from apps.audit import service as audit
from apps.ticketing import qr
from apps.ticketing.models import Ticket, TicketStatus
from apps.trips.models import Trip, TripStatus

from .models import BoardingEvent, ScanResult

# Message compréhensible par un agent non technique + couleur d'affichage.
RESULT_INFO = {
    ScanResult.VALIDATED: ("green", "Embarquement validé."),
    ScanResult.ALREADY_BOARDED: ("red", "Ce billet a déjà été utilisé : passager déjà embarqué."),
    ScanResult.INVALID: ("red", "Billet invalide : ce QR Code est inconnu ou a été modifié."),
    ScanResult.CANCELLED: ("orange", "Ce billet a été annulé. Ne pas embarquer."),
    ScanResult.WRONG_TRIP: ("orange", "Ce billet est valable pour un autre voyage."),
    ScanResult.TRIP_CLOSED: ("orange", "L'embarquement de ce voyage est clôturé."),
    ScanResult.NOT_ELIGIBLE: ("orange", "L'embarquement n'est pas encore ouvert pour ce voyage."),
}


def _response(result, ticket=None, event=None, replay=False):
    color, message = RESULT_INFO[result]
    out = {"result": result, "color": color, "message": message, "replay": replay}
    if ticket is not None and result in (ScanResult.VALIDATED, ScanResult.ALREADY_BOARDED, ScanResult.CANCELLED):
        out["ticket"] = {
            "reference": ticket.reference,
            "passenger": ticket.passenger.full_name,
            "seat": ticket.seat.code if ticket.seat else None,
        }
    if event is not None:
        out["event_id"] = event.id
    return out


def _record(tenant, trip, ticket, agent, device, result, key):
    return BoardingEvent.objects.create(
        tenant=tenant, trip=trip, ticket=ticket, agent=agent, device=(device or "")[:80],
        result=result, idempotency_key=key or "",
    )


def scan(*, tenant, agent, trip_id, code, device="", idempotency_key="", agency_scope_id=None):
    """`code` : contenu du QR (jeton signé) ou référence saisie à la main (secours)."""
    key = (idempotency_key or "")[:64]
    if key:  # rejeu d'une requête déjà traitée (réseau instable) : même réponse, aucun nouvel effet
        prev = BoardingEvent.objects.filter(tenant=tenant, idempotency_key=key).select_related("ticket__passenger", "ticket__seat").first()
        if prev:
            return _response(prev.result, prev.ticket, prev, replay=True)

    trip = Trip.objects.filter(pk=trip_id, tenant=tenant).first()
    if trip is None or (agency_scope_id and trip.agency_id != agency_scope_id):
        return None  # la vue renvoie 404

    code = (code or "").strip()
    token = qr.parse_payload(code)
    lookup = _find_by_token(tenant, token) if token else None
    if lookup is None and code and "." not in code:
        lookup = Ticket.objects.filter(tenant=tenant, reference=code.upper()).first()  # saisie manuelle

    try:
        with transaction.atomic():
            ticket = None
            if lookup is not None:
                # Verrou de ligne : deux scans concurrents du même billet sont sérialisés.
                # of=("self",) : PostgreSQL refuse FOR UPDATE sur la jointure externe (siège facultatif).
                ticket = (Ticket.objects.select_for_update(of=("self",))
                          .select_related("passenger", "seat").get(pk=lookup.pk))
            if ticket is None:
                result = ScanResult.INVALID
            elif trip.status in (TripStatus.CLOSED, TripStatus.COMPLETED):
                result = ScanResult.TRIP_CLOSED
            elif ticket.trip_id != trip.id:
                result = ScanResult.WRONG_TRIP
            elif ticket.status == TicketStatus.CANCELLED:
                result = ScanResult.CANCELLED
            elif trip.status != TripStatus.BOARDING:
                result = ScanResult.NOT_ELIGIBLE
            elif BoardingEvent.objects.filter(ticket=ticket, result=ScanResult.VALIDATED).exists():
                result = ScanResult.ALREADY_BOARDED
            else:
                result = ScanResult.VALIDATED
            event = _record(tenant, trip, ticket, agent, device, result, key)
    except IntegrityError:
        # Course perdue : la contrainte d'unicité a bloqué le second embarquement validé.
        with transaction.atomic():
            ticket = Ticket.objects.select_related("passenger", "seat").filter(pk=lookup.pk).first() if lookup else None
            event = _record(tenant, trip, ticket, agent, device, ScanResult.ALREADY_BOARDED, "")
        result = ScanResult.ALREADY_BOARDED

    audit.log(f"boarding.{result.lower()}", actor=agent, tenant=tenant, entity="Trip", entity_id=trip.id,
              ticket_ref=ticket.reference if ticket else None, device=device[:40] if device else "")
    return _response(result, ticket, event)


def _find_by_token(tenant, token):
    return Ticket.objects.filter(tenant=tenant, public_token=token).first()
