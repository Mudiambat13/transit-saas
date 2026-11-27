from datetime import timedelta

from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import HasTenantPermission
from apps.accounts.tenancy import scope_by_agency
from apps.trips.models import Trip, TripStatus

from . import services
from .models import LocationPoint, TrackingSession


class TokenThrottle(SimpleRateThrottle):
    """Limite par jeton appareil (et non par IP : plusieurs bus peuvent partager une sortie réseau)."""

    scope = "track_ingest"

    def get_cache_key(self, request, view):
        token = request.headers.get("X-Tracking-Token", "")
        return self.cache_format % {"scope": self.scope, "ident": services.hash_token(token) if token else self.get_ident(request)}


class IpThrottle(SimpleRateThrottle):
    """Plafond par adresse IP, large : empêche d'inonder la base avec des jetons inventés (chacun aurait son propre compteur)."""

    scope = "track_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


def _trip(request, trip_id):
    m = request.user.membership
    trip = scope_by_agency(Trip.objects.filter(tenant=m.tenant), m, "agency").filter(pk=trip_id).first()
    if trip is None:
        raise NotFound("Voyage introuvable.")
    if not services.driver_may_track(request.user, trip):
        raise NotFound("Voyage introuvable.")  # un chauffeur ne voit pas les voyages des autres
    return trip


def _session_dict(s):
    return {"id": s.id, "started_at": s.started_at, "ended_at": s.ended_at, "ended_reason": s.ended_reason,
            "device_label": s.device_label}


class StartTrackingView(APIView):
    permission_classes = [HasTenantPermission]
    required_perm = "tracking.manage"

    def post(self, request, trip_id):
        m = request.user.membership
        session, token = services.start_session(
            tenant=m.tenant, actor=request.user, trip_id=trip_id,
            device_label=str(request.data.get("device_label", "")),
            agency_scope_id=m.agency_id if m.role != "COMPANY_ADMIN" else None)
        # Le jeton n'est montré qu'une seule fois : seul son hachage est conservé.
        return Response({"session": _session_dict(session), "token": token}, status=201)


class StopTrackingView(APIView):
    permission_classes = [HasTenantPermission]
    required_perm = "tracking.manage"

    def post(self, request, trip_id):
        trip = _trip(request, trip_id)
        n = services.stop_session(tenant=trip.tenant, actor=request.user, trip_id=trip.id)
        return Response({"stopped": bool(n)})


class TripTrackingView(APIView):
    """Position courante + tracé d'un voyage (compagnie)."""

    permission_classes = [HasTenantPermission]
    required_perm = "tracking.view"

    def get(self, request, trip_id):
        trip = _trip(request, trip_id)
        session = trip.tracking_sessions.order_by("-started_at").first()
        last = services.latest_point(trip)
        try:
            limit = min(int(request.query_params.get("limit", 500)), 2000)
        except ValueError:
            limit = 500
        trail = list(LocationPoint.objects.filter(trip=trip, suspect=False).order_by("-recorded_at")[:limit])
        trail.reverse()
        return Response({
            "trip": {"id": trip.id, "reference": trip.reference, "route": f"{trip.origin} → {trip.destination}", "status": trip.status},
            "tracking_code": trip.tracking_code,
            "session": _session_dict(session) if session else None,
            "active": bool(session and session.is_active),
            "last": services.point_dict(last) if last else None,
            "stale": services.is_stale(last) if session and session.is_active else None,
            "trail": [[p.lat, p.lon] for p in trail],
            "replay": [[p.lat, p.lon, p.speed_kmh, p.recorded_at] for p in trail],
            "stats": services.trip_stats(trail),
            "departure_at": trip.departure_at,
            "drivers": [d.full_name for d in trip.drivers.all()],
            "bus": trip.bus.plate,
            "suspect_points": LocationPoint.objects.filter(trip=trip, suspect=True).count(),
        })


