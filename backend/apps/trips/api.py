from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.exceptions import BusinessError
from apps.accounts.permissions import has_perm
from apps.accounts.serializers import _enforce_plan_limit
from apps.accounts.tenancy import TenantModelViewSet, TenantPrimaryKeyRelatedField, get_tenant
from apps.agencies.models import Agency
from apps.audit import service as audit
from apps.fleet.models import Bus, BusStatus, Driver

from . import services
from .models import Trip, TripDriver, TripStatus


class TripSerializer(serializers.ModelSerializer):
    agency = TenantPrimaryKeyRelatedField(queryset=Agency.objects.all())
    bus = TenantPrimaryKeyRelatedField(queryset=Bus.objects.all())
    driver_ids = TenantPrimaryKeyRelatedField(queryset=Driver.objects.all(), many=True, required=False, write_only=True)
    agency_name = serializers.CharField(source="agency.name", read_only=True)
    bus_plate = serializers.CharField(source="bus.plate", read_only=True)
    drivers_detail = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    sold = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = ["id", "reference", "agency", "agency_name", "origin", "destination", "departure_at",
                  "arrival_estimated_at", "bus", "bus_plate", "driver_ids", "drivers_detail", "capacity",
                  "price", "currency", "status", "status_label", "notes", "closed_at", "sold", "created_at"]
        read_only_fields = ["id", "capacity", "status", "closed_at", "created_at"]
        extra_kwargs = {"currency": {"required": False}, "reference": {"required": False}}

    def get_drivers_detail(self, obj):
        return [{"id": d.id, "full_name": d.full_name} for d in obj.drivers.all()]

    def get_sold(self, obj):
        return obj.tickets.filter(status="ACTIVE").count()

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Le prix ne peut pas être négatif.")
        return value

    def validate(self, attrs):
        tenant = get_tenant(self.context["request"])
        inst = self.instance
        if inst and inst.status not in (TripStatus.DRAFT, TripStatus.OPEN, TripStatus.SUSPENDED):
            raise serializers.ValidationError("Ce voyage ne peut plus être modifié dans son état actuel.")
        bus = attrs.get("bus", inst.bus if inst else None)
        departure = attrs.get("departure_at", inst.departure_at if inst else None)
        arrival = attrs.get("arrival_estimated_at", inst.arrival_estimated_at if inst else None)
        if arrival and departure and arrival <= departure:
            raise serializers.ValidationError({"arrival_estimated_at": "L'arrivée doit être postérieure au départ."})
        if bus and bus.status != BusStatus.ACTIVE:
            raise serializers.ValidationError({"bus": "Ce bus n'est pas en service."})
        if inst and bus and bus.pk != inst.bus_id and inst.tickets.filter(status="ACTIVE").exists():
            raise serializers.ValidationError({"bus": "Des billets existent déjà : changement de bus impossible."})
        if bus and departure:
            other = services.find_bus_conflict(tenant, bus, departure, arrival, exclude_trip_id=inst.pk if inst else None)
            if other:
                raise serializers.ValidationError({"bus": f"Ce bus est déjà affecté au voyage {other.reference} sur cette période."})
        if not inst:
            _enforce_trip_quota(tenant)
        return attrs

    @transaction.atomic
    def create(self, validated):
        drivers = validated.pop("driver_ids", [])
        request = self.context["request"]
        tenant = get_tenant(request)
        bus = validated["bus"]
        validated.setdefault("currency", tenant.currency)
        if not validated.get("reference"):
            validated["reference"] = _next_reference(tenant)
        elif Trip.objects.filter(tenant=tenant, reference=validated["reference"]).exists():
            raise serializers.ValidationError({"reference": "Cette référence existe déjà."})
        trip = Trip.objects.create(capacity=bus.capacity, created_by=request.user, **validated)
        for d in drivers:
            TripDriver.objects.create(trip=trip, driver=d)
        return trip

    @transaction.atomic
    def update(self, instance, validated):
        drivers = validated.pop("driver_ids", None)
        if "bus" in validated:
            instance.capacity = validated["bus"].capacity
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if drivers is not None:
            instance.trip_drivers.all().delete()
            for d in drivers:
                TripDriver.objects.create(trip=instance, driver=d)
        return instance


