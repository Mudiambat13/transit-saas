"""Suivi de position : sessions, ingestion par lots tolérante aux coupures réseau, anomalies."""
import hashlib
import math
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.exceptions import BusinessError
from apps.audit import service as audit
from apps.trips.models import Trip, TripStatus

from .models import LocationPoint, TrackingSession

TRACKABLE = {TripStatus.OPEN, TripStatus.BOARDING, TripStatus.CLOSED}
MAX_BATCH = 200
MAX_FUTURE = timedelta(minutes=5)
MAX_AGE = timedelta(days=2)
MAX_PLAUSIBLE_KMH = 220.0   # au-delà entre deux points : point suspect (GPS faux ou saut)
STALE_AFTER = timedelta(minutes=5)
PUBLIC_VISIBLE_FOR = timedelta(minutes=30)


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_tracking_code():
    return secrets.token_urlsafe(9)


def ensure_tracking_code(trip):
    if not trip.tracking_code:
        trip.tracking_code = new_tracking_code()
        trip.save(update_fields=["tracking_code"])
    return trip.tracking_code


def haversine_km(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0088
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dphi, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def driver_may_track(user, trip):
    """Un chauffeur ne suit que les voyages auxquels il est affecté ; les autres rôles autorisés ont tout leur périmètre."""
    m = user.membership
    if m.role != "DRIVER":
        return True
    return trip.drivers.filter(user=user).exists()


@transaction.atomic
def start_session(*, tenant, actor, trip_id, device_label="", agency_scope_id=None):
    trip = Trip.objects.select_for_update().filter(pk=trip_id, tenant=tenant).first()
    if trip is None or (agency_scope_id and trip.agency_id != agency_scope_id):
        raise BusinessError("Voyage introuvable.", code="trip_not_found", status_code=404)
    if not driver_may_track(actor, trip):
        raise BusinessError("Ce voyage ne vous est pas affecté.", code="not_assigned", status_code=403)
    if trip.status not in TRACKABLE:
        raise BusinessError("Le suivi n'est possible que pour un voyage ouvert, en embarquement ou clôturé (en route).", code="trip_not_trackable")
    now = timezone.now()
    replaced = TrackingSession.objects.filter(trip=trip, ended_at__isnull=True).update(ended_at=now, ended_reason="REPLACED")
    token = secrets.token_urlsafe(32)
    session = TrackingSession.objects.create(
        tenant=tenant, trip=trip, token_hash=hash_token(token), device_label=device_label[:80], started_by=actor)
    ensure_tracking_code(trip)
    audit.log("tracking.started", actor=actor, tenant=tenant, entity="Trip", entity_id=trip.id, replaced=bool(replaced))
    return session, token


@transaction.atomic
def stop_session(*, tenant, actor, trip_id, reason="STOPPED"):
    n = TrackingSession.objects.filter(tenant=tenant, trip_id=trip_id, ended_at__isnull=True).update(
        ended_at=timezone.now(), ended_reason=reason)
    if n:
        audit.log("tracking.stopped", actor=actor, tenant=tenant, entity="Trip", entity_id=trip_id, reason=reason)
    return n


@transaction.atomic
def end_by_device(session):
    """Le téléphone termine lui-même sa session (jeton appareil). Idempotent."""
    n = TrackingSession.objects.filter(pk=session.pk, ended_at__isnull=True).update(ended_at=timezone.now(), ended_reason="STOPPED")
    if n:
        audit.log("tracking.stopped", tenant=session.tenant, entity="Trip", entity_id=session.trip_id, reason="STOPPED", by="device")
    return bool(n)


def end_sessions_for_trip(trip, reason="TRIP_ENDED"):
    """Appelé quand un voyage est terminé ou annulé."""
    return TrackingSession.objects.filter(trip=trip, ended_at__isnull=True).update(ended_at=timezone.now(), ended_reason=reason)


def session_from_token(token):
    if not token or len(token) > 100:
        return None
    return TrackingSession.objects.select_related("trip", "tenant").filter(token_hash=hash_token(token)).first()


def _clean_point(raw, now):
    try:
        lat, lon = float(raw["lat"]), float(raw["lon"])
        recorded = raw["recorded_at"]
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    from django.utils.dateparse import parse_datetime
    when = parse_datetime(recorded) if isinstance(recorded, str) else None
    if when is None:
        return None
    if timezone.is_naive(when):
        when = timezone.make_aware(when, timezone.utc)
    if when > now + MAX_FUTURE or when < now - MAX_AGE:
        return None

    def opt(key, lo, hi):
        try:
            v = float(raw.get(key)) if raw.get(key) is not None else None
        except (TypeError, ValueError):
            return None
        return v if v is not None and lo <= v <= hi else None

    return {"lat": lat, "lon": lon, "recorded_at": when, "speed_kmh": opt("speed_kmh", 0, 400),
            "heading": opt("heading", 0, 360), "accuracy_m": opt("accuracy_m", 0, 100000)}


def ingest(session, raw_points):
    """Enregistre un lot (rejouable : un point déjà reçu est ignoré). Retourne un résumé."""
    if not session.is_active:
        raise BusinessError("Le suivi de ce voyage est terminé.", code="session_ended", status_code=410)
    if session.trip.status not in TRACKABLE:
        end_sessions_for_trip(session.trip)
        raise BusinessError("Le voyage est terminé : le suivi est arrêté.", code="session_ended", status_code=410)
    if not isinstance(raw_points, list) or not raw_points:
        raise BusinessError("Aucun point fourni.", code="empty_batch", status_code=400)
    if len(raw_points) > MAX_BATCH:
        raise BusinessError(f"Lot trop grand (maximum {MAX_BATCH} points).", code="batch_too_large", status_code=400)

    now = timezone.now()
    cleaned = [c for c in (_clean_point(p, now) for p in raw_points) if c]
    rejected = len(raw_points) - len(cleaned)
    cleaned.sort(key=lambda c: c["recorded_at"])

    prev = LocationPoint.objects.filter(session=session, suspect=False).order_by("-recorded_at").first()
    existing = set(LocationPoint.objects.filter(
        session=session, recorded_at__in=[c["recorded_at"] for c in cleaned]).values_list("recorded_at", flat=True))
    to_create, duplicates, suspects = [], 0, 0
    last_ok = (prev.lat, prev.lon, prev.recorded_at) if prev else None
    for c in cleaned:
        if c["recorded_at"] in existing:
            duplicates += 1
            continue
        suspect = False
        if last_ok:
            dt_h = (c["recorded_at"] - last_ok[2]).total_seconds() / 3600
            dist = haversine_km(last_ok[0], last_ok[1], c["lat"], c["lon"])
            if dt_h > 0 and dist / dt_h > MAX_PLAUSIBLE_KMH and dist > 0.3:
                suspect = True
        if suspect:
            suspects += 1
        else:
            last_ok = (c["lat"], c["lon"], c["recorded_at"])
        to_create.append(LocationPoint(tenant=session.tenant, session=session, trip=session.trip, suspect=suspect, **c))
    try:
        with transaction.atomic():
            LocationPoint.objects.bulk_create(to_create, ignore_conflicts=True)
    except IntegrityError:  # lots concurrents : les doublons sont déjà écartés par ignore_conflicts
        pass
    return {"accepted": len(to_create), "duplicates": duplicates, "rejected": rejected, "suspect": suspects}


def latest_point(trip, include_suspect=False):
    qs = LocationPoint.objects.filter(trip=trip)
    if not include_suspect:
        qs = qs.filter(suspect=False)
    return qs.order_by("-recorded_at").first()


def point_dict(p):
    return {"lat": p.lat, "lon": p.lon, "speed_kmh": p.speed_kmh, "heading": p.heading,
            "accuracy_m": p.accuracy_m, "recorded_at": p.recorded_at}


def is_stale(point, now=None):
    return point is None or (now or timezone.now()) - point.recorded_at > STALE_AFTER


def purge_old_points(days):
    cutoff = timezone.now() - timedelta(days=days)
    n, _ = LocationPoint.objects.filter(recorded_at__lt=cutoff).delete()
    return n