class LiveFleetView(APIView):
    """Tous les bus suivis en ce moment dans la compagnie."""

    permission_classes = [HasTenantPermission]
    required_perm = "tracking.view"

    def get(self, request):
        m = request.user.membership
        sessions = scope_by_agency(
            TrackingSession.objects.filter(tenant=m.tenant, ended_at__isnull=True).select_related("trip", "trip__bus").prefetch_related("trip__drivers"), m, "trip__agency")
        if m.role == "DRIVER":
            sessions = sessions.filter(trip__drivers__user=request.user)
        out = []
        for s in sessions:
            last = services.latest_point(s.trip)
            out.append({
                "trip_id": s.trip_id, "reference": s.trip.reference, "route": f"{s.trip.origin} → {s.trip.destination}",
                "bus": s.trip.bus.plate, "status": s.trip.status, "departure_at": s.trip.departure_at, "started_at": s.started_at,
                "drivers": [d.full_name for d in s.trip.drivers.all()],
                "last": services.point_dict(last) if last else None, "stale": services.is_stale(last),
            })
        return Response(out)


class MyTripsView(APIView):
    """Voyages que l'utilisateur peut suivre (page chauffeur)."""

    permission_classes = [HasTenantPermission]
    required_perm = "tracking.manage"

    def get(self, request):
        m = request.user.membership
        qs = scope_by_agency(Trip.objects.filter(tenant=m.tenant, status__in=list(services.TRACKABLE)), m, "agency")
        if m.role == "DRIVER":
            qs = qs.filter(drivers__user=request.user)
        qs = qs.select_related("bus").order_by("departure_at").distinct()
        active = set(TrackingSession.objects.filter(tenant=m.tenant, ended_at__isnull=True).values_list("trip_id", flat=True))
        return Response([{
            "id": t.id, "reference": t.reference, "route": f"{t.origin} → {t.destination}", "departure_at": t.departure_at,
            "status": t.status, "bus": t.bus.plate, "tracking_active": t.id in active,
        } for t in qs])


class IngestView(APIView):
    """Réception des positions envoyées par le téléphone. Authentifiée par le jeton appareil de la session."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [TokenThrottle, IpThrottle]

    def post(self, request):
        session = services.session_from_token(request.headers.get("X-Tracking-Token", ""))
        if session is None:
            return Response({"detail": "Jeton de suivi invalide.", "code": "invalid_token"}, status=401)
        if not session.tenant.is_active:
            return Response({"detail": "Compagnie suspendue.", "code": "tenant_inactive"}, status=403)
        points = request.data.get("points") if hasattr(request.data, "get") else None
        return Response(services.ingest(session, points))


class EndView(APIView):
    """Le téléphone met fin à son suivi avec son jeton appareil (aucun mot de passe ni JWT conservé sur l'appareil)."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [TokenThrottle, IpThrottle]

    def post(self, request):
        session = services.session_from_token(request.headers.get("X-Tracking-Token", ""))
        if session is None:
            return Response({"detail": "Jeton de suivi invalide.", "code": "invalid_token"}, status=401)
        return Response({"stopped": services.end_by_device(session)})


class PublicTrackView(APIView):
    """Page passagers : sans connexion, uniquement le strict nécessaire (jamais le bus, le chauffeur ni les billets)."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "track_public"

    def get(self, request, code):
        trip = Trip.objects.select_related("tenant").filter(tracking_code=code).first()
        if trip is None or not trip.tenant.is_active:
            raise NotFound("Lien de suivi inconnu.")
        now = timezone.now()
        session = trip.tracking_sessions.filter(ended_at__isnull=True).first()
        ended = trip.status in (TripStatus.COMPLETED, TripStatus.CANCELLED)
        data = {
            "company": trip.tenant.name, "origin": trip.origin, "destination": trip.destination,
            "departure_at": trip.departure_at, "status": trip.status, "status_label": trip.get_status_display(),
            "timezone": trip.tenant.timezone, "tracking_active": bool(session) and not ended,
            "position": None, "trail": [], "stale": None,
        }
        if session and not ended:
            last = services.latest_point(trip)
            if last and now - last.recorded_at <= services.PUBLIC_VISIBLE_FOR:
                data["position"] = {"lat": last.lat, "lon": last.lon, "speed_kmh": last.speed_kmh, "recorded_at": last.recorded_at}
                data["stale"] = services.is_stale(last, now)
                pts = LocationPoint.objects.filter(trip=trip, suspect=False, recorded_at__gte=now - timedelta(hours=3)).order_by("-recorded_at")[:40]
                data["trail"] = [[p.lat, p.lon] for p in reversed(list(pts))]
        return Response(data)
