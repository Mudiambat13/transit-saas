from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import HasTenantPermission
from apps.accounts.tenancy import get_tenant, scope_by_agency
from apps.trips.models import Trip

from . import services
from .models import BoardingEvent, ScanResult


class ScanInputSerializer(serializers.Serializer):
    trip = serializers.IntegerField()
    code = serializers.CharField(max_length=120)
    device = serializers.CharField(max_length=80, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=64, required=False, allow_blank=True)


class ScanView(APIView):
    permission_classes = [HasTenantPermission]
    required_perm = "boarding.scan"
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "scan"

    def post(self, request):
        ser = ScanInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        m = request.user.membership
        out = services.scan(
            tenant=m.tenant, agent=request.user, trip_id=d["trip"], code=d["code"],
            device=d.get("device", ""), idempotency_key=d.get("idempotency_key", ""),
            agency_scope_id=m.agency_id if m.role != "COMPANY_ADMIN" else None,
        )
        if out is None:
            raise NotFound("Voyage introuvable.")
        return Response(out)


def _trip_for(request, trip_id):
    m = request.user.membership
    qs = scope_by_agency(Trip.objects.filter(tenant=m.tenant), m, "agency")
    trip = qs.filter(pk=trip_id).first()
    if trip is None:
        raise NotFound("Voyage introuvable.")
    return trip


class TripBoardingView(APIView):
    """Liste d'embarquement en direct : embarqués / restants."""

    permission_classes = [HasTenantPermission]
    required_perm = "boarding.view"

    def get(self, request, trip_id):
        trip = _trip_for(request, trip_id)
        tickets = trip.tickets.filter(status="ACTIVE").select_related("passenger", "seat")
        boarded = {e.ticket_id: e.created_at for e in
                   BoardingEvent.objects.filter(trip=trip, result=ScanResult.VALIDATED)}
        rows = [{
            "ticket_id": t.id, "reference": t.reference, "passenger": t.passenger.full_name,
            "seat": t.seat.code if t.seat else None,
            "boarded": t.id in boarded, "boarded_at": boarded.get(t.id),
        } for t in tickets.order_by("seat__id", "id")]
        n_boarded = sum(1 for r in rows if r["boarded"])
        return Response({
            "trip": {"id": trip.id, "reference": trip.reference, "status": trip.status},
            "totals": {"valid": len(rows), "boarded": n_boarded, "remaining": len(rows) - n_boarded},
            "passengers": rows,
        })


class TripBoardingEventsView(APIView):
    permission_classes = [HasTenantPermission]
    required_perm = "boarding.view"

    def get(self, request, trip_id):
        trip = _trip_for(request, trip_id)
        events = BoardingEvent.objects.filter(trip=trip).select_related("ticket__passenger", "agent")[:300]
        return Response([{
            "id": e.id, "result": e.result, "label": e.get_result_display(),
            "ticket": e.ticket.reference if e.ticket else None,
            "passenger": e.ticket.passenger.full_name if e.ticket else None,
            "agent": e.agent.email if e.agent else None, "created_at": e.created_at,
        } for e in events])
