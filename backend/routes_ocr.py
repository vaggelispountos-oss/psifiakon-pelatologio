"""
routes_ocr.py
--------------------------------------------------------------------
Αναγνώριση πινακίδας μέσω ALPR (proxy, δες ocr_plate) + μετρικές OCR
(πόσο καλά δουλεύει στην πράξη — δες models.OcrMetric).
--------------------------------------------------------------------
"""
import aade_core
import requests
from auth import limiter, require_auth, workshop_key
from flask import Blueprint, current_app, g, jsonify, request
from models import OcrMetric, db
from sqlalchemy import case, func

ocr_bp = Blueprint("ocr", __name__)


# ----------------------------------------------------------------
# Αναγνώριση πινακίδας μέσω εξειδικευμένου ALPR (Plate Recognizer) —
# proxy ώστε το API token να ΜΗΝ βρίσκεται ποτέ στο frontend bundle.
# Παίρνει multipart/form-data με το πεδίο "upload" (εικόνα), το προωθεί
# στο Plate Recognizer και επιστρέφει { plate, confidence, raw }.
# ----------------------------------------------------------------
@ocr_bp.route("/api/ocr/plate", methods=["POST"])
@require_auth
@limiter.limit("30 per minute", key_func=workshop_key)
def ocr_plate():
    token = current_app.config["PLATE_RECOGNIZER_TOKEN"]
    if not token:
        raise aade_core.ApiError(
            "Το ALPR API δεν έχει ρυθμιστεί (λείπει PLATE_RECOGNIZER_TOKEN "
            "στο backend/.env). Χρησιμοποίησε το δωρεάν tesseract recognizer "
            "ή πρόσθεσε το token.",
            503,
        )

    upload = request.files.get("upload")
    if not upload:
        raise aade_core.ApiError("Λείπει το αρχείο εικόνας (πεδίο «upload»).")
    if upload.mimetype not in ("image/jpeg", "image/png", "image/webp"):
        raise aade_core.ApiError(
            "Μη έγκυρος τύπος αρχείου — επιτρέπονται μόνο JPEG, PNG ή WebP εικόνες.",
            400,
        )

    try:
        resp = requests.post(
            current_app.config["PLATE_RECOGNIZER_URL"],
            headers={"Authorization": f"Token {token}"},
            data={"regions": current_app.config["PLATE_RECOGNIZER_REGIONS"]},
            files={"upload": (upload.filename, upload.stream, upload.mimetype)},
            timeout=15,
        )
    except requests.RequestException as err:
        raise aade_core.ApiError(f"Σφάλμα σύνδεσης με το ALPR API: {err}", 502)

    if resp.status_code >= 400:
        raise aade_core.ApiError(
            f"Το ALPR API επέστρεψε σφάλμα ({resp.status_code}): {resp.text[:300]}",
            502,
        )

    try:
        payload = resp.json()
    except ValueError:
        raise aade_core.ApiError(
            "Το ALPR API επέστρεψε μη έγκυρη απάντηση (όχι JSON).", 502
        )
    results = payload.get("results") or []
    if not results:
        return jsonify(
            {"plate": None, "confidence": None, "raw": payload, "candidates": []}
        )

    best = max(results, key=lambda r: r.get("score", 0))
    candidates = [
        {"plate": (r.get("plate") or "").upper(), "score": r.get("score")}
        for r in results
    ]
    return jsonify(
        {
            "plate": (best.get("plate") or "").upper() or None,
            "confidence": round((best.get("score") or 0) * 100),
            "raw": payload,
            "candidates": candidates,
        }
    )


# ----------------------------------------------------------------
# Μετρικές αναγνώρισης πινακίδας (OCR) — για να φαίνεται πόσο καλά
# δουλεύει στην πράξη: ποσοστό επιτυχίας, πόσο συχνά χρειάζεται
# χειροκίνητη διόρθωση, ανά μηχανή/τύπο οχήματος. Δες models.OcrMetric.
# ----------------------------------------------------------------
@ocr_bp.route("/api/ocr/metrics", methods=["POST"])
@require_auth
def create_ocr_metric():
    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "car").strip()
    if mode not in ("car", "moto"):
        mode = "car"
    engine = (data.get("engine") or "unknown").strip()

    metric = OcrMetric(
        workshop_id=g.workshop_id,
        mode=mode,
        engine=engine,
        ocr_plate=(data.get("ocrPlate") or None),
        confidence=data.get("confidence"),
        warnings_count=int(data.get("warningsCount") or 0),
        parser_corrected=bool(data.get("parserCorrected")),
    )
    db.session.add(metric)
    db.session.commit()
    aade_core._forward_metric_to_telemetry(metric.to_dict())
    return jsonify(metric.to_dict()), 201


