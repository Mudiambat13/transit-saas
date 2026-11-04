"""Isolation multi-tenant : une compagnie ne voit ni ne modifie jamais les données d'une autre."""
from apps.accounts.models import User

from .conftest import client_for, make_user


def test_lists_only_contain_own_tenant_data(world_a, world_b):
    world_a.sell()
    world_b.sell()
    for path in ("agencies", "buses", "trips", "tickets"):
        ids_a = {r["id"] for r in world_a.admin_c.get(f"/api/v1/{path}/").json()["results"]}
        ids_b = {r["id"] for r in world_b.admin_c.get(f"/api/v1/{path}/").json()["results"]}
        assert ids_a and ids_b and not (ids_a & ids_b), path


def test_cannot_read_other_tenant_resource_by_guessing_id(world_a, world_b):
    ticket_b = world_b.sell()
    assert world_a.admin_c.get(f"/api/v1/trips/{world_b.trip.id}/").status_code == 404
    assert world_a.admin_c.get(f"/api/v1/tickets/{ticket_b['id']}/").status_code == 404
    assert world_a.admin_c.get(f"/api/v1/tickets/{ticket_b['id']}/pdf/").status_code == 404
    assert world_a.admin_c.get(f"/api/v1/trips/{world_b.trip.id}/boarding/").status_code == 404
    assert world_a.admin_c.get(f"/api/v1/trips/{world_b.trip.id}/manifests/").status_code == 404
    assert world_a.admin_c.get(f"/api/v1/trips/{world_b.trip.id}/available-seats/").status_code == 404


def test_cannot_modify_or_delete_other_tenant_resource(world_a, world_b):
    assert world_a.admin_c.patch(f"/api/v1/agencies/{world_b.agency.id}/", {"name": "Hack"}, format="json").status_code == 404
    assert world_a.admin_c.delete(f"/api/v1/buses/{world_b.bus.id}/").status_code == 404
    assert world_a.admin_c.post(f"/api/v1/trips/{world_b.trip.id}/cancel/").status_code == 404
    ticket_b = world_b.sell()
    assert world_a.admin_c.post(f"/api/v1/tickets/{ticket_b['id']}/cancel/", {"reason": "piratage"}, format="json").status_code == 404
    world_b.agency.refresh_from_db()
    assert world_b.agency.name != "Hack"


def test_cannot_reference_foreign_objects_in_writes(world_a, world_b):
    payload = {"origin": "A", "destination": "B", "departure_at": "2030-01-01T08:00:00Z", "price": "10",
               "agency": world_b.agency.id, "bus": world_a.bus.id}
    r = world_a.admin_c.post("/api/v1/trips/", payload, format="json")
    assert r.status_code == 400 and "agency" in r.json()
    payload.update(agency=world_a.agency.id, bus=world_b.bus.id)
    r = world_a.admin_c.post("/api/v1/trips/", payload, format="json")
    assert r.status_code == 400 and "bus" in r.json()


def test_cannot_sell_on_other_tenant_trip_or_scan_there(world_a, world_b):
    r = world_a.seller_c.post("/api/v1/tickets/", {"trip": world_b.trip.id, "full_name": "X Y"}, format="json")
    assert r.status_code == 404
    r = world_a.scanner_c.post("/api/v1/boarding/scan/", {"trip": world_b.trip.id, "code": "x.y"}, format="json")
    assert r.status_code == 404


def test_other_tenant_ticket_qr_is_invalid_in_my_tenant(world_a, world_b):
    ticket_b = world_b.sell()
    world_a.trip.status = "BOARDING"
    world_a.trip.save()
    r = world_a.scanner_c.post("/api/v1/boarding/scan/", {"trip": world_a.trip.id, "code": ticket_b["qr_payload"]}, format="json")
    assert r.json()["result"] == "INVALID"


def test_users_endpoint_is_tenant_scoped(world_a, world_b):
    emails = {u["email"] for u in world_a.admin_c.get("/api/v1/users/").json()["results"]}
    assert all(e.endswith("@alpha.test") for e in emails) and emails
    other = User.objects.get(email="seller@beta.test")
    assert world_a.admin_c.get(f"/api/v1/users/{other.id}/").status_code == 404
    assert world_a.admin_c.patch(f"/api/v1/users/{other.id}/", {"full_name": "pwned"}, format="json").status_code == 404


def test_user_without_active_tenant_has_no_business_access(db):
    loner = make_user(None, None, "loner@test.dev")
    c = client_for(loner)
    for path in ("agencies", "trips", "tickets", "buses"):
        assert c.get(f"/api/v1/{path}/").status_code == 403
    assert c.get("/api/v1/reports/dashboard/").status_code == 403


def test_suspended_tenant_is_blocked(world_a, platform_client):
    r = platform_client.post(f"/api/v1/platform/tenants/{world_a.tenant.id}/suspend/", {"reason": "impayé"}, format="json")
    assert r.status_code == 200
    def fresh():  # chaque requête réelle recharge l'utilisateur ; on le simule ici
        return client_for(User.objects.get(email="admin@alpha.test"))

    assert fresh().get("/api/v1/trips/").status_code == 403
    login = fresh().__class__().post("/api/v1/auth/login/", {"email": "admin@alpha.test", "password": "Passw0rd!x"}, format="json")
    assert login.status_code == 403
    platform_client.post(f"/api/v1/platform/tenants/{world_a.tenant.id}/reactivate/")
    assert fresh().get("/api/v1/trips/").status_code == 200


def test_platform_admin_has_no_business_data_access(platform_client, world_a):
    assert platform_client.get("/api/v1/tickets/").status_code == 403
    assert platform_client.get("/api/v1/trips/").status_code == 403
    assert platform_client.get("/api/v1/platform/metrics/").status_code == 200


def test_company_users_cannot_use_platform_api(world_a):
    assert world_a.admin_c.get("/api/v1/platform/tenants/").status_code == 403
    assert world_a.admin_c.post("/api/v1/platform/tenants/", {"name": "X", "slug": "x"}, format="json").status_code == 403
    assert world_a.admin_c.get("/api/v1/platform/metrics/").status_code == 403
