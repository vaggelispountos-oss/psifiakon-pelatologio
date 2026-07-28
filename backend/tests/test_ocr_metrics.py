"""
test_ocr_metrics.py
--------------------------------------------------------------------
Τεστ για τα endpoints /api/ocr/metrics* (καταγραφή απόδοσης OCR πινακίδας).
Χρησιμοποιεί το πραγματικό Flask app + test_client. ΚΑΘΑΡΙΖΕΙ μετά τον εαυτό
του (διαγράφει τις γραμμές που δημιούργησε) ώστε να μη μολύνει τη dev βάση.
--------------------------------------------------------------------
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import OcrMetric, db  # noqa: E402


def client():
    app.config["TESTING"] = True
    return app.test_client()


def cleanup(ids):
    with app.app_context():
        OcrMetric.query.filter(OcrMetric.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.session.commit()


def test_create_metric_success():
    c = client()
    ids = []
    try:
        res = c.post(
            "/api/ocr/metrics",
            json={
                "mode": "car",
                "engine": "tesseract",
                "ocrPlate": "IKX-1833",
                "confidence": 72,
                "warningsCount": 0,
                "parserCorrected": False,
            },
        )
        assert res.status_code == 201
        body = res.get_json()
        ids.append(body["id"])
        assert body["ocrPlate"] == "IKX-1833"
        assert body["confirmed"] is False
        assert body["userEdited"] is None
    finally:
        cleanup(ids)


def test_create_metric_failure_has_null_plate():
    c = client()
    ids = []
    try:
        res = c.post(
            "/api/ocr/metrics",
            json={"mode": "moto", "engine": "tesseract", "ocrPlate": None},
        )
        assert res.status_code == 201
        body = res.get_json()
        ids.append(body["id"])
        assert body["ocrPlate"] is None
        assert body["mode"] == "moto"
    finally:
        cleanup(ids)


def test_confirm_without_edit_marks_user_edited_false():
    c = client()
    ids = []
    try:
        created = c.post(
            "/api/ocr/metrics",
            json={"mode": "car", "engine": "tesseract", "ocrPlate": "IKX-1833"},
        ).get_json()
        ids.append(created["id"])

        # Ο χρήστης επιβεβαιώνει ΑΚΡΙΒΩΣ ό,τι πρότεινε το OCR (ίδιο, χωρίς
        # την παύλα -> δεν πρέπει να μετρηθεί σαν διόρθωση).
        res = c.patch(
            f"/api/ocr/metrics/{created['id']}",
            json={"finalPlate": "IKX1833"},
        )
        assert res.status_code == 200
        body = res.get_json()
        assert body["confirmed"] is True
        assert body["userEdited"] is False
    finally:
        cleanup(ids)


def test_confirm_with_edit_marks_user_edited_true():
    c = client()
    ids = []
    try:
        created = c.post(
            "/api/ocr/metrics",
            json={"mode": "car", "engine": "tesseract", "ocrPlate": "HKX-2183"},
        ).get_json()
        ids.append(created["id"])

        # Ο χρήστης διόρθωσε το λάθος αποτέλεσμα του OCR.
        res = c.patch(
            f"/api/ocr/metrics/{created['id']}",
            json={"finalPlate": "IKX-1833"},
        )
        body = res.get_json()
        assert body["userEdited"] is True
    finally:
        cleanup(ids)


def test_confirm_missing_metric_returns_404():
    c = client()
    res = c.patch("/api/ocr/metrics/999999999", json={"finalPlate": "IKX-1833"})
    assert res.status_code == 404


def test_summary_reflects_created_rows():
    c = client()
    ids = []
    try:
        r1 = c.post(
            "/api/ocr/metrics",
            json={
                "mode": "car",
                "engine": "tesseract",
                "ocrPlate": "IKX-1833",
                "confidence": 80,
            },
        ).get_json()
        r2 = c.post(
            "/api/ocr/metrics",
            json={"mode": "car", "engine": "tesseract", "ocrPlate": None},
        ).get_json()
        ids = [r1["id"], r2["id"]]

        summary = c.get("/api/ocr/metrics/summary").get_json()
        assert summary["total"] >= 2
        assert summary["successes"] >= 1
        assert summary["failures"] >= 1
        assert "tesseract" in summary["byEngine"]
        assert "car" in summary["byMode"]
    finally:
        cleanup(ids)


def test_list_metrics_respects_limit():
    c = client()
    ids = []
    try:
        for _ in range(3):
            r = c.post(
                "/api/ocr/metrics",
                json={"mode": "car", "engine": "tesseract", "ocrPlate": "IKX-1833"},
            ).get_json()
            ids.append(r["id"])

        res = c.get("/api/ocr/metrics?limit=2")
        assert res.status_code == 200
        assert len(res.get_json()) == 2
    finally:
        cleanup(ids)
