import pytest
from django.db import IntegrityError, transaction

from apps.ticketing.models import Ticket
from apps.ticketing import qr

from .conftest import client_for, make_user


def test_authorized_agent_creates_ticket_with_opaque_qr(world_a):
    t = world_a.sell(phone="+243990000000", payment_method="MOBILE_MONEY")
    assert t["reference"].startswith("TKT-") and t["status"] == "ACTIVE" and t["seat_code"]
    token, sig = t["qr_payload"].rsplit(".", 1)
    # Le QR ne contient aucune donnée personnelle ni identifiant séquentiel.
    assert "Mukendi" not in t["qr_payload"] and "+243" not in t["qr_payload"] and len(token) >= 20
    assert qr.parse_payload(t["qr_payload"]) == token
    assert qr.parse_payload(token + ".deadbeef0000") is None


def test_unauthorized_roles_cannot_create_ticket(world_a):
    body = {"trip": world_a.trip.id, "full_name": "Marie K"}
    assert world_a.scanner_c.post("/api/v1/tickets/", body, format="json").status_code == 403
    assert world_a.driver_c.post("/api/v1/tickets/", body, format="json").status_code == 403
    anon = client_for(make_user(None, None, "x@x.dev"))
    assert anon.post("/api/v1/tickets/", body, format="json").status_code == 403


def test_trip_must_be_open_for_sale(world_a):
    draft = world_a.new_trip("DRAFT", bus=world_a.bus)
    r = world_a.seller_c.post("/api/v1/tickets/", {"trip": draft.id, "full_name": "Marie K"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "trip_not_sellable"


def test_passenger_name_required_and_phone_setting(world_a):
    r = world_a.seller_c.post("/api/v1/tickets/", {"trip": world_a.trip.id, "full_name": ""}, format="json")
    assert r.status_code == 400
    world_a.tenant.settings = {"passenger_phone_required": True}
    world_a.tenant.save()
    r = client_for(type(world_a.seller).objects.get(pk=world_a.seller.pk)).post(
        "/api/v1/tickets/", {"trip": world_a.trip.id, "full_name": "Marie K"}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "passenger_phone_required"


def test_same_seat_cannot_be_sold_twice(world_a):
    seat = world_a.bus.seats.first()
    world_a.sell(seat=seat.id)
    r = world_a.seller_c.post("/api/v1/tickets/", {"trip": world_a.trip.id, "full_name": "Autre", "seat": seat.id}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "seat_taken"


def test_seat_from_another_bus_rejected(world_a, world_b):
    foreign = world_b.bus.seats.first()
    r = world_a.seller_c.post("/api/v1/tickets/", {"trip": world_a.trip.id, "full_name": "Autre", "seat": foreign.id}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "seat_invalid"


def test_database_constraint_blocks_double_active_seat(world_a):
    """Garantie ultime au niveau base, même si le code applicatif était contourné."""
    t = world_a.sell()
    first = Ticket.objects.get(pk=t["id"])
    with pytest.raises(IntegrityError), transaction.atomic():
        Ticket.objects.create(tenant=world_a.tenant, trip=first.trip, passenger=first.passenger, seat=first.seat,
                              price=1, currency="USD", reference="TKT-DUPLICAT", public_token="dup-token")


def test_capacity_cannot_be_exceeded(world_a):
    for i in range(world_a.trip.capacity):
        world_a.sell(name=f"Passager {i}")
    r = world_a.seller_c.post("/api/v1/tickets/", {"trip": world_a.trip.id, "full_name": "De trop"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "trip_full"
    seats = world_a.seller_c.get(f"/api/v1/trips/{world_a.trip.id}/available-seats/").json()
    assert seats["remaining"] == 0 and not any(s["available"] for s in seats["seats"])


def test_capacity_without_seat_selection(world_a):
    world_a.tenant.settings = {"seat_selection": False}
    world_a.tenant.save()
    seller = client_for(type(world_a.seller).objects.get(pk=world_a.seller.pk))
    for i in range(10):
        assert seller.post("/api/v1/tickets/", {"trip": world_a.trip.id, "full_name": f"P {i}"}, format="json").status_code == 201
    r = seller.post("/api/v1/tickets/", {"trip": world_a.trip.id, "full_name": "De trop"}, format="json")
    assert r.status_code == 409


def test_cancel_requires_reason_permission_and_frees_seat(world_a):
    t = world_a.sell()
    assert world_a.seller_c.post(f"/api/v1/tickets/{t['id']}/cancel/", {"reason": "erreur"}, format="json").status_code == 403
    assert world_a.admin_c.post(f"/api/v1/tickets/{t['id']}/cancel/", {"reason": ""}, format="json").status_code == 400
    r = world_a.admin_c.post(f"/api/v1/tickets/{t['id']}/cancel/", {"reason": "Demande du client"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert world_a.admin_c.post(f"/api/v1/tickets/{t['id']}/cancel/", {"reason": "encore"}, format="json").status_code == 409
    # le siège est de nouveau vendable
    again = world_a.sell(name="Nouveau", seat=t["seat"])
    assert again["seat"] == t["seat"]


def test_ticket_search_and_pdf(world_a):
    t = world_a.sell(name="Pascaline Ilunga", phone="+243970001122")
    for q in ("Pascaline", "970001122", t["reference"]):
        res = world_a.seller_c.get("/api/v1/tickets/", {"search": q}).json()
        assert res["count"] == 1, q
    pdf = world_a.seller_c.get(f"/api/v1/tickets/{t['id']}/pdf/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")


def test_tickets_are_immutable_via_api(world_a):
    t = world_a.sell()
    assert world_a.admin_c.patch(f"/api/v1/tickets/{t['id']}/", {"price": "1"}, format="json").status_code == 405
    assert world_a.admin_c.delete(f"/api/v1/tickets/{t['id']}/").status_code == 405


def test_agency_scoped_manager_cannot_see_other_agency_trips(world_a):
    from apps.agencies.models import Agency
    other = Agency.objects.create(tenant=world_a.tenant, name="Autre agence", city="Likasi")
    trip2 = world_a.new_trip("OPEN")
    trip2.agency = other
    trip2.save()
    ids = {r["id"] for r in world_a.manager_c.get("/api/v1/trips/").json()["results"]}
    assert world_a.trip.id in ids and trip2.id not in ids
    assert world_a.manager_c.get(f"/api/v1/trips/{trip2.id}/").status_code == 404
