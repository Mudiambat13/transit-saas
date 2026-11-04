"""Règles métier du cycle de vie des voyages."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts.exceptions import BusinessError
from apps.audit import service as audit

from .models import Trip, TripStatus

DEFAULT_TRIP_DURATION = timedelta(hours=12)

ALLOWED_TRANSITIONS = {
    TripStatus.DRAFT: {TripStatus.OPEN, TripStatus.CANCELLED},
    TripStatus.OPEN: {TripStatus.BOARDING, TripStatus.SUSPENDED, TripStatus.CANCELLED},
    TripStatus.SUSPENDED: {TripStatus.OPEN, TripStatus.CANCELLED},
    TripStatus.BOARDING: {TripStatus.CLOSED},
    TripStatus.CLOSED: {TripStatus.COMPLETED, TripStatus.BOARDING},  # BOARDING = réouverture exceptionnelle
}

SELLABLE = {TripStatus.OPEN, TripStatus.BOARDING}


def trip_window(departure_at, arrival_estimated_at=None):
    end = arrival_estimated_at or (departure_at + DEFAULT_TRIP_DURATION)
    return departure_at, end


def find_bus_conflict(tenant, bus, departure_at, arrival_estimated_at=None, exclude_trip_id=None):
    start, end = trip_window(departure_at, arrival_estimated_at)
    qs = Trip.objects.filter(
        tenant=tenant, bus=bus,
        departure_at__lt=end + timedelta(days=3), departure_at__gt=start - timedelta(days=3),
    ).exclude(status__in=[TripStatus.CANCELLED, TripStatus.COMPLETED])
    if exclude_trip_id:
        qs = qs.exclude(pk=exclude_trip_id)
    for other in qs:
        o_start, o_end = trip_window(other.departure_at, other.arrival_estimated_at)
        if o_start < end and start < o_end:
            return other
    return None


def _check(trip, target):
    if target not in ALLOWED_TRANSITIONS.get(trip.status, set()):
        raise BusinessError(
            f"Transition impossible : {trip.get_status_display()} → {TripStatus(target).label}.",
            code="invalid_transition",
        )


@transaction.atomic
def transition(trip_id, target, *, tenant, actor, reason=""):
    """Change l'état d'un voyage de façon atomique et journalisée."""
    trip = Trip.objects.select_for_update().get(pk=trip_id, tenant=tenant)
    previous = trip.status
    _check(trip, target)
    if target == TripStatus.OPEN and not trip.bus.seats.exists():
        trip.bus.generate_seats()
    if target == TripStatus.CANCELLED and trip.boarding_events.filter(result="VALIDATED").exists():
        raise BusinessError("Des passagers sont déjà embarqués : le voyage ne peut plus être annulé.", code="already_boarded")
    trip.status = target
    trip.save(update_fields=["status"])
    audit.log(f"trip.{str(target).lower()}", actor=actor, tenant=tenant, entity="Trip", entity_id=trip.id,
              previous=previous, reason=reason)
    return trip


@transaction.atomic
def close_boarding(trip_id, *, tenant, actor):
    """Clôture : bloque les scans, fige le manifeste définitif, trace l'acteur."""
    from apps.manifests.services import finalize_manifest

    trip = Trip.objects.select_for_update().get(pk=trip_id, tenant=tenant)
    _check(trip, TripStatus.CLOSED)
    trip.status = TripStatus.CLOSED
    trip.closed_at = timezone.now()
    trip.closed_by = actor
    trip.save(update_fields=["status", "closed_at", "closed_by"])
    manifest = finalize_manifest(trip, actor)
    audit.log("trip.closed", actor=actor, tenant=tenant, entity="Trip", entity_id=trip.id,
              manifest_number=manifest.number, manifest_version=manifest.version)
    return trip, manifest


@transaction.atomic
def reopen(trip_id, *, tenant, actor, reason):
    if not reason or len(reason.strip()) < 5:
        raise BusinessError("Un motif (5 caractères minimum) est obligatoire pour rouvrir un voyage clôturé.", code="reason_required", status_code=400)
    trip = Trip.objects.select_for_update().get(pk=trip_id, tenant=tenant)
    if trip.status != TripStatus.CLOSED:
        raise BusinessError("Seul un voyage clôturé peut être rouvert.", code="invalid_transition")
    trip.status = TripStatus.BOARDING
    trip.save(update_fields=["status"])
    audit.log("trip.reopened", actor=actor, tenant=tenant, entity="Trip", entity_id=trip.id, reason=reason.strip())
    return trip
