"""Délégation des comptes : l'administrateur gère tout, le responsable d'agence gère son équipe, personne d'autre."""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Role, User
from apps.accounts.serializers import ensure_another_admin
from apps.agencies.models import Agency
from apps.fleet.models import Driver
from tests.conftest import client_for, make_user

U = "/api/v1/users/"
PW = "Str0ng!Passw0rd"


def new_user(client, email, role, **extra):
    return client.post(U, {"email": email, "full_name": email.split("@")[0], "role": role, "password": PW, **extra}, format="json")


@pytest.fixture
def team(world_a):
    """Deux agences : le gestionnaire (agence A) a un guichetier chez lui et un autre dans l'agence B."""
    w = world_a
    w.agency_b = Agency.objects.create(tenant=w.tenant, name="Agence B", city="Kolwezi")
    w.mine = make_user(w.tenant, Role.TICKET_AGENT, "mine@a.test", agency=w.agency)
    w.theirs = make_user(w.tenant, Role.TICKET_AGENT, "theirs@a.test", agency=w.agency_b)
    return w


def test_manager_sees_only_his_agencys_team(team):
    emails = {u["email"] for u in team.manager_c.get(U).json()["results"]}
    assert "mine@a.test" in emails
    assert not {"theirs@a.test", "admin@a.test", "manager@a.test"} & emails  # ni autre agence, ni encadrement


def test_manager_can_create_team_members_only_in_his_agency(team):
    r = new_user(team.manager_c, "new@a.test", Role.TICKET_AGENT, agency=team.agency_b.id)  # tente une autre agence
    assert r.status_code == 201
    assert Membership.objects.get(user__email="new@a.test").agency_id == team.agency.id  # forcé à la sienne
    for role in (Role.COMPANY_ADMIN, Role.AGENCY_MANAGER):
        assert new_user(team.manager_c, f"{role}@a.test".lower(), role).status_code == 400
    assert not User.objects.filter(email__in=["company_admin@a.test", "agency_manager@a.test"]).exists()


def test_manager_cannot_grant_permissions_or_touch_others(team):
    assert new_user(team.manager_c, "p@a.test", Role.TICKET_AGENT, extra_permissions=["user.manage"]).status_code == 400
    assert team.manager_c.patch(f"{U}{team.theirs.id}/", {"full_name": "x"}, format="json").status_code == 404  # autre agence
    assert team.manager_c.patch(f"{U}{team.admin.id}/", {"full_name": "x"}, format="json").status_code == 404  # admin invisible
    r = team.manager_c.patch(f"{U}{team.mine.id}/", {"role": Role.AGENCY_MANAGER}, format="json")  # pas de promotion
    assert r.status_code == 400
    assert team.manager_c.delete(f"{U}{team.theirs.id}/").status_code == 404


def test_manager_without_agency_manages_nobody(team):
    orphan = make_user(team.tenant, Role.AGENCY_MANAGER, "orphan@a.test", agency=None)
    c = client_for(orphan)
    assert c.get(U).json()["results"] == []
    assert new_user(c, "z@a.test", Role.TICKET_AGENT).status_code == 400


@pytest.mark.parametrize("who", ["seller_c", "scanner_c", "driver_c"])
def test_other_roles_cannot_manage_accounts(team, who):
    c = getattr(team, who)
    assert c.get(U).status_code == 403
    assert new_user(c, "x@a.test", Role.DRIVER).status_code == 403


def test_admin_must_give_an_agency_to_bound_roles(team):
    assert new_user(team.admin_c, "s@a.test", Role.TICKET_AGENT).status_code == 400
    assert new_user(team.admin_c, "m@a.test", Role.AGENCY_MANAGER).status_code == 400
    assert new_user(team.admin_c, "s@a.test", Role.TICKET_AGENT, agency=team.agency.id).status_code == 201
    assert new_user(team.admin_c, "b@a.test", Role.BOARDING_AGENT).status_code == 201  # agence facultative


def test_creating_a_driver_account_creates_the_linked_driver_profile(team):
    r = new_user(team.manager_c, "chauf@a.test", Role.DRIVER, phone="+243970000000")
    assert r.status_code == 201
    d = Driver.objects.get(user__email="chauf@a.test")
    assert d.tenant_id == team.tenant.id and d.phone == "+243970000000"


def test_nobody_can_lock_themselves_out_or_self_promote(team):
    assert team.admin_c.delete(f"{U}{team.admin.id}/").status_code == 400
    assert team.admin_c.patch(f"{U}{team.admin.id}/", {"role": Role.TICKET_AGENT, "agency": team.agency.id}, format="json").status_code == 400
    assert team.admin_c.patch(f"{U}{team.admin.id}/", {"is_active": False}, format="json").status_code == 400
    assert team.admin_c.patch(f"{U}{team.admin.id}/", {"full_name": "Nouveau nom"}, format="json").status_code == 200  # le reste est permis


def test_company_keeps_at_least_one_active_admin(team):
    with pytest.raises(Exception) as e:
        ensure_another_admin(team.tenant, exclude_user=team.admin)
    assert "au moins un administrateur" in str(e.value)
    second = make_user(team.tenant, Role.COMPANY_ADMIN, "admin2@a.test")
    ensure_another_admin(team.tenant, exclude_user=team.admin)  # un autre admin actif existe : pas d'erreur
    assert second.is_active


def test_deactivate_then_reactivate_restores_login(team):
    c = APIClient()
    login = lambda: c.post("/api/v1/auth/login/", {"email": "mine@a.test", "password": "Passw0rd!x"}, format="json").status_code
    assert login() == 200
    assert team.manager_c.delete(f"{U}{team.mine.id}/").status_code == 204
    assert login() == 401
    assert team.manager_c.get(f"{U}{team.mine.id}/").status_code == 200  # reste visible (traçabilité)
    assert team.manager_c.patch(f"{U}{team.mine.id}/", {"is_active": True}, format="json").status_code == 200
    assert login() == 200  # l'adhésion est réactivée avec le compte


def test_admin_password_reset_and_self_service_change(team):
    assert team.admin_c.patch(f"{U}{team.mine.id}/", {"password": PW}, format="json").status_code == 200
    c = APIClient()
    assert c.post("/api/v1/auth/login/", {"email": "mine@a.test", "password": PW}, format="json").status_code == 200
    team.mine.refresh_from_db()  # le mot de passe a changé en base
    me = client_for(team.mine)
    assert me.post("/api/v1/auth/change-password/", {"current_password": "faux", "new_password": "N3w!Passw0rdx"}, format="json").status_code == 400
    assert me.post("/api/v1/auth/change-password/", {"current_password": PW, "new_password": "123"}, format="json").status_code == 400
    assert me.post("/api/v1/auth/change-password/", {"current_password": PW, "new_password": "N3w!Passw0rdx"}, format="json").status_code == 200
    assert c.post("/api/v1/auth/login/", {"email": "mine@a.test", "password": "N3w!Passw0rdx"}, format="json").status_code == 200