def _next_reference(tenant):
    from django.utils import timezone

    prefix = f"V{timezone.now():%y%m}-"
    count = Trip.objects.filter(tenant=tenant, reference__startswith=prefix).count() + 1
    while Trip.objects.filter(tenant=tenant, reference=f"{prefix}{count:04d}").exists():
        count += 1
    return f"{prefix}{count:04d}"


def _enforce_trip_quota(tenant):
    from django.utils import timezone

    now = timezone.now()
    n = Trip.objects.filter(tenant=tenant, created_at__year=now.year, created_at__month=now.month).count()
    _enforce_plan_limit(tenant, "max_trips_per_month", n, "voyages par mois")


class TripViewSet(TenantModelViewSet):
    queryset = Trip.objects.select_related("agency", "bus").prefetch_related("drivers")
    serializer_class = TripSerializer
    agency_field = "agency"
    search_fields = ["reference", "origin", "destination"]
    ordering_fields = ["departure_at", "created_at", "status"]
    required_perms = {
        "list": "trip.view", "retrieve": "trip.view", "available_seats": "trip.view",
        "reopen": "trip.reopen", "*": "trip.manage",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("sellable") == "1":
            qs = qs.filter(status__in=list(services.SELLABLE))
        if p.get("date_from"):
            qs = qs.filter(departure_at__date__gte=p["date_from"])
        if p.get("date_to"):
            qs = qs.filter(departure_at__date__lte=p["date_to"])
        return qs

    def perform_create(self, serializer):
        super().perform_create(serializer)
        audit.log("trip.created", actor=self.request.user, tenant=get_tenant(self.request), entity="Trip", entity_id=serializer.instance.id)

    def perform_destroy(self, instance):
        if instance.status != TripStatus.DRAFT or instance.tickets.exists():
            raise BusinessError("Seul un brouillon sans billet peut être supprimé ; annulez le voyage sinon.", code="not_deletable")
        instance.delete()

    def _do(self, request, pk, target):
        trip = self.get_object()  # applique tenant + périmètre d'agence
        out = services.transition(trip.pk, target, tenant=trip.tenant, actor=request.user, reason=request.data.get("reason", ""))
        return Response(self.get_serializer(out).data)

    @action(detail=True, methods=["post"], url_path="open-sales")
    def open_sales(self, request, pk=None):
        return self._do(request, pk, TripStatus.OPEN)

    @action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, pk=None):
        return self._do(request, pk, TripStatus.SUSPENDED)

    @action(detail=True, methods=["post"], url_path="start-boarding")
    def start_boarding(self, request, pk=None):
        return self._do(request, pk, TripStatus.BOARDING)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        return self._do(request, pk, TripStatus.COMPLETED)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        return self._do(request, pk, TripStatus.CANCELLED)

    @action(detail=True, methods=["post"], url_path="close-boarding")
    def close_boarding(self, request, pk=None):
        trip = self.get_object()
        if not has_perm(request.user, "manifest.finalize"):
            raise BusinessError("Vous n'avez pas la permission de clôturer un voyage.", code="forbidden", status_code=403)
        trip, manifest = services.close_boarding(trip.pk, tenant=trip.tenant, actor=request.user)
        data = self.get_serializer(trip).data
        data["manifest"] = {"id": manifest.id, "number": manifest.number, "version": manifest.version}
        return Response(data)

    @action(detail=True, methods=["post"], url_path="reopen")
    def reopen(self, request, pk=None):
        trip = self.get_object()
        out = services.reopen(trip.pk, tenant=trip.tenant, actor=request.user, reason=request.data.get("reason", ""))
        return Response(self.get_serializer(out).data)

    @action(detail=True, methods=["get"], url_path="available-seats")
    def available_seats(self, request, pk=None):
        trip = self.get_object()
        taken = set(trip.tickets.filter(status="ACTIVE", seat__isnull=False).values_list("seat_id", flat=True))
        seats = trip.bus.seats.order_by("id")
        sold = trip.tickets.filter(status="ACTIVE").count()
        return Response({
            "capacity": trip.capacity,
            "sold": sold,
            "remaining": max(trip.capacity - sold, 0),
            "seat_selection": bool(get_tenant(request).setting("seat_selection", True)),
            "seats": [{"id": s.id, "code": s.code, "available": s.id not in taken} for s in seats],
        })
