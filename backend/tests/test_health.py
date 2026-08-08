"""
test_health.py
--------------------------------------------------------------------
Τεστ για τα /api/health (liveness) και /api/health/ready (readiness).

Ο ΔΙΑΧΩΡΙΣΜΟΣ ΤΩΝ ΔΥΟ ΕΙΝΑΙ ΤΟ ΝΟΗΜΑ, όχι λεπτομέρεια υλοποίησης:
το render.yaml δείχνει το healthCheckPath στο /api/health, οπότε αν εκείνο
άγγιζε τη βάση, ένα στιγμιαίο πρόβλημα σύνδεσης θα έκανε το Render να
σκοτώνει και να ξαναστήνει το service σε βρόχο — ακριβώς τη στιγμή που η
βάση δυσκολεύεται. Αυτά τα tests κλειδώνουν αυτή τη συμπεριφορά ώστε να μην
«διορθωθεί» κατά λάθος στο μέλλον.
--------------------------------------------------------------------
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db  # noqa: E402


def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_liveness_returns_ok():
    res = client().get("/api/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_liveness_does_not_touch_the_database(monkeypatch):
    """
    Το κρίσιμο: ακόμα και με ΕΝΤΕΛΩΣ πεσμένη βάση, το liveness πρέπει να
    απαντά 200 — αλλιώς το Render μπαίνει σε restart loop.
    """
    def boom(*args, **kwargs):
        raise RuntimeError("η βάση είναι πεσμένη")

    monkeypatch.setattr(db.session, "execute", boom)

    res = client().get("/api/health")
    assert res.status_code == 200


def test_readiness_reports_ok_when_database_reachable():
    res = client().get("/api/health/ready")
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_readiness_returns_503_when_database_unreachable(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("connection pool exhausted")

    monkeypatch.setattr(db.session, "execute", boom)

    res = client().get("/api/health/ready")
    assert res.status_code == 503
    body = res.get_json()
    assert body["status"] == "error"
    assert body["database"] == "unreachable"
    # Το endpoint είναι δημόσιο: το μήνυμα του σφάλματος δεν πρέπει να
    # διαρρέει προς τα έξω (πάει μόνο στα logs/Sentry).
    assert "connection pool exhausted" not in res.get_data(as_text=True)


def test_failed_readiness_does_not_poison_later_requests(monkeypatch):
    """
    Χωρίς το db.session.rollback() στον error handler, η session μένει σε
    failed state και ΚΑΘΕ επόμενο query στον ίδιο gunicorn worker σκάει —
    δηλαδή ένα αποτυχημένο health check θα έριχνε πραγματικά αιτήματα
    χρηστών. Αυτό το test το πιάνει.
    """
    c = client()

    def boom(*args, **kwargs):
        raise RuntimeError("προσωρινή αποτυχία")

    monkeypatch.setattr(db.session, "execute", boom)
    assert c.get("/api/health/ready").status_code == 503

    # Η βάση συνέρχεται (αίρουμε το monkeypatch) — το επόμενο αίτημα πρέπει
    # να δουλέψει κανονικά.
    monkeypatch.undo()
    res = c.get("/api/health/ready")
    assert res.status_code == 200
    assert res.get_json()["database"] == "ok"
