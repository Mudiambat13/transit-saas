from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.exceptions import BusinessError
from apps.accounts.permissions import HasTenantPermission, has_perm
from apps.accounts.tenancy import scope_by_agency
from apps.audit import service as audit
from apps.trips import services as trip_services
from apps.trips.models import Trip, TripStatus

from . import services
from .models import Manifest
from .pdf import render_manifest_pdf


class ManifestListSerializer(serializers.ModelSerializer):
    type_label = serializers.CharField(source="get_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Manifest
        fields = ["id", "trip", "type", "type_label", "number", "version", "status", "status_label", "created_by_name", "created_at"]

    def get_created_by_name(self, obj):
        return (obj.created_by.full_name or obj.created_by.email) if obj.created_by else None


def _trip(request, trip_id):
    m = request.user.membership
    trip = scope_by_agency(Trip.objects.filter(tenant=m.tenant), m, "agency").filter(pk=trip_id).first()
    if trip is None:
        raise NotFound("Voyage introuvable.")
    return trip


class TripManifestsView(APIView):
    permission_classes = [HasTenantPermission]
    required_perm = "manifest.view"

    def get(self, request, trip_id):
        trip = _trip(request, trip_id)
        qs = Manifest.objects.filter(tenant=trip.tenant, trip=trip).select_related("created_by")
        return Response(ManifestListSerializer(qs, many=True).data)


class PreviewManifestView(APIView):
    permission_classes = [HasTenantPermission]
    required_perm = "manifest.generate"

    def post(self, request, trip_id):
        trip = _trip(request, trip_id)
        m = services.generate_preview(trip, request.user)
        return Response({**ManifestListSerializer(m).data, "snapshot": m.snapshot}, status=201)


class FinalizeManifestView(APIView):
    """Équivalent de `close-boarding` : la clôture produit le manifeste définitif archivé."""

    permission_classes = [HasTenantPermission]
    required_perm = "manifest.finalize"

    def post(self, request, trip_id):
        trip = _trip(request, trip_id)
        if trip.status != TripStatus.BOARDING:
            raise BusinessError("Le manifeste définitif se génère à la clôture d'un voyage en cours d'embarquement.", code="invalid_transition")
        trip, manifest = trip_services.close_boarding(trip.pk, tenant=trip.tenant, actor=request.user)
        return Response({**ManifestListSerializer(manifest).data, "snapshot": manifest.snapshot}, status=201)


def _manifest(request, pk):
    m = request.user.membership
    obj = Manifest.objects.filter(tenant=m.tenant, pk=pk).select_related("trip", "created_by").first()
    if obj is None or (m.agency_id and m.role != "COMPANY_ADMIN" and obj.trip.agency_id != m.agency_id):
        raise NotFound("Manifeste introuvable.")
    return obj


class ManifestDetailView(APIView):
    permission_classes = [HasTenantPermission]
    required_perm = "manifest.view"

    def get(self, request, pk):
        obj = _manifest(request, pk)
        return Response({**ManifestListSerializer(obj).data, "snapshot": obj.snapshot})


class ManifestPdfView(APIView):
    permission_classes = [HasTenantPermission]
    required_perm = "manifest.view"

    def get(self, request, pk):
        obj = _manifest(request, pk)
        audit.log("manifest.exported", actor=request.user, tenant=obj.tenant, entity="Manifest", entity_id=obj.id, number=obj.number)
        resp = HttpResponse(render_manifest_pdf(obj), content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{obj.number}.pdf"'
        return resp
