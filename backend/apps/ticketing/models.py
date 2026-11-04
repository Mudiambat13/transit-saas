from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenants.models import TenantOwnedModel


class TicketStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Valide"
    CANCELLED = "CANCELLED", "Annulé"


class Passenger(TenantOwnedModel):
    full_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40, blank=True)
    id_type = models.CharField(max_length=30, blank=True)
    id_number = models.CharField(max_length=60, blank=True)
    extra_info = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name


class Ticket(TenantOwnedModel):
    reference = models.CharField(max_length=20)          # lisible, ex. TKT-7K3QX9AB
    public_token = models.CharField(max_length=64, unique=True)  # opaque, aléatoire : contenu du QR
    trip = models.ForeignKey("trips.Trip", on_delete=models.PROTECT, related_name="tickets")
    passenger = models.ForeignKey(Passenger, on_delete=models.PROTECT, related_name="tickets")
    seat = models.ForeignKey("fleet.Seat", null=True, blank=True, on_delete=models.PROTECT, related_name="tickets")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=10, choices=TicketStatus.choices, default=TicketStatus.ACTIVE, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "reference"], name="uniq_ticket_ref_per_tenant"),
            # Un siège = un seul billet ACTIF par voyage (garantie au niveau base de données).
            models.UniqueConstraint(
                fields=["trip", "seat"],
                condition=Q(status="ACTIVE", seat__isnull=False),
                name="uniq_active_seat_per_trip",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "trip", "status"])]
        ordering = ["-created_at"]

    def __str__(self):
        return self.reference


class PaymentRecord(models.Model):
    """Enregistrement informatif du paiement (pas de passerelle de paiement dans le MVP)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, default="CASH")  # CASH, MOBILE_MONEY, CARD, OTHER
    reference = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=12, default="RECORDED")
    created_at = models.DateTimeField(auto_now_add=True)


class TicketCancellation(models.Model):
    ticket = models.OneToOneField(Ticket, on_delete=models.CASCADE, related_name="cancellation")
    reason = models.CharField(max_length=255)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
