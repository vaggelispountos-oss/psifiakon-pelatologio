"""
test_token_revocation.py
--------------------------------------------------------------------
Επιβεβαιώνει το token_epoch mechanism (models.Workshop.token_epoch +
auth.py additional_claims_loader/require_auth/refresh): αλλαγή κωδικού
πρέπει να ακυρώνει ΑΜΕΣΩΣ κάθε ήδη-εκδομένο access ΚΑΙ refresh token, όχι
μόνο να επιτρέπει την επόμενη σύνδεση με τον νέο κωδικό.

Χωρίς αυτό, ένα κλεμμένο token (π.χ. μέσω XSS) παραμένει έγκυρο για ΟΛΗ
του τη διάρκεια ζωής (access: ώρες, refresh: 30 μέρες) ΑΚΟΜΗ ΚΙ ΑΝ ο
ιδιοκτήτης αλλάξει κωδικό — δεν έχει κανέναν τρόπο να «διώξει» τον
επιτιθέμενο.
--------------------------------------------------------------------
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import Workshop, db  # noqa: E402

TEST_EMAIL = "tokenrevoke.test@example.com"
TEST_PASSWORD = "testpass1234"
NEW_PASSWORD = "newpass5678"


def client():
    app.config["TESTING"] = True
    return app.test_client()


def _register(c):
    res = c.post(
        "/api/auth/register",
        json={
            "name": "Token Revocation Test Workshop",
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "businessType": "garage",
            "termsAccepted": True,
        },
    )
    data = res.get_json()
    return data["accessToken"], data["refreshToken"]


def _cleanup():
    with app.app_context():
        Workshop.query.filter_by(email=TEST_EMAIL).delete()
        db.session.commit()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_new_tokens_work_before_any_password_change():
    _cleanup()
    c = client()
    try:
        access, _ = _register(c)
        res = c.get("/api/auth/me", headers=_auth(access))
        assert res.status_code == 200
    finally:
        _cleanup()


def test_changing_password_invalidates_old_access_token():
    _cleanup()
    c = client()
    try:
        old_access, _ = _register(c)

        res = c.put(
            "/api/auth/password",
            json={"currentPassword": TEST_PASSWORD, "newPassword": NEW_PASSWORD},
            headers=_auth(old_access),
        )
        assert res.status_code == 200

        # Το ΙΔΙΟ access token (που μόλις χρησιμοποιήθηκε επιτυχώς για να
        # κάνει το ίδιο το password change) πρέπει τώρα να είναι άκυρο.
        res = c.get("/api/auth/me", headers=_auth(old_access))
        assert res.status_code == 401
        assert res.get_json().get("reason") == "token_epoch_mismatch"
    finally:
        _cleanup()


def test_changing_password_invalidates_old_refresh_token():
    _cleanup()
    c = client()
    try:
        old_access, old_refresh = _register(c)

        res = c.put(
            "/api/auth/password",
            json={"currentPassword": TEST_PASSWORD, "newPassword": NEW_PASSWORD},
            headers=_auth(old_access),
        )
        assert res.status_code == 200

        # Το ΠΑΛΙΟ refresh token δεν πρέπει να μπορεί να κόψει νέο access
        # token — αλλιώς ένα κλεμμένο refresh token (ζει 30 μέρες) θα
        # παρέκαμπτε εντελώς την ανάκληση.
        res = c.post("/api/auth/refresh", headers=_auth(old_refresh))
        assert res.status_code == 401
        assert res.get_json().get("reason") == "token_epoch_mismatch"
    finally:
        _cleanup()


def test_fresh_login_after_password_change_works_normally():
    _cleanup()
    c = client()
    try:
        old_access, _ = _register(c)
        c.put(
            "/api/auth/password",
            json={"currentPassword": TEST_PASSWORD, "newPassword": NEW_PASSWORD},
            headers=_auth(old_access),
        )

        res = c.post(
            "/api/auth/login",
            json={"email": TEST_EMAIL, "password": NEW_PASSWORD},
        )
        assert res.status_code == 200
        new_access = res.get_json()["accessToken"]

        res = c.get("/api/auth/me", headers=_auth(new_access))
        assert res.status_code == 200
    finally:
        _cleanup()


def test_reset_password_also_invalidates_old_tokens():
    """reset_password() καλεί το ίδιο set_password() — ίδιο μηχανισμό,
    διαφορετική διαδρομή (forgot/reset flow αντί για change_password)."""
    import hashlib
    import secrets
    from datetime import timedelta

    from models import PasswordResetToken, utcnow

    _cleanup()
    c = client()
    try:
        old_access, _ = _register(c)

        with app.app_context():
            workshop = Workshop.query.filter_by(email=TEST_EMAIL).first()
            raw_token = secrets.token_urlsafe(32)
            reset_token = PasswordResetToken(
                workshop_id=workshop.id,
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=utcnow() + timedelta(minutes=30),
            )
            db.session.add(reset_token)
            db.session.commit()

        res = c.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "password": NEW_PASSWORD},
        )
        assert res.status_code == 200

        res = c.get("/api/auth/me", headers=_auth(old_access))
        assert res.status_code == 401
        assert res.get_json().get("reason") == "token_epoch_mismatch"
    finally:
        _cleanup()
