from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasTenantPermission
from apps.accounts.tenancy import scope_by_agency
from apps.boarding.models import BoardingEvent
from apps.ticketing.models import Ticket
from apps.trips.models import Trip


class DashboardView(APIView):
    """Indicateurs de la compagnie (périmètre d'agence appliqué)."""

    permission_classes = [HasTenantPermission]
    required_perm = "report.view"

    def get(self, request):
        m = request.user.membership
        now = timezone.now()
        trips = scope_by_agency(Trip.objects.filter(tenant=m.tenant), m, "agency")
        tickets = scope_by_agency(Ticket.objects.filter(tenant=m.tenant), m, "trip__agency")
        today = tickets.filter(created_at__date=now.date(), status="ACTIVE")
        upcoming = trips.filter(departure_at__gte=now - timedelta(hours=6), status__in=["OPEN", "BOARDING", "SUSPENDED"]).order_by("departure_at")[:8]
        revenue = tickets.filter(status="ACTIVE", created_at__year=now.year, created_at__month=now.month).values("currency").annotate(total=Sum("price"))
        return Response({
            "trips": trips.aggregate(
                open=Count("id", filter=Q(status="OPEN")), boarding=Count("id", filter=Q(status="BOARDING")),
                draft=Count("id", filter=Q(status="DRAFT")), closed=Count("id", filter=Q(status="CLOSED"))),
            "tickets_today": today.count(),
            "tickets_month": tickets.filter(status="ACTIVE", created_at__year=now.year, created_at__month=now.month).count(),
            "cancelled_month": tickets.filter(status="CANCELLED", created_at__year=now.year, created_at__month=now.month).count(),
            "revenue_month": [{"currency": r["currency"], "total": f"{Decimal(str(r['total'])):.2f}"} for r in revenue],
            "upcoming": [{
                "id": t.id, "reference": t.reference, "route": f"{t.origin} → {t.destination}",
                "departure_at": t.departure_at, "status": t.status, "capacity": t.capacity,
                "sold": t.tickets.filter(status="ACTIVE").count(),
            } for t in upcoming],
        })


class TripStatsView(APIView):
    """Remplissage et embarquement d'un voyage."""

    permission_classes = [HasTenantPermission]
    required_perm = "report.view"

    def get(self, request, trip_id):
        m = request.user.membership
        trip = scope_by_agency(Trip.objects.filter(tenant=m.tenant), m, "agency").filter(pk=trip_id).first()
        if trip is None:
            from rest_framework.exceptions import NotFound
            raise NotFound("Voyage introuvable.")
        sold = trip.tickets.filter(status="ACTIVE").count()
        cancelled = trip.tickets.filter(status="CANCELLED").count()
        boarded = BoardingEvent.objects.filter(trip=trip, result="VALIDATED").count()
        return Response({
            "capacity": trip.capacity, "sold": sold, "cancelled": cancelled, "remaining": max(trip.capacity - sold, 0),
            "boarded": boarded, "absent": max(sold - boarded, 0),
            "fill_rate": round(100 * sold / trip.capacity, 1) if trip.capacity else 0,
            "boarding_rate": round(100 * boarded / sold, 1) if sold else 0,
        })
