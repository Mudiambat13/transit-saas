from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Role, User
from apps.agencies.models import Agency
from apps.fleet.models import Bus
from apps.tenants.models import Plan, Subscription, Tenant
from apps.trips.models import Trip


def make_tenant(slug, **kw):
    return Tenant.objects.create(name=f"Compagnie {slug}", slug=slug, **kw)


def make_user(tenant, role, email, agency=None, password="Passw0rd!x"):
    u = User.objects.create_user(email=email, password=password, full_name=email.split("@")[0])
    if tenant is not None:
        Membership.objects.create(user=u, tenant=tenant, role=role, agency=agency)
    return u


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class World:
    """Une compagnie complète : agence, bus (10 places), utilisateurs de chaque rôle, voyage."""

    def __init__(self, slug):
        self.tenant = make_tenant(slug)
        t = self.tenant
        self.agency = Agency.objects.create(tenant=t, name=f"Agence {slug}", city="Lubumbashi")
        self.admin = make_user(t, Role.COMPANY_ADMIN, f"admin@{slug}.test")
        self.manager = make_user(t, Role.AGENCY_MANAGER, f"manager@{slug}.test", agency=self.agency)
        self.seller = make_user(t, Role.TICKET_AGENT, f"seller@{slug}.test")
        self.scanner = make_user(t, Role.BOARDING_AGENT, f"scanner@{slug}.test")
        self.driver_user = make_user(t, Role.DRIVER, f"driver@{slug}.test")
        self.bus = Bus.objects.create(tenant=t, plate=f"{slug.upper()}-001", capacity=10)
        self.bus.generate_seats()
        self.trip = self.new_trip("OPEN")
        self.admin_c, self.seller_c, self.scanner_c = client_for(self.admin), client_for(self.seller), client_for(self.scanner)
        self.manager_c, self.driver_c = client_for(self.manager), client_for(self.driver_user)

    def new_trip(self, status="OPEN", ref=None, bus=None, hours=48):
        n = Trip.objects.filter(tenant=self.tenant).count() + 1
        return Trip.objects.create(
            tenant=self.tenant, reference=ref or f"V-{n:03d}", agency=self.agency, origin="Lubumbashi",
            destination="Kinshasa", departure_at=timezone.now() + timedelta(hours=hours), bus=bus or self.bus,
            capacity=(bus or self.bus).capacity, price="120.00", currency="USD", status=status, created_by=self.admin,
        )

    def sell(self, trip=None, name="Jean Mukendi", **extra):
        trip = trip or self.trip
        r = self.seller_c.post("/api/v1/tickets/", {"trip": trip.id, "full_name": name, **extra}, format="json")
        assert r.status_code == 201, r.content
        return r.json()


@pytest.fixture
def world_a(db):
    return World("alpha")


@pytest.fixture
def world_b(db):
    return World("beta")


@pytest.fixture
def platform_admin(db):
    u = User.objects.create_user(email="root@platform.test", password="Passw0rd!x", is_platform_admin=True)
    return u


@pytest.fixture
def platform_client(platform_admin):
    return client_for(platform_admin)
