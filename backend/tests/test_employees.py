"""
test_employees.py
--------------------------------------------------------------------
Πολλαπλά logins ανά συνεργείο (owner + υπάλληλοι, δες models.Employee):
- owner δημιουργεί/απενεργοποιεί/σβήνει υπαλλήλους, υπάλληλος ΔΕΝ μπορεί
- υπάλληλος βλέπει ΤΑ ΙΔΙΑ δεδομένα με τον owner (ίδιο workshop_id)
- υπάλληλος ΔΕΝ μπορεί να διαγράψει τον λογαριασμό (owner-only)
- απενεργοποιημένος υπάλληλος αποκλείεται ΑΜΕΣΩΣ, ακόμη και με valid token
- ξεχωριστό token_epoch: αλλαγή κωδικού του ενός ΔΕΝ αποσυνδέει τον άλλο
- audit trail: DclEntry/AadeLog καταγράφουν ΠΟΙΟΣ το έκανε
--------------------------------------------------------------------
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import AadeLog, DclEntry, Employee, Settings, Workshop, db  # noqa: E402

OWNER_EMAIL = "emp.owner.test@example.com"
EMPLOYEE_EMAIL = "emp.staff.test@example.com"
OWNER_PASSWORD = "ownerpass1234"
EMPLOYEE_PASSWORD = "staffpass1234"


def client():
    app.config["TESTING"] = True
    return app.test_client()


def _register_owner(c):
    res = c.post(
        "/api/auth/register",
        json={
            "name": "Employee Test Garage",
            "email": OWNER_EMAIL,
            "password": OWNER_PASSWORD,
            "businessType": "garage",
            "termsAccepted": True,
        },
    )
    assert res.status_code == 201, res.get_json()
    return res.get_json()["accessToken"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _cleanup():
    with app.app_context():
        ws = Workshop.query.filter_by(email=OWNER_EMAIL).first()
        if ws:
            # Καθάρισε ΠΡΩΤΑ τα FKs προς employees (ίδιο μοτίβο με
            # auth.delete_employee) — χωρίς αυτό, ένα DclEntry/AadeLog
            # μένει με ορφανό created_by_employee_id/actor_employee_id
            # αφού διαγραφεί ο Employee, γιατί το SQLite (dev/tests) δεν
            # επιβάλλει FK constraints by default.
            AadeLog.query.filter_by(workshop_id=ws.id).update(
                {"actor_employee_id": None}
            )
            DclEntry.query.filter_by(workshop_id=ws.id).update(
                {"created_by_employee_id": None}
            )
            Employee.query.filter_by(workshop_id=ws.id).delete()
            AadeLog.query.filter_by(workshop_id=ws.id).delete()
            DclEntry.query.filter_by(workshop_id=ws.id).delete()
            Settings.query.filter_by(workshop_id=ws.id).delete()
            db.session.delete(ws)
        Employee.query.filter_by(email=EMPLOYEE_EMAIL).delete()
        db.session.commit()


def _create_employee(c, owner_token):
    res = c.post(
        "/api/employees",
        json={"name": "Staff Member", "email": EMPLOYEE_EMAIL, "password": EMPLOYEE_PASSWORD},
        headers=_auth(owner_token),
    )
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def test_owner_creates_employee_and_employee_logs_in():
    _cleanup()
    c = client()
    try:
        owner_token = _register_owner(c)
        created = _create_employee(c, owner_token)
        assert created["email"] == EMPLOYEE_EMAIL
        assert created["isActive"] is True

        login_res = c.post(
            "/api/auth/login",
            json={"email": EMPLOYEE_EMAIL, "password": EMPLOYEE_PASSWORD},
        )
        assert login_res.status_code == 200, login_res.get_json()
        data = login_res.get_json()
        assert data["actor"]["type"] == "employee"
        assert data["actor"]["email"] == EMPLOYEE_EMAIL
        # Το "workshop" key δείχνει ΠΑΝΤΑ την επιχείρηση, όχι τον υπάλληλο.
        assert data["workshop"]["email"] == OWNER_EMAIL
    finally:
        _cleanup()


def test_employee_sees_same_workshop_data_as_owner():
    _cleanup()
    c = client()
    try:
        owner_token = _register_owner(c)
        _create_employee(c, owner_token)
        employee_token = c.post(
            "/api/auth/login",
            json={"email": EMPLOYEE_EMAIL, "password": EMPLOYEE_PASSWORD},
        ).get_json()["accessToken"]

        res = c.get("/api/dcl/entries", headers=_auth(employee_token))
        assert res.status_code == 200
    finally:
        _cleanup()


def test_employee_cannot_manage_employees_or_delete_account():
    _cleanup()
    c = client()
    try:
        owner_token = _register_owner(c)
        _create_employee(c, owner_token)
        employee_token = c.post(
            "/api/auth/login",
            json={"email": EMPLOYEE_EMAIL, "password": EMPLOYEE_PASSWORD},
        ).get_json()["accessToken"]

        create_res = c.post(
            "/api/employees",
            json={"name": "Another", "email": "should.fail@example.com", "password": "whatever123"},
            headers=_auth(employee_token),
        )
        assert create_res.status_code == 403

        delete_res = c.delete(
            "/api/account",
            json={"password": EMPLOYEE_PASSWORD},
            headers=_auth(employee_token),
        )
        assert delete_res.status_code == 403

        # Owner ΜΠΟΡΕΙ να διαχειριστεί υπαλλήλους.
        list_res = c.get("/api/employees", headers=_auth(owner_token))
        assert list_res.status_code == 200
        assert len(list_res.get_json()) == 1
    finally:
        _cleanup()


def test_deactivated_employee_blocked_immediately():
    _cleanup()
    c = client()
    try:
        owner_token = _register_owner(c)
        employee = _create_employee(c, owner_token)
        employee_token = c.post(
            "/api/auth/login",
            json={"email": EMPLOYEE_EMAIL, "password": EMPLOYEE_PASSWORD},
        ).get_json()["accessToken"]

        # Δουλεύει πριν την απενεργοποίηση.
        assert c.get("/api/dcl/entries", headers=_auth(employee_token)).status_code == 200

        deactivate_res = c.patch(
            f"/api/employees/{employee['id']}",
            json={"isActive": False},
            headers=_auth(owner_token),
        )
        assert deactivate_res.status_code == 200
        assert deactivate_res.get_json()["isActive"] is False

        # ΙΔΙΟ (ήδη εκδομένο) access token, ΤΩΡΑ μπλοκάρεται — χωρίς να
        # χρειαστεί να λήξει ή να γίνει epoch mismatch.
        blocked_res = c.get("/api/dcl/entries", headers=_auth(employee_token))
        assert blocked_res.status_code == 401

        # Ούτε login πλέον.
        login_res = c.post(
            "/api/auth/login",
            json={"email": EMPLOYEE_EMAIL, "password": EMPLOYEE_PASSWORD},
        )
        assert login_res.status_code == 401
    finally:
        _cleanup()


def test_password_change_epoch_isolated_between_owner_and_employee():
    _cleanup()
    c = client()
    try:
        owner_token = _register_owner(c)
        _create_employee(c, owner_token)
        employee_token = c.post(
            "/api/auth/login",
            json={"email": EMPLOYEE_EMAIL, "password": EMPLOYEE_PASSWORD},
        ).get_json()["accessToken"]

        # Ο υπάλληλος αλλάζει ΤΟΝ ΔΙΚΟ ΤΟΥ κωδικό.
        change_res = c.put(
            "/api/auth/password",
            json={"currentPassword": EMPLOYEE_PASSWORD, "newPassword": "newstaffpass123"},
            headers=_auth(employee_token),
        )
        assert change_res.status_code == 200

        # Το ΠΑΛΙΟ access token του υπαλλήλου έγινε άκυρο (epoch mismatch).
        assert c.get("/api/dcl/entries", headers=_auth(employee_token)).status_code == 401

        # Ο owner ΔΕΝ επηρεάστηκε — το δικό του token δουλεύει ακόμα.
        assert c.get("/api/dcl/entries", headers=_auth(owner_token)).status_code == 200
    finally:
        _cleanup()


def test_dcl_entry_records_creating_employee():
    _cleanup()
    c = client()
    try:
        owner_token = _register_owner(c)
        _create_employee(c, owner_token)
        employee_token = c.post(
            "/api/auth/login",
            json={"email": EMPLOYEE_EMAIL, "password": EMPLOYEE_PASSWORD},
        ).get_json()["accessToken"]

        with app.app_context():
            workshop = Workshop.query.filter_by(email=OWNER_EMAIL).first()
            settings = Settings(workshop_id=workshop.id, branch=0, aade_username="testuser")
            settings.aade_subscription_key = "testkey"
            db.session.add(settings)
            db.session.commit()

        create_res = c.post(
            "/api/dcl/entry",
            json={"plate": "ABC1234", "branch": 0},
            headers=_auth(employee_token),
        )
        assert create_res.status_code == 201, create_res.get_json()

        list_res = c.get("/api/dcl/entries", headers=_auth(owner_token))
        entries = list_res.get_json()
        assert len(entries) == 1
        assert entries[0]["createdByName"] == "Staff Member"
    finally:
        _cleanup()
