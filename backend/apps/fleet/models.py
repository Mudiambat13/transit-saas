from django.db import models

from apps.tenants.models import TenantOwnedModel


class BusStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "En service"
    MAINTENANCE = "MAINTENANCE", "En maintenance"
    RETIRED = "RETIRED", "Retiré"


class Bus(TenantOwnedModel):
    plate = models.CharField("immatriculation", max_length=20)
    brand = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=60, blank=True)
    capacity = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=12, choices=BusStatus.choices, default=BusStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "buses"
        constraints = [models.UniqueConstraint(fields=["tenant", "plate"], name="uniq_bus_plate_per_tenant")]
        ordering = ["plate"]

    def __str__(self):
        return self.plate

    def generate_seats(self, layout=None):
        """Crée les sièges 1..capacity (idempotent). `layout` : liste de codes optionnelle."""
        codes = layout or [str(i) for i in range(1, self.capacity + 1)]
        existing = set(self.seats.values_list("code", flat=True))
        Seat.objects.bulk_create([Seat(bus=self, code=c) for c in codes if c not in existing])


class Seat(models.Model):
    bus = models.ForeignKey(Bus, on_delete=models.CASCADE, related_name="seats")
    code = models.CharField(max_length=8)
    category = models.CharField(max_length=20, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bus", "code"], name="uniq_seat_code_per_bus")]

    def __str__(self):
        return f"{self.bus.plate}-{self.code}"


class Driver(TenantOwnedModel):
    full_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40, blank=True)
    license_number = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    # Compte optionnel pour la consultation en lecture seule du manifeste.
    user = models.OneToOneField("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="driver_profile")

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name
