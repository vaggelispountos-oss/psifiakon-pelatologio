"""
test_password_reset.py
--------------------------------------------------------------------
Τεστ πλήρους ροής forgot-password -> reset-password -> login με νέο κωδικό.
Το πραγματικό email δεν στέλνεται στα tests — παγιδεύουμε το send_email
(δες auth.py: `from email_service import send_email`) για να πάρουμε το
token από το link, ακριβώς όπως θα το έπαιρνε ο χρήστης από το email του.
--------------------------------------------------------------------
"""
import os
import re
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import PasswordResetToken, Workshop, db  # noqa: E402

TEST_EMAIL = "pwdreset.test@example.com"
TEST_PASSWORD = "testpass1234"
NEW_PASSWORD = "newpass5678"


def client():
    app.config["TESTING"] = True
    return app.test_client()


def _register(c):
    return c.post(
        "/api/auth/register",
        json={
            "name": "Password Reset Test Workshop",
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "businessType": "garage",
            "termsAccepted": True,
        },
    )


def _cleanup():
    with app.app_context():
        workshop = Workshop.query.filter_by(email=TEST_EMAIL).first()
        if workshop:
            PasswordResetToken.query.filter_by(workshop_id=workshop.id).delete()
        Workshop.query.filter_by(email=TEST_EMAIL).delete()
        db.session.commit()


def test_forgot_password_unknown_email_returns_generic_message():
    c = client()
    res = c.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert res.status_code == 200
    assert "email" in res.get_json()["message"].lower()


def test_full_reset_flow_changes_password():
    _cleanup()
    c = client()
    try:
        assert _register(c).status_code == 201

        captured = {}

        def fake_send_email(to, subject, html):
            captured["html"] = html

        with patch("auth.send_email", fake_send_email):
            res = c.post("/api/auth/forgot-password", json={"email": TEST_EMAIL})
        assert res.status_code == 200
        assert "html" in captured

        match = re.search(r"token=([\w\-]+)", captured["html"])
        assert match, "reset link δεν βρέθηκε στο email"
        token = match.group(1)

        reset = c.post(
            "/api/auth/reset-password",
            json={"token": token, "password": NEW_PASSWORD},
        )
        assert reset.status_code == 200

        # Ο παλιός κωδικός δεν δουλεύει πια
        old_login = c.post(
            "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        assert old_login.status_code == 401

        # Ο νέος κωδικός δουλεύει
        new_login = c.post(
            "/api/auth/login", json={"email": TEST_EMAIL, "password": NEW_PASSWORD}
        )
        assert new_login.status_code == 200

        # Το token είναι single-use — δεύτερη χρήση αποτυγχάνει
        reused = c.post(
            "/api/auth/reset-password",
            json={"token": token, "password": "anotherpass123"},
        )
        assert reused.status_code == 400
    finally:
        _cleanup()
