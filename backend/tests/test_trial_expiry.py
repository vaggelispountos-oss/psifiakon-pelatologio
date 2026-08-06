"""
test_trial_expiry.py
--------------------------------------------------------------------
Τεστ ότι το require_auth μπλοκάρει (402) όταν λήξει η δοκιμαστική περίοδος
ενός workshop σε κατάσταση "trial". Καθαρίζει μετά τον εαυτό του.
--------------------------------------------------------------------
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import Workshop, db, utcnow  # noqa: E402

TEST_EMAIL = "trialexpiry.test@example.com"
TEST_PASSWORD = "testpass1234"


def client():
    app.config["TESTING"] = True
    return app.test_client()


def _register(c):
    return c.post(
        "/api/auth/register",
        json={
            "name": "Trial Expiry Test Workshop",
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "businessType": "garage",
            "termsAccepted": True,
        },
    )


def _cleanup():
    with app.app_context():
        Workshop.query.filter_by(email=TEST_EMAIL).delete()
        db.session.commit()


def test_fresh_trial_is_active():
    _cleanup()
    c = client()
    try:
        res = _register(c)
        assert res.status_code == 201
        token = res.get_json()["accessToken"]

        me = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
    finally:
        _cleanup()


def test_expired_trial_is_blocked():
    _cleanup()
    c = client()
    try:
        res = _register(c)
        assert res.status_code == 201
        token = res.get_json()["accessToken"]

        with app.app_context():
            workshop = Workshop.query.filter_by(email=TEST_EMAIL).first()
            workshop.trial_ends_at = utcnow() - timedelta(days=1)
            db.session.commit()

        me = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 402
        assert me.get_json().get("trialExpired") is True
    finally:
        _cleanup()
