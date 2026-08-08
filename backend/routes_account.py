"""
routes_account.py
--------------------------------------------------------------------
Λογαριασμός — εξαγωγή δεδομένων (portability) / διαγραφή (erasure), GDPR,
και εξαγωγή audit log σε Excel για λογιστικό έλεγχο.
--------------------------------------------------------------------
"""
from datetime import date

from audit_export import build_audit_workbook
from auth import require_auth, require_owner
from flask import Blueprint, g, jsonify, request, send_file
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


@account_bp.route("/api/audit-log/export.xlsx", methods=["GET"])
@require_auth
def export_audit_log():
    """
    Excel με το ιστορικό εγγραφών + όλες τις κλήσεις προς την ΑΑΔΕ, για
    λογιστικό έλεγχο/φακέλωση. Δύο φύλλα — δες audit_export.py.

    ΔΕΝ είναι @require_owner: ένας υπάλληλος μπορεί κάλλιστα να χρειαστεί να
    βγάλει το αρχείο για τον λογιστή. Τα δεδομένα είναι ούτως ή άλλως αυτά
    που ήδη βλέπει στο «Ιστορικό».
    """
    # selectinload παντού: χωρίς αυτό, ένα συνεργείο με μερικές χιλιάδες
    # γραμμές κάνει ένα query ΑΝΑ γραμμή για να βρει τον υπάλληλο/εγγραφή
    # (lazy=True default) — δηλαδή timeout αντί για αρχείο.
    entries = (
        DclEntry.query.filter_by(workshop_id=g.workshop_id)
        .options(selectinload(DclEntry.created_by_employee))
        .order_by(DclEntry.created_at.desc())
        .all()
    )
    # Το φιλτράρισμα στο workshop_id είναι ΚΡΙΣΙΜΟ (multi-tenant): το
    # AadeLog.workshop_id είναι nullable για ιστορικές γραμμές από πριν το
    # migration 0004, οι οποίες σκόπιμα ΔΕΝ επιστρέφονται — δεν μπορούν να
    # αποδοθούν με βεβαιότητα σε συγκεκριμένο συνεργείο.
    logs = (
        AadeLog.query.filter_by(workshop_id=g.workshop_id)
        .options(selectinload(AadeLog.actor_employee), selectinload(AadeLog.dcl_entry))
        .order_by(AadeLog.created_at.desc())
        .all()
    )

    stream = build_audit_workbook(entries, logs)
    return send_file(
        stream,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"pelatologio-audit-{date.today().isoformat()}.xlsx",
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
