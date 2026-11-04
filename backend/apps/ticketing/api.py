from django.db.models import Q
from django.http import HttpResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasTenantPermission
from apps.accounts.tenancy import get_tenant, scope_by_agency
from apps.audit import service as audit

from . import qr, services
from .models import Ticket
from .pdf import render_ticket_pdf


class TicketSerializer(serializers.ModelSerializer):
    passenger_name = serializers.CharField(source="passenger.full_name", read_only=True)
    passenger_phone = serializers.CharField(source="passenger.phone", read_only=True)
    trip_reference = serializers.CharField(source="trip.reference", read_only=True)
    route = serializers.SerializerMethodField()
    seat_code = serializers.CharField(source="seat.code", read_only=True, default=None)
    boarded = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    qr_payload = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = ["id", "reference", "trip", "trip_reference", "route", "passenger_name", "passenger_phone",
                  "seat", "seat_code", "price", "currency", "status", "status_label", "boarded",
                  "payment_method", "qr_payload", "created_at"]

    def get_route(self, obj):
        return f"{obj.trip.origin} → {obj.trip.destination}"

    def get_boarded(self, obj):
        return obj.boarding_events.filter(result="VALIDATED").exists()

    def get_qr_payload(self, obj):
        return qr.build_payload(obj.public_token)

    def get_payment_method(self, obj):
        p = obj.payments.first()
        return p.method if p else None


class TicketCreateSerializer(serializers.Serializer):
    trip = serializers.IntegerField()
    full_name = serializers.CharField(max_length=160)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    id_type = serializers.CharField(max_length=30, required=False, allow_blank=True)
    id_number = serializers.CharField(max_length=60, required=False, allow_blank=True)
    extra_info = serializers.CharField(max_length=255, required=False, allow_blank=True)
    seat = serializers.IntegerField(required=False, allow_null=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    payment_method = serializers.CharField(max_length=20, required=False, default="CASH")
    payment_reference = serializers.CharField(max_length=60, required=False, allow_blank=True)


class TicketViewSet(viewsets.ReadOnlyModelViewSet):
    """Les billets ne se modifient pas : on les crée, on les consulte, on les annule."""

    permission_classes = [HasTenantPermission]
    serializer_class = TicketSerializer
    required_perms = {"list": "ticket.view", "retrieve": "ticket.view", "create": "ticket.create",
                      "pdf": "ticket.reprint", "cancel": "ticket.cancel"}
    search_fields = ["passenger__full_name", "passenger__phone", "reference", "trip__reference"]
    ordering_fields = ["created_at", "price"]

    def get_queryset(self):
        m = self.request.user.membership
        qs = Ticket.objects.filter(tenant=m.tenant).select_related("trip", "passenger", "seat", "trip__agency", "trip__bus")
        qs = scope_by_agency(qs, m, "trip__agency")
        p = self.request.query_params
        if p.get("trip"):
            qs = qs.filter(trip_id=p["trip"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        return qs

    def create(self, request):
        ser = TicketCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        m = request.user.membership
        ticket = services.create_ticket(
            tenant=m.tenant, actor=request.user, trip_id=d["trip"],
            passenger={k: d.get(k) for k in ("full_name", "phone", "id_type", "id_number", "extra_info")},
            seat_id=d.get("seat"), price=d.get("price"),
            payment={"method": d.get("payment_method"), "reference": d.get("payment_reference")},
            agency_scope_id=m.agency_id if m.role != "COMPANY_ADMIN" else None,
        )
        return Response(TicketSerializer(ticket).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        ticket = self.get_object()
        audit.log("ticket.printed", actor=request.user, tenant=ticket.tenant, entity="Ticket", entity_id=ticket.id)
        resp = HttpResponse(render_ticket_pdf(ticket), content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{ticket.reference}.pdf"'
        return resp

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        ticket = self.get_object()
        m = request.user.membership
        out = services.cancel_ticket(
            tenant=m.tenant, actor=request.user, ticket_id=ticket.pk, reason=request.data.get("reason", ""),
            agency_scope_id=m.agency_id if m.role != "COMPANY_ADMIN" else None,
        )
        return Response(TicketSerializer(out).data)
