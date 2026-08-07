"""
test_account_deletion.py
--------------------------------------------------------------------
Επιβεβαιώνει ότι το DELETE /api/account σβήνει ΟΛΑ τα AadeLog ενός
συνεργείου, ΣΥΜΠΕΡΙΛΑΜΒΑΝΟΜΕΝΩΝ των system-level logs χωρίς dcl_entry_id
(π.χ. «Έλεγχος σύνδεσης» στις Ρυθμίσεις) — πριν το workshop_id στο
AadeLog, αυτά επιβίωναν επ' αόριστον στη βάση μετά τη διαγραφή του
λογαριασμού (ημιτελής GDPR erasure). Επιβεβαιώνει επίσης tenant isolation
(δεν σβήνονται logs άλλου συνεργείου).
--------------------------------------------------------------------
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import AadeLog, DclEntry, Workshop, db  # noqa: E402

WORKSHOP_A_EMAIL = "delete.a.test@example.com"
WORKSHOP_B_EMAIL = "delete.b.test@example.com"
PASSWORD = "testpass1234"


def client():
    app.config["TESTING"] = True
    return app.test_client()


def _register(c, email):
    res = c.post(
        "/api/auth/register",
        json={
            "name": f"Delete Test {email}",
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
            ws = Workshop.query.filter_by(email=email).first()
            if ws:
                AadeLog.query.filter_by(workshop_id=ws.id).delete()
                DclEntry.query.filter_by(workshop_id=ws.id).delete()
                db.session.delete(ws)
        db.session.commit()


def test_delete_account_removes_system_level_aade_logs():
    _cleanup()
    c = client()
    try:
        token_a = _register(c, WORKSHOP_A_EMAIL)
        token_b = _register(c, WORKSHOP_B_EMAIL)

        with app.app_context():
            workshop_a = Workshop.query.filter_by(email=WORKSHOP_A_EMAIL).first()
            workshop_b = Workshop.query.filter_by(email=WORKSHOP_B_EMAIL).first()
            # system-level log, ΧΩΡΙΣ dcl_entry_id — π.χ. «Έλεγχος σύνδεσης»
            log_a = AadeLog(
                workshop_id=workshop_a.id,
                dcl_entry_id=None,
                method="RequestClients",
                request_json="{}",
                response_json="{}",
                success=True,
            )
            log_b = AadeLog(
                workshop_id=workshop_b.id,
                dcl_entry_id=None,
                method="RequestClients",
                request_json="{}",
                response_json="{}",
                success=True,
            )
            db.session.add_all([log_a, log_b])
            db.session.commit()
            workshop_a_id = workshop_a.id

        res = c.delete(
            "/api/account", json={"password": PASSWORD}, headers=_auth(token_a)
        )
        assert res.status_code == 204, res.get_json()

        with app.app_context():
            # Του Α σβήστηκε (ΚΑΙ το ίδιο το workshop, ΚΑΙ το system log του)
            workshop_a_after = Workshop.query.filter_by(
                email=WORKSHOP_A_EMAIL
            ).first()
            assert workshop_a_after is None
            remaining_a_logs = AadeLog.query.filter_by(
                workshop_id=workshop_a_id
            ).count()
            assert remaining_a_logs == 0

            # Του Β παραμένει ανέγγιχτο
            workshop_b_after = Workshop.query.filter_by(
                email=WORKSHOP_B_EMAIL
            ).first()
            assert workshop_b_after is not None
            remaining_b_logs = AadeLog.query.filter_by(
                workshop_id=workshop_b_after.id
            ).count()
            assert remaining_b_logs == 1
    finally:
        _cleanup()