@ocr_bp.route("/api/ocr/metrics/<int:metric_id>", methods=["PATCH"])
@require_auth
def confirm_ocr_metric(metric_id):
    metric = OcrMetric.query.filter_by(
        id=metric_id, workshop_id=g.workshop_id
    ).first()
    if metric is None:
        raise aade_core.ApiError("Δεν βρέθηκε η μετρική.", 404)

    data = request.get_json(silent=True) or {}
    final_plate = aade_core._canonical_plate((data.get("finalPlate") or "").strip()) or None

    metric.final_plate = final_plate
    metric.confirmed = True
    metric.user_edited = aade_core._normalize_plate(final_plate) != aade_core._normalize_plate(
        metric.ocr_plate
    )
    db.session.commit()
    aade_core._forward_metric_to_telemetry(metric.to_dict())
    return jsonify(metric.to_dict())


@ocr_bp.route("/api/ocr/metrics", methods=["GET"])
@require_auth
def list_ocr_metrics():
    limit = min(aade_core._parse_int(request.args.get("limit", 50), "limit"), 500)
    rows = (
        OcrMetric.query.filter_by(workshop_id=g.workshop_id)
        .order_by(OcrMetric.created_at.desc())
        .limit(limit)
        .all()
    )
    return jsonify([r.to_dict() for r in rows])


@ocr_bp.route("/api/ocr/metrics/summary", methods=["GET"])
@require_auth
def ocr_metrics_summary():
    # Μία γραμμή ΑΝΑ σάρωση πινακίδας -> ο πίνακας μεγαλώνει πολύ πιο
    # γρήγορα από τις εγγραφές (πολλαπλές προσπάθειες ανά όχημα). Τα
    # aggregates γίνονται στη ΒΑΣΗ: το προηγούμενο .all() + Python loops
    # φόρτωνε ΚΑΘΕ σάρωση που έγινε ποτέ, στη μνήμη, σε κάθε άνοιγμα του
    # tab (δεκάδες χιλιάδες γραμμές/χρόνο για ένα ενεργό συνεργείο).
    scoped = db.session.query(OcrMetric).filter_by(workshop_id=g.workshop_id)

    total, successes, parser_corrected, avg_confidence = scoped.with_entities(
        func.count(OcrMetric.id),
        func.count(OcrMetric.ocr_plate),  # COUNT(col) αγνοεί τα NULL
        func.sum(case((OcrMetric.parser_corrected.is_(True), 1), else_=0)),
        func.avg(OcrMetric.confidence),
    ).one()

    confirmed, user_edited = scoped.filter(
        OcrMetric.confirmed.is_(True)
    ).with_entities(
        func.count(OcrMetric.id),
        func.sum(case((OcrMetric.user_edited.is_(True), 1), else_=0)),
    ).one()

    # SUM() γυρνά NULL (όχι 0) όταν δεν υπάρχουν γραμμές.
    parser_corrected = int(parser_corrected or 0)
    user_edited = int(user_edited or 0)

    def group_counts(column):
        return {
            key: count
            for key, count in scoped.with_entities(
                column, func.count(OcrMetric.id)
            ).group_by(column)
        }

    return jsonify(
        {
            "total": total,
            "successes": successes,
            "failures": total - successes,
            "successRate": round(successes / total * 100, 1) if total else None,
            "confirmed": confirmed,
            "userEdited": user_edited,
            "userEditedRate": round(user_edited / confirmed * 100, 1)
            if confirmed
            else None,
            "parserCorrected": parser_corrected,
            "avgConfidence": round(float(avg_confidence), 1)
            if avg_confidence is not None
            else None,
            "byEngine": group_counts(OcrMetric.engine),
            "byMode": group_counts(OcrMetric.mode),
        }
    )
