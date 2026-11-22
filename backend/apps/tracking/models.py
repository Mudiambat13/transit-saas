from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenants.models import TenantOwnedModel


class TrackingSession(TenantOwnedModel):
    """Suivi d'un voyage depuis un téléphone. Le jeton appareil est propre à la session (stocké haché)."""

    trip = models.ForeignKey("trips.Trip", on_delete=models.PROTECT, related_name="tracking_sessions")
    token_hash = models.CharField(max_length=64, unique=True)
    device_label = models.CharField(max_length=80, blank=True)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=30, blank=True)  # STOPPED, TRIP_ENDED, REVOKED, REPLACED

    class Meta:
        constraints = [
            # Un seul téléphone actif par voyage : en démarrer un autre remplace le précédent.
            models.UniqueConstraint(fields=["trip"], condition=Q(ended_at__isnull=True), name="uniq_active_tracking_per_trip"),
        ]
        indexes = [models.Index(fields=["tenant", "ended_at"])]

    @property
    def is_active(self):
        return self.ended_at is None


class LocationPoint(TenantOwnedModel):
    session = models.ForeignKey(TrackingSession, on_delete=models.CASCADE, related_name="points")
    trip = models.ForeignKey("trips.Trip", on_delete=models.CASCADE, related_name="location_points")
    lat = models.FloatField()
    lon = models.FloatField()
    speed_kmh = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    accuracy_m = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField()          # heure d'origine sur le téléphone (peut être en différé)
    received_at = models.DateTimeField(auto_now_add=True)
    suspect = models.BooleanField(default=False)  # saut de position physiquement impossible

    class Meta:
        constraints = [models.UniqueConstraint(fields=["session", "recorded_at"], name="uniq_point_per_session_time")]
        indexes = [models.Index(fields=["trip", "-recorded_at"])]
        ordering = ["-recorded_at"]
