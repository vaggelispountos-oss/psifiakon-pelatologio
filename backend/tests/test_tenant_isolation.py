"""
test_tenant_isolation.py
--------------------------------------------------------------------
Επιβεβαιώνει ότι δύο workshops δεν βλέπουν ποτέ δεδομένα το ένα του
άλλου. Το app.py φιλτράρει χειροκίνητα με filter_by(workshop_id=...)
σε ~28 σημεία — αυτό το test καλύπτει τα κύρια endpoints (customers,
fleet-vehicles, ocr-metrics, dcl-entries) ώστε μια μελλοντική αλλαγή
που ξεχάσει το φίλτρο να σπάει αμέσως το test suite.
--------------------------------------------------------------------
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import Customer, DclEntry, FleetVehicle, OcrMetric, Workshop, db  # noqa: E402

WORKSHOP_A_EMAIL = "tenant.a.test@example.com"
WORKSHOP_B_EMAIL = "tenant.b.test@example.com"
PASSWORD = "testpass1234"


def client():
    app.config["TESTING"] = True
    return app.test_client()


def _register(c, email):
    res = c.post(
        "/api/auth/register",
        json={
            "name": f"Tenant Test {email}",
            "email": email,
            "password": PASSWORD,
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
        for email in (WORKSHOP_A_EMAIL, WORKSHOP_B_EMAIL):
            workshop = Workshop.query.filter_by(email=email).first()
            if workshop is None:
                continue
            Customer.query.filter_by(workshop_id=workshop.id).delete()
            FleetVehicle.query.filter_by(workshop_id=workshop.id).delete()
            OcrMetric.query.filter_by(workshop_id=workshop.id).delete()
            DclEntry.query.filter_by(workshop_id=workshop.id).delete()
            db.session.delete(workshop)
        db.session.commit()


def test_fleet_vehicles_isolated_between_workshops():
    _cleanup()
    c = client()
    try:
        token_a = _register(c, WORKSHOP_A_EMAIL)
        token_b = _register(c, WORKSHOP_B_EMAIL)

        created = c.post(
            "/api/fleet-vehicles",
            json={"plate": "ABC1234", "label": "A-only van"},
            headers=_auth(token_a),
        )
        assert created.status_code == 201
        vehicle_id = created.get_json()["id"]

        # Β δεν βλέπει το όχημα του Α στη λίστα
        list_b = c.get("/api/fleet-vehicles", headers=_auth(token_b))
        assert list_b.status_code == 200
        assert list_b.get_json() == []

        # Α το βλέπει κανονικά
        list_a = c.get("/api/fleet-vehicles", headers=_auth(token_a))
        assert list_a.status_code == 200
        assert len(list_a.get_json()) == 1

        # Β δεν μπορεί να το επεξεργαστεί ή να το σβήσει (404, όχι 200/403)
        patch_b = c.patch(
            f"/api/fleet-vehicles/{vehicle_id}",
            json={"label": "hijacked"},
            headers=_auth(token_b),
        )
        assert patch_b.status_code == 404

        delete_b = c.delete(
            f"/api/fleet-vehicles/{vehicle_id}", headers=_auth(token_b)
        )
        assert delete_b.status_code == 404

        # Και όντως δεν αλλοιώθηκε
        list_a_after = c.get("/api/fleet-vehicles", headers=_auth(token_a))
        assert list_a_after.get_json()[0]["label"] == "A-only van"
    finally:
        _cleanup()


def test_customers_isolated_between_workshops():
    _cleanup()
    c = client()
    try:
        token_a = _register(c, WORKSHOP_A_EMAIL)
        token_b = _register(c, WORKSHOP_B_EMAIL)

        with app.app_context():
            workshop_a = Workshop.query.filter_by(email=WORKSHOP_A_EMAIL).first()
            customer = Customer(
                workshop_id=workshop_a.id, plate="XYZ5678", name="Secret Customer A"
            )
            db.session.add(customer)
            db.session.commit()
            customer_id = customer.id

        list_b = c.get("/api/customers", headers=_auth(token_b))
        assert list_b.status_code == 200
        assert list_b.get_json() == []

        list_a = c.get("/api/customers", headers=_auth(token_a))
        assert len(list_a.get_json()) == 1

        plates_b = c.get("/api/customers/plates", headers=_auth(token_b))
        assert plates_b.status_code == 200
        assert plates_b.get_json() == []

        plates_a = c.get("/api/customers/plates", headers=_auth(token_a))
        assert plates_a.get_json() == [{"plate": "XYZ5678", "name": "Secret Customer A"}]

        patch_b = c.patch(
            f"/api/customers/{customer_id}",
            json={"name": "hijacked"},
            headers=_auth(token_b),
        )
        assert patch_b.status_code == 404
    finally:
        _cleanup()


def test_ocr_metrics_isolated_between_workshops():
    _cleanup()
    c = client()
    try:
        token_a = _register(c, WORKSHOP_A_EMAIL)
        token_b = _register(c, WORKSHOP_B_EMAIL)

        created = c.post(
            "/api/ocr/metrics",
            json={"mode": "car", "engine": "test", "ocrPlate": "AAA1111"},
            headers=_auth(token_a),
        )
        assert created.status_code == 201
        metric_id = created.get_json()["id"]

        list_b = c.get("/api/ocr/metrics", headers=_auth(token_b))
        assert list_b.status_code == 200
        assert list_b.get_json() == []

        summary_b = c.get("/api/ocr/metrics/summary", headers=_auth(token_b))
        assert summary_b.status_code == 200
        assert summary_b.get_json()["total"] == 0

        patch_b = c.patch(
            f"/api/ocr/metrics/{metric_id}",
            json={"finalPlate": "AAA1111"},
            headers=_auth(token_b),
        )
        assert patch_b.status_code == 404
    finally:
        _cleanup()


def test_dcl_entries_isolated_between_workshops():
    _cleanup()
    c = client()
    try:
        token_a = _register(c, WORKSHOP_A_EMAIL)
        token_b = _register(c, WORKSHOP_B_EMAIL)

        with app.app_context():
            workshop_a = Workshop.query.filter_by(email=WORKSHOP_A_EMAIL).first()
            entry = DclEntry(
                workshop_id=workshop_a.id,
                plate="DEF9999",
                branch=0,
                client_service_type=workshop_a.client_service_type,
                status="open",
            )
            db.session.add(entry)
            db.session.commit()
            entry_id = entry.id

        list_b = c.get("/api/dcl/entries", headers=_auth(token_b))
        assert list_b.status_code == 200
        assert list_b.get_json() == []

        get_b = c.get(f"/api/dcl/entries/{entry_id}", headers=_auth(token_b))
        assert get_b.status_code == 404

        get_a = c.get(f"/api/dcl/entries/{entry_id}", headers=_auth(token_a))
        assert get_a.status_code == 200
    finally:
        _cleanup()
