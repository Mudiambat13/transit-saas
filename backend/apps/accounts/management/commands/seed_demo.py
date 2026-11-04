"""Données de démonstration : `python manage.py seed_demo` (idempotent, jamais en production)."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import Membership, Role, User
from apps.agencies.models import Agency
from apps.fleet.models import Bus, Driver
from apps.tenants.models import Plan, Subscription, Tenant
from apps.trips.models import Trip, TripDriver

PASSWORD = "Demo12345!"


class Command(BaseCommand):
    help = "Crée une compagnie de démonstration, ses utilisateurs, un bus et deux voyages."

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("seed_demo est réservé au mode développement (DJANGO_DEBUG=1).")
        root, _ = User.objects.get_or_create(email="superadmin@transit.local", defaults={
            "full_name": "Super Admin", "is_platform_admin": True, "is_staff": True, "is_superuser": True})
        root.set_password(PASSWORD)
        root.save()
        plan, _ = Plan.objects.get_or_create(name="Pro", defaults={"price": 99, "max_agencies": 10, "max_users": 50})
        tenant, _ = Tenant.objects.get_or_create(slug="trans-katanga", defaults={
            "name": "Trans Katanga Express", "currency": "USD", "timezone": "Africa/Lubumbashi",
            "contact_phone": "+243 990 000 000", "settings": {"seat_selection": True}})
        if not tenant.subscriptions.exists():
            Subscription.objects.create(tenant=tenant, plan=plan)
        agency, _ = Agency.objects.get_or_create(tenant=tenant, name="Agence Lubumbashi", defaults={"city": "Lubumbashi"})
        Agency.objects.get_or_create(tenant=tenant, name="Agence Kolwezi", defaults={"city": "Kolwezi"})

        for email, role, name in [
            ("admin@trans-katanga.local", Role.COMPANY_ADMIN, "Admin Compagnie"),
            ("guichet@trans-katanga.local", Role.TICKET_AGENT, "Agent Guichet"),
            ("embarquement@trans-katanga.local", Role.BOARDING_AGENT, "Agent Embarquement"),
        ]:
            u, _ = User.objects.get_or_create(email=email, defaults={"full_name": name})
            u.set_password(PASSWORD)
            u.save()
            Membership.objects.get_or_create(user=u, tenant=tenant, defaults={"role": role})

        bus, _ = Bus.objects.get_or_create(tenant=tenant, plate="KAT-1234", defaults={"brand": "Scania", "model": "Marcopolo", "capacity": 50})
        bus.generate_seats()
        driver, _ = Driver.objects.get_or_create(tenant=tenant, full_name="Patrice Kabongo", defaults={"phone": "+243 970 111 222"})
        bus2, _ = Bus.objects.get_or_create(tenant=tenant, plate="KAT-5678", defaults={"brand": "Yutong", "capacity": 45})
        bus2.generate_seats()

        for ref, bus_, dest, hours, status in [("V-DEMO-001", bus, "Kolwezi", 6, "OPEN"), ("V-DEMO-002", bus2, "Likasi", 30, "DRAFT")]:
            trip, created = Trip.objects.get_or_create(tenant=tenant, reference=ref, defaults={
                "agency": agency, "origin": "Lubumbashi", "destination": dest, "bus": bus_, "capacity": bus_.capacity,
                "departure_at": timezone.now() + timedelta(hours=hours), "price": "35.00", "currency": "USD", "status": status})
            if created:
                TripDriver.objects.create(trip=trip, driver=driver)
        self.stdout.write(self.style.SUCCESS(f"Démo prête. Mot de passe de tous les comptes : {PASSWORD}"))
        self.stdout.write("  Super Admin : superadmin@transit.local")
        self.stdout.write("  Compagnie   : admin@ / guichet@ / embarquement@trans-katanga.local")
