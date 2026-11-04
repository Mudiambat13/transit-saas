"""Ventes concurrentes : un siège / une place ne peut jamais être vendu(e) deux fois."""
import threading

import pytest
from django.db import connection

from apps.accounts.exceptions import BusinessError
from apps.ticketing import services
from apps.ticketing.models import Ticket

pytestmark = pytest.mark.django_db(transaction=True)


def run_parallel(n, fn):
    outcomes, barrier = [], threading.Barrier(n)

    def worker(i):
        try:
            barrier.wait()
            outcomes.append(("ok", fn(i)))
        except BusinessError as exc:
            outcomes.append(("refused", exc.code))
        except Exception as exc:  # noqa: BLE001
            outcomes.append(("error", repr(exc)))
        finally:
            connection.close()

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return outcomes


def test_same_seat_sold_by_many_agents_at_once(world_a):
    w, seat = world_a, world_a.bus.seats.first()
    out = run_parallel(8, lambda i: services.create_ticket(
        tenant=w.tenant, actor=w.seller, trip_id=w.trip.id, passenger={"full_name": f"Client {i}"}, seat_id=seat.id))
    assert not [o for o in out if o[0] == "error"], out
    assert sum(1 for o in out if o[0] == "ok") == 1
    assert {o[1] for o in out if o[0] == "refused"} == {"seat_taken"}
    assert Ticket.objects.filter(trip=w.trip, seat=seat, status="ACTIVE").count() == 1


def test_capacity_never_exceeded_under_concurrency(world_a):
    w = world_a
    for i in range(8):  # 8 places vendues sur 10 : il reste 2 places
        w.sell(name=f"Déjà {i}")
    out = run_parallel(8, lambda i: services.create_ticket(
        tenant=w.tenant, actor=w.seller, trip_id=w.trip.id, passenger={"full_name": f"Course {i}"}))
    assert not [o for o in out if o[0] == "error"], out
    assert sum(1 for o in out if o[0] == "ok") == 2
    assert {o[1] for o in out if o[0] == "refused"} <= {"trip_full"}
    assert Ticket.objects.filter(trip=w.trip, status="ACTIVE").count() == 10
