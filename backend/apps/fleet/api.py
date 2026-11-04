from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.tenancy import TenantModelViewSet, get_tenant
from apps.audit import service as audit

from .models import Bus, Driver, Seat


class SeatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Seat
        fields = ["id", "code", "category"]


class BusSerializer(serializers.ModelSerializer):
    seat_count = serializers.IntegerField(source="seats.count", read_only=True)

    class Meta:
        model = Bus
        fields = ["id", "plate", "brand", "model", "capacity", "status", "seat_count", "created_at"]
        read_only_fields = ["id", "created_at", "seat_count"]

    def validate_capacity(self, value):
        if not 1 <= value <= 120:
            raise serializers.ValidationError("La capacité doit être comprise entre 1 et 120.")
        return value

    def validate(self, attrs):
        tenant = get_tenant(self.context["request"])
        plate = attrs.get("plate")
        if plate:
            attrs["plate"] = plate.strip().upper()
            qs = Bus.objects.filter(tenant=tenant, plate=attrs["plate"])
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"plate": "Cette immatriculation existe déjà."})
        if self.instance and "capacity" in attrs and attrs["capacity"] < self.instance.capacity:
            if self.instance.trips.filter(status__in=["OPEN", "BOARDING"]).exists():
                raise serializers.ValidationError({"capacity": "Impossible de réduire la capacité d'un bus affecté à un voyage actif."})
        return attrs


class DriverSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = ["id", "full_name", "phone", "license_number", "is_active"]


class BusViewSet(TenantModelViewSet):
    queryset = Bus.objects.all()
    serializer_class = BusSerializer
    search_fields = ["plate", "brand", "model"]
    required_perms = {"list": "fleet.view", "retrieve": "fleet.view", "seats": "fleet.view", "*": "fleet.manage"}

    @transaction.atomic
    def perform_create(self, serializer):
        super().perform_create(serializer)
        serializer.instance.generate_seats()
        audit.log("bus.created", actor=self.request.user, tenant=get_tenant(self.request), entity="Bus", entity_id=serializer.instance.id)

    @transaction.atomic
    def perform_update(self, serializer):
        bus = serializer.save()
        bus.generate_seats()  # complète les sièges si la capacité augmente
        audit.log("bus.updated", actor=self.request.user, tenant=bus.tenant, entity="Bus", entity_id=bus.id)

    def perform_destroy(self, instance):
        if instance.trips.exists():
            instance.status = "RETIRED"
            instance.save(update_fields=["status"])
        else:
            instance.delete()

    @action(detail=True, methods=["get"])
    def seats(self, request, pk=None):
        return Response(SeatSerializer(self.get_object().seats.order_by("id"), many=True).data)


class DriverViewSet(TenantModelViewSet):
    queryset = Driver.objects.all()
    serializer_class = DriverSerializer
    search_fields = ["full_name", "phone"]
    required_perms = {"list": "fleet.view", "retrieve": "fleet.view", "*": "fleet.manage"}
