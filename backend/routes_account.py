"""
routes_account.py
--------------------------------------------------------------------
Λογαριασμός — εξαγωγή δεδομένων (portability) / διαγραφή (erasure), GDPR.
--------------------------------------------------------------------
"""
from auth import require_auth, require_owner
from flask import Blueprint, g, jsonify, request
from models import AadeLog, Customer, DclEntry, OcrMetric, Settings, Workshop, db
from sqlalchemy.orm import selectinload

account_bp = Blueprint("account", __name__)


@account_bp.route("/api/account/export", methods=["GET"])
@require_auth
def export_account():
    workshop = Workshop.query.get(g.workshop_id)
    customers = Customer.query.filter_by(workshop_id=g.workshop_id).all()
    # selectinload: 1 επιπλέον query για ΟΛΑ τα AadeLog των entries, αντί
    # για ΕΝΑ query ανά entry (lazy=True default στο DclEntry.logs) —
    # χωρίς αυτό, ένα συνεργείο με π.χ. 2000 entries κάνει 2000+1 queries
    # εδώ και ρισκάρει timeout στο export.
    entries = (
        DclEntry.query.filter_by(workshop_id=g.workshop_id)
        .options(selectinload(DclEntry.logs))
        .all()
    )
    settings = Settings.query.filter_by(workshop_id=g.workshop_id).first()
    return jsonify(
        {
            "workshop": workshop.to_dict(),
            "customers": [c.to_dict() for c in customers],
            "dclEntries": [e.to_dict(include_logs=True) for e in entries],
            "settings": settings.to_dict() if settings else None,
        }
    )


@account_bp.route("/api/account", methods=["DELETE"])
@require_auth
@require_owner
def delete_account():
    data = request.get_json(silent=True) or {}
    password = data.get("password") or ""
    workshop = Workshop.query.get(g.workshop_id)
    if workshop is None or not workshop.check_password(password):
        # ΟΧΙ 401: το frontend κάνει global logout σε ΚΑΘΕ 401 (λήξη
        # session) — ένα λάθος πληκτρολογημένος κωδικός εδώ δεν πρέπει
        # να αποσυνδέει τον ήδη-συνδεδεμένο χρήστη.
        return jsonify({"error": "Λάθος κωδικός."}), 400

    Customer.query.filter_by(workshop_id=g.workshop_id).delete()
    OcrMetric.query.filter_by(workshop_id=g.workshop_id).delete()
    # Το delete() του query δεν ενεργοποιεί cascade στα relationships
    # (π.χ. DclEntry.logs -> AadeLog) — σβήνουμε ρητά τα AadeLog πρώτα.
    # Filter ΑΠΕΥΘΕΙΑΣ με workshop_id (όχι μέσω entry_ids/dcl_entry_id):
    # πιάνει ΚΑΙ τα system-level logs χωρίς dcl_entry_id (π.χ. «Έλεγχος
    # σύνδεσης» στις Ρυθμίσεις) — παλιότερα αυτά επιβίωναν της
    # διαγραφής λογαριασμού επ' αόριστον.
    AadeLog.query.filter_by(workshop_id=g.workshop_id).delete()
    DclEntry.query.filter_by(workshop_id=g.workshop_id).delete()
    Settings.query.filter_by(workshop_id=g.workshop_id).delete()
    db.session.delete(workshop)
    db.session.commit()
    return "", 204
