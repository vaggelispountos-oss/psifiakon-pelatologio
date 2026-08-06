"""
app.py
--------------------------------------------------------------------
Flask backend για το σύστημα Ψηφιακού Πελατολογίου Οχημάτων (ΑΑΔΕ)
για συνεργείο αυτοκινήτων. MVP — single-tenant, mock ΑΑΔΕ.

Το backend υλοποιεί τη λογική των 4 «Χρόνων» της ΑΑΔΕ:
    1ος Χρόνος -> POST /api/dcl/entry      (SendClient)
    2ος Χρόνος -> POST /api/dcl/service    (UpdateClient — κατηγορία υπηρεσίας)
    3ος Χρόνος -> POST /api/dcl/exit       (UpdateClient — entryCompletion)
    4ος Χρόνος -> POST /api/dcl/correlate   (ClientCorrelations — ΜΑΡΚ)
    (+ ακύρωση) -> POST /api/dcl/cancel      (CancelClient)
--------------------------------------------------------------------
"""
import json
import re
import threading
import uuid
from datetime import datetime

import requests
from flask import Flask, current_app, g, jsonify, request
from flask_cors import CORS
from sqlalchemy import inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

from auth import init_auth, require_auth
from config import Config, validate_production_config
from models import AadeLog, Customer, DclEntry, OcrMetric, Settings, Workshop, db, utcnow

# --------------------------------------------------------------------
# Επιλογή υπηρεσίας ΑΑΔΕ (mock ή πραγματική).
# ΜΟΝΟ αυτό το σημείο αλλάζει όταν έρθει το πραγματικό ΑΑΔΕ:
#   from real_aade import RealAadeService
#   aade = RealAadeService(...)
# Η υπόλοιπη λογική παραμένει ίδια γιατί το interface είναι το ίδιο.
# --------------------------------------------------------------------
from mock_aade import MockAadeService


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Render (και οι περισσότεροι PaaS) βάζουν την εφαρμογή πίσω από έναν
    # reverse proxy — χωρίς αυτό, request.remote_addr θα ήταν πάντα η IP του
    # proxy, όχι του πραγματικού χρήστη, κι έτσι το per-IP rate limiting
    # (δες auth.limiter) θα μετρούσε ΟΛΟΥΣ τους χρήστες σαν έναν.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

    if app.config["FLASK_ENV"] == "production":
        validate_production_config()

    # CORS: με τον Vite proxy (single tunnel) δεν χτυπιέται καθόλου CORS, γιατί
    # ο browser μιλά μόνο στο origin του frontend. Default "*" (βολικό για
    # tunnels στο dev/testing) — για production όρισε CORS_ORIGINS στο .env
    # με το πραγματικό origin του frontend (δες config.py).
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    db.init_app(app)
    init_auth(app)

    # Δημιουργία της βάσης αυτόματα στο πρώτο τρέξιμο
    with app.app_context():
        db.create_all()
        _add_missing_columns(app)

    register_routes(app)
    register_error_handlers(app)
    return app


def _add_missing_columns(app):
    """
    Ελαφριά "auto-migration" για SQLite: το db.create_all() φτιάχνει ΜΟΝΟ
    πίνακες που λείπουν εντελώς — ΔΕΝ προσθέτει νέες στήλες σε πίνακες που
    ήδη υπάρχουν. Χωρίς αυτό, κάθε φορά που προστίθεται πεδίο σε μοντέλο
    (π.χ. έγινε ήδη με Settings.installation_id), ΚΑΘΕ υπάρχουσα εγκατάσταση
    (βάση συνεργείου με πραγματικά δεδομένα) σκάει με
    "OperationalError: no such column" στο πρώτο request — μη αποδεκτό όταν
    ο χρήστης είναι ένα συνεργείο χωρίς IT τμήμα να τρέξει migrations.
    Προσθέτει ΜΟΝΟ nullable στήλες (ασφαλές σε SQLite ΧΩΡΙΣ default value).
    ΔΕΝ αντικαθιστά πραγματικό εργαλείο migrations (Alembic) — αν χρειαστεί
    πιο σύνθετη αλλαγή σχήματος (νέα NOT NULL στήλη, rename, κλπ) χρειάζεται
    χειροκίνητο migration.
    """
    inspector = inspect(db.engine)
    with db.engine.begin() as conn:
        for table in db.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue  # νέος πίνακας -> τον έφτιαξε ήδη το create_all()
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not column.nullable:
                    app.logger.warning(
                        "Auto-migration: λείπει η NOT NULL στήλη '%s.%s' — "
                        "χρειάζεται χειροκίνητο migration, ΔΕΝ προστέθηκε αυτόματα.",
                        table.name,
                        column.name,
                    )
                    continue
                col_type = column.type.compile(db.engine.dialect)
                conn.execute(
                    text(
                        f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                    )
                )
                app.logger.info(
                    "Auto-migration: πρόσθεσα στήλη %s.%s", table.name, column.name
                )


# --------------------------------------------------------------------
# Βοηθητικές συναρτήσεις
# --------------------------------------------------------------------
def _log_aade(entry_id, method, request_payload, response_payload, success):
    """Καταγραφή κλήσης ΑΑΔΕ στο audit log."""
    log = AadeLog(
        dcl_entry_id=entry_id,
        method=method,
        request_json=json.dumps(request_payload, ensure_ascii=False),
        response_json=json.dumps(response_payload, ensure_ascii=False),
        success=success,
    )
    db.session.add(log)


class ApiError(Exception):
    """Σφάλμα εφαρμογής με HTTP status code."""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _get_entry_or_404(entry_id):
    entry = DclEntry.query.filter_by(id=entry_id, workshop_id=g.workshop_id).first()
    if entry is None:
        raise ApiError(f"Δεν βρέθηκε εγγραφή με id={entry_id}.", 404)
    return entry


def _parse_int(value, field_name):
    """Μετατρέπει σε int ή σηκώνει καθαρό ApiError (αντί για unhandled 500)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(f"Το πεδίο '{field_name}' πρέπει να είναι ακέραιος.")


# Ελληνικά γράμματα πινακίδας -> λατινικό οπτικό αντίστοιχο (ίδια αντιστοίχιση
# με frontend/src/utils.js GREEK_TO_LATIN). Χρειάζεται ΚΑΙ εδώ γιατί το
# vehicleRegistrationNumber της ΑΑΔΕ και η στήλη plate περιμένουν λατινικά,
# και ο χρήστης μπορεί να στείλει "ΙΚΧ-1833" απευθείας μέσω API/import χωρίς
# να περάσει ποτέ από το frontend.
_PLATE_LETTERS_LATIN = "ABEZHIKMNOPTYX"
_PLATE_LETTERS_GREEK = "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ"
_GREEK_TO_LATIN = dict(zip(_PLATE_LETTERS_GREEK, _PLATE_LETTERS_LATIN))


def _to_latin_plate(plate):
    """Μετατρέπει τυχόν ελληνικά γράμματα πινακίδας στα λατινικά αντίστοιχά
    τους. Καμία αλλαγή σε ήδη-λατινικές πινακίδες ή σε μη-γράμματα."""
    if not plate:
        return plate
    return "".join(_GREEK_TO_LATIN.get(ch, ch) for ch in plate)


def _normalize_plate(plate):
    """Κανονική μορφή πινακίδας για σύγκριση/αποθήκευση: λατινικά γράμματα,
    uppercase, χωρίς ό,τι δεν είναι γράμμα/ψηφίο (ώστε η σύγκριση "ΙΚΧ-1833"
    vs "IKX1833" να μη μετράει σαν χειροκίνητη διόρθωση, και ώστε η ίδια
    πινακίδα σε ελληνικά/λατινικά να ταυτίζεται πάντα με ΕΝΑΝ Customer)."""
    if not plate:
        return ""
    return re.sub(r"[^A-Z0-9]", "", _to_latin_plate(plate.upper()))


def _canonical_plate(plate):
    """Κανονική μορφή ΑΠΟΘΗΚΕΥΣΗΣ: λατινικά γράμματα, uppercase, ΔΙΑΤΗΡΕΙ την
    παύλα/κενά (σε αντίθεση με _normalize_plate που είναι μόνο για σύγκριση).
    Εφαρμόζεται σε κάθε plate πριν αποθηκευτεί (entry ή customer), ώστε η ίδια
    πινακίδα να έχει ΠΑΝΤΑ μία αναπαράσταση στη βάση."""
    if not plate:
        return plate
    return _to_latin_plate(plate.strip().upper())


def _get_workshop():
    """Το Workshop του τρέχοντος tenant — καθορίζει τον τύπο επιχείρησης
    (Συνεργείο/Ενοικίαση) άρα και ποιο clientServiceType/ροή χρησιμοποιείται."""
    return Workshop.query.get(g.workshop_id)


def _get_settings():
    """Επιστρέφει τις Settings του τρέχοντος workshop (δημιουργεί κενές αν λείπουν)."""
    settings = Settings.query.filter_by(workshop_id=g.workshop_id).first()
    if settings is None:
        settings = Settings(workshop_id=g.workshop_id, branch=0)
        db.session.add(settings)
        db.session.commit()
    return settings


def _get_installation_id():
    """Μοναδικό id αυτής της εγκατάστασης — δημιουργείται μία φορά, μόνιμο."""
    settings = _get_settings()
    if not settings.installation_id:
        settings.installation_id = uuid.uuid4().hex[:12]
        db.session.commit()
    return settings.installation_id


def _forward_metric_to_telemetry(payload):
    """
    Προωθεί (best-effort, ΣΕ ΞΕΧΩΡΙΣΤΟ thread) μία μετρική OCR στον κεντρικό
    telemetry server, αν έχει ρυθμιστεί TELEMETRY_URL. ΠΟΤΕ δεν πρέπει να
    καθυστερήσει ή να σπάσει το αίτημα του χρήστη — γι' αυτό:
      - τρέχει σε background thread (η απάντηση στο frontend δεν περιμένει)
      - καταπίνει ΟΠΟΙΟΔΗΠΟΤΕ σφάλμα δικτύου (ο πελάτης μπορεί να έχει κακό
        internet ή ο δικός σου server να είναι προσωρινά down — δεν πειράζει)
    """
    url = current_app.config.get("TELEMETRY_URL")
    if not url:
        return
    key = current_app.config.get("TELEMETRY_KEY")
    installation_id = _get_installation_id()
    # Data minimization: η πραγματική πινακίδα (ocrPlate/finalPlate) είναι
    # προσωπικό δεδομένο πελάτη του συνεργείου — ΔΕΝ χρειάζεται για να
    # μετρηθεί η απόδοση του OCR (ποσοστό επιτυχίας, user_edited, κλπ), άρα
    # ΔΕΝ φεύγει ποτέ προς τον telemetry server. Κρατάμε μόνο το boolean
    # "αναγνωρίστηκε κάτι" (ocrSuccess) που χρειάζεται το ποσοστό επιτυχίας.
    body = {
        k: v for k, v in payload.items() if k not in ("ocrPlate", "finalPlate")
    }
    body["ocrSuccess"] = bool(payload.get("ocrPlate"))
    body["installationId"] = installation_id

    def _send():
        try:
            requests.post(
                url,
                json=body,
                headers={"X-Telemetry-Key": key} if key else {},
                timeout=5,
            )
        except requests.RequestException:
            pass

    threading.Thread(target=_send, daemon=True).start()


def _build_aade(settings):
    """
    Factory: χτίζει την υπηρεσία ΑΑΔΕ με τα credentials από τις Settings.
    ΜΟΝΟ εδώ αλλάζει mock <-> πραγματικό ΑΑΔΕ (ίδιο interface).
    """
    creds = {
        "username": settings.aade_username,
        "subscription_key": settings.aade_subscription_key,
        "branch": settings.branch,
        "entity_vat_number": settings.entity_vat_number,
    }
    # force_real_aade: per-workshop override (δες /api/admin/.../aade-mode)
    # ώστε ΕΝΑ workshop να δοκιμάσει πραγματική ΑΑΔΕ χωρίς να αλλάξει
    # συμπεριφορά για όλους τους υπόλοιπους tenants στο ίδιο deployment.
    use_mock = current_app.config["USE_MOCK_AADE"] and not settings.force_real_aade
    if use_mock:
        return MockAadeService(**creds)
    # Πραγματική ΑΑΔΕ — ίδιο interface, περνά και το base_url (dev/prod).
    from real_aade import RealAadeService

    return RealAadeService(base_url=current_app.config["AADE_BASE_URL"], **creds)


def _require_credentials():
    """
    Επιστρέφει τις Settings αν έχουν οριστεί credentials, αλλιώς μπλοκάρει
    τη ροή με καθαρό μήνυμα (παραπομπή στις Ρυθμίσεις).
    """
    settings = _get_settings()
    if not settings.has_key or not settings.aade_username:
        raise ApiError(
            "Δεν έχουν οριστεί οι κωδικοί ΑΑΔΕ — πήγαινε στις Ρυθμίσεις.", 400
        )
    return settings


def _parse_aade_dt(s):
    """
    Parse datetime από την ΑΑΔΕ (RequestClients).
    ⚠️ Έρχεται σε ώρα Ελλάδος (Europe/Athens) — το κρατάμε ως έχει.
    """
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_aade_record(requested_doc, id_dcl):
    """
    Βρίσκει στο parsed RequestedDoc τον DigitalClient με το δοσμένο idDcl και
    επιστρέφει τα αυθεντικά στοιχεία (creationDateTime από InitialClientData,
    τα υπόλοιπα από UpdatedClientData) — η ΑΑΔΕ είναι πάντα η πηγή αλήθειας,
    ανεξάρτητα από ΠΟΙΟ λογισμικό (το δικό μας ή π.χ. αυτό του λογιστή)
    έστειλε την τελευταία ενημέρωση.
    """
    for client in requested_doc.get("clients", []) or []:
        init = client.get("InitialClientData", {}) or {}
        upd = client.get("UpdatedClientData", {}) or {}
        if str(init.get("idDcl")) == str(id_dcl):
            return {
                "idDcl": init.get("idDcl"),
                "creationDateTime": init.get("creationDateTime"),
                "completionDateTime": upd.get("completionDateTime"),
                "providedServiceCategory": upd.get("providedServiceCategory"),
                "providedServiceCategoryOther": upd.get("providedServiceCategoryOther"),
                "invoiceKind": upd.get("invoiceKind"),
                "entryCompletion": upd.get("entryCompletion"),
            }
    return None


def _as_list(val):
    """Το _elem_to_dict δίνει string για ένα στοιχείο, list για πολλά — ενοποίηση."""
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def _find_cancellation(requested_doc, id_dcl):
    for c in requested_doc.get("cancellations", []) or []:
        if str(c.get("dclid")) == str(id_dcl):
            return c
    return None


def _find_correlation(requested_doc, id_dcl):
    for c in requested_doc.get("correlations", []) or []:
        ids = [str(x) for x in _as_list(c.get("correlatedDCLids"))]
        if str(id_dcl) in ids:
            return c
    return None


# --------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------
def register_routes(app):
    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"})

    # ----------------------------------------------------------------
    # Ρυθμίσεις ΑΑΔΕ (credentials) — GET/PUT
    # ----------------------------------------------------------------
    @app.route("/api/settings", methods=["GET"])
    @require_auth
    def get_settings():
        # Επιστρέφει ΠΑΝΤΑ masked key (ποτέ ολόκληρο).
        return jsonify(_get_settings().to_dict())

    @app.route("/api/settings", methods=["PUT"])
    @require_auth
    def update_settings():
        data = request.get_json(silent=True) or {}
        settings = _get_settings()

        # --- Validation ---
        username = (data.get("aade_username") or "").strip()
        if not username:
            raise ApiError("Το «Όνομα Χρήστη» είναι υποχρεωτικό.")

        branch = data.get("branch")
        try:
            branch = int(branch)
        except (TypeError, ValueError):
            raise ApiError("Ο «Αριθμός Εγκατάστασης» πρέπει να είναι ακέραιος ≥ 0.")
        if branch < 0:
            raise ApiError("Ο «Αριθμός Εγκατάστασης» πρέπει να είναι ≥ 0.")

        entity_vat = (data.get("entity_vat_number") or "").strip()
        if entity_vat and not (entity_vat.isdigit() and len(entity_vat) == 9):
            raise ApiError("Το ΑΦΜ υπόχρεης οντότητας πρέπει να είναι 9 ψηφία.")

        # --- Αποθήκευση ---
        settings.aade_username = username
        settings.branch = branch
        settings.entity_vat_number = entity_vat or None

        # Το key: αν έρθει κενό ή masked (περιέχει •), ΜΗΝ το αντικαθιστάς.
        new_key = data.get("aade_subscription_key")
        if new_key and "•" not in new_key and new_key.strip():
            settings.aade_subscription_key = new_key.strip()

        db.session.commit()
        return jsonify(settings.to_dict())

    # ----------------------------------------------------------------
    # Βάση Πελατών/Οχημάτων — λίστα (με αναζήτηση) + επεξεργασία στοιχείων.
    # Ξεχωριστό από τα /api/dcl/entries: εδώ είναι ΜΙΑ γραμμή ανά πινακίδα
    # με τα στοιχεία επαφής (όνομα/ΑΦΜ/τηλέφωνο) που κρατά ήδη το μοντέλο
    # Customer αλλά δεν εκτίθονταν πουθενά.
    # ----------------------------------------------------------------
    @app.route("/api/customers", methods=["GET"])
    @require_auth
    def list_customers():
        q = (request.args.get("q") or "").strip()
        query = Customer.query.filter_by(workshop_id=g.workshop_id)
        if q:
            like = f"%{q}%"
            query = query.filter(
                db.or_(
                    Customer.plate.ilike(like),
                    Customer.name.ilike(like),
                    Customer.vat.ilike(like),
                    Customer.phone.ilike(like),
                )
            )
        customers = query.order_by(Customer.plate.asc()).all()
        return jsonify([c.to_dict() for c in customers])

    @app.route("/api/customers/<int:customer_id>", methods=["PATCH"])
    @require_auth
    def update_customer(customer_id):
        customer = Customer.query.filter_by(
            id=customer_id, workshop_id=g.workshop_id
        ).first()
        if customer is None:
            raise ApiError("Δεν βρέθηκε ο πελάτης.", 404)

        data = request.get_json(silent=True) or {}
        if "name" in data:
            customer.name = (data.get("name") or "").strip() or None
        if "vat" in data:
            vat = (data.get("vat") or "").strip()
            if vat and not (vat.isdigit() and len(vat) == 9):
                raise ApiError("Το ΑΦΜ πρέπει να είναι 9 ψηφία.")
            customer.vat = vat or None
        if "phone" in data:
            customer.phone = (data.get("phone") or "").strip() or None

        db.session.commit()
        return jsonify(customer.to_dict())

    # ----------------------------------------------------------------
    # Λογαριασμός — εξαγωγή δεδομένων (portability) / διαγραφή (erasure)
    # ----------------------------------------------------------------
    @app.route("/api/account/export", methods=["GET"])
    @require_auth
    def export_account():
        workshop = Workshop.query.get(g.workshop_id)
        customers = Customer.query.filter_by(workshop_id=g.workshop_id).all()
        entries = DclEntry.query.filter_by(workshop_id=g.workshop_id).all()
        settings = Settings.query.filter_by(workshop_id=g.workshop_id).first()
        return jsonify(
            {
                "workshop": workshop.to_dict(),
                "customers": [c.to_dict() for c in customers],
                "dclEntries": [e.to_dict(include_logs=True) for e in entries],
                "settings": settings.to_dict() if settings else None,
            }
        )

    @app.route("/api/account", methods=["DELETE"])
    @require_auth
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
        entry_ids = [
            e.id for e in DclEntry.query.filter_by(workshop_id=g.workshop_id).all()
        ]
        if entry_ids:
            AadeLog.query.filter(AadeLog.dcl_entry_id.in_(entry_ids)).delete(
                synchronize_session=False
            )
        DclEntry.query.filter_by(workshop_id=g.workshop_id).delete()
        Settings.query.filter_by(workshop_id=g.workshop_id).delete()
        db.session.delete(workshop)
        db.session.commit()
        return "", 204

    # ----------------------------------------------------------------
    # Έλεγχος σύνδεσης ΑΑΔΕ (ελαφριά κλήση RequestClients)
    # ----------------------------------------------------------------
    @app.route("/api/settings/test-connection", methods=["POST"])
    @require_auth
    def test_connection():
        settings = _get_settings()

        if not settings.has_key or not settings.aade_username:
            return jsonify({"ok": False, "reason": "Όρισε πρώτα κωδικούς ΑΑΔΕ."})

        # Σεβασμός mock/real switch (ίδια λογική με _build_aade: το per-workshop
        # force_real_aade υπερισχύει του global USE_MOCK_AADE).
        use_mock = current_app.config["USE_MOCK_AADE"] and not settings.force_real_aade
        if use_mock:
            return jsonify(
                {"ok": True, "message": "Mock mode — δεν έγινε πραγματική κλήση"}
            )

        aade = _build_aade(settings)
        # Ελαφριά κλήση με dummy/μικρό dclid
        res = aade.request_clients(dclid=1)

        # Audit (system-level, χωρίς entry)
        _log_aade(None, "RequestClients", {"dclid": 1}, res, "error" not in res)
        db.session.commit()

        if "error" in res:
            return jsonify({"ok": False, "reason": res["error"]})
        return jsonify({"ok": True, "message": "Σύνδεση επιτυχής"})

    # ----------------------------------------------------------------
    # Live/Mock switch — αυτοεξυπηρέτηση από τον χρήστη (workshop-scoped).
    # Ίδιο flag με το admin-only /api/admin/.../aade-mode, ώστε ο χρήστης
    # να μπορεί να ενεργοποιήσει πραγματική ΑΑΔΕ χωρίς admin key.
    # ----------------------------------------------------------------
    @app.route("/api/settings/aade-mode", methods=["PUT"])
    @require_auth
    def set_own_aade_mode():
        settings = _get_settings()
        if not settings.has_key or not settings.aade_username:
            raise ApiError(
                "Όρισε πρώτα τους κωδικούς ΑΑΔΕ πριν ενεργοποιήσεις πραγματική λειτουργία.",
                400,
            )
        data = request.get_json(silent=True) or {}
        settings.force_real_aade = bool(data.get("forceReal"))
        db.session.commit()
        return jsonify(settings.to_dict())

    # ----------------------------------------------------------------
    # 1ος ΧΡΟΝΟΣ — SendClient
    # Δημιουργία εγγραφής Ψηφιακού Πελατολογίου. Η ΑΑΔΕ επιστρέφει
    # τον Μοναδικό Αριθμό Εγγραφής (idDcl) και την ώρα δημιουργίας.
    # ----------------------------------------------------------------
    @app.route("/api/dcl/entry", methods=["POST"])
    @require_auth
    def create_entry():
        data = request.get_json(silent=True) or {}

        # Guard: πρέπει να έχουν οριστεί credentials ΑΑΔΕ
        settings = _require_credentials()
        aade = _build_aade(settings)
        workshop = _get_workshop()
        is_rental = workshop.client_service_type == 1

        # Κανονικοποίηση ΕΔΩ (όχι μόνο στο frontend): η ίδια πινακίδα σε
        # ελληνικά/λατινικά γράμματα πρέπει ΠΑΝΤΑ να καταλήγει στον ΙΔΙΟ
        # Customer — αλλιώς το unique constraint plate+workshop δημιουργεί
        # σιωπηλά διπλότυπους πελάτες για την ίδια πινακίδα.
        plate = _canonical_plate((data.get("plate") or "").strip())
        # Το branch έρχεται ΑΠΟ ΤΙΣ ΡΥΘΜΙΣΕΙΣ (όχι hardcoded/από το body)
        branch = settings.branch

        if not plate:
            raise ApiError("Το πεδίο 'plate' (πινακίδα) είναι υποχρεωτικό.")

        # --- Ενοικιάσεις: Σκοπός Κίνησης Οχήματος υποχρεωτικός στον 1ο Χρόνο ---
        movement_purpose = None
        is_diff_pickup = None
        pickup_location = None
        if is_rental:
            movement_purpose = data.get("vehicleMovementPurpose")
            if movement_purpose is None:
                raise ApiError("Το πεδίο 'vehicleMovementPurpose' (Σκοπός Κίνησης) είναι υποχρεωτικό για Ενοικιάσεις.")
            movement_purpose = _parse_int(movement_purpose, "vehicleMovementPurpose")
            if movement_purpose not in (1, 2, 3):
                raise ApiError("Το 'vehicleMovementPurpose' πρέπει να είναι 1, 2 ή 3.")
            is_diff_pickup = bool(data.get("isDiffVehPickupLocation"))
            pickup_location = (data.get("vehiclePickupLocation") or "").strip() or None

        # Δημιουργία ή εύρεση πελάτη με βάση την πινακίδα (μέσα στο workshop)
        customer = Customer.query.filter_by(
            plate=plate, workshop_id=g.workshop_id
        ).first()
        if customer is None:
            customer = Customer(
                workshop_id=g.workshop_id,
                plate=plate,
                name=data.get("customerName"),
                vat=data.get("vat"),
                vehicle_category=data.get("vehicleCategory"),
                vehicle_factory=data.get("vehicleFactory"),
            )
            db.session.add(customer)
        else:
            # Ενημέρωση στοιχείων αν δόθηκαν
            if data.get("customerName"):
                customer.name = data.get("customerName")
            if data.get("vat"):
                customer.vat = data.get("vat")
            if data.get("vehicleCategory"):
                customer.vehicle_category = data.get("vehicleCategory")
            if data.get("vehicleFactory"):
                customer.vehicle_factory = data.get("vehicleFactory")

        # Δημιουργία της εγγραφής DCL (τοπικά, χωρίς idDcl ακόμη)
        entry = DclEntry(
            workshop_id=g.workshop_id,
            plate=plate,
            branch=int(branch),
            client_service_type=workshop.client_service_type,
            comments=data.get("comments"),
            status="open",
            vehicle_movement_purpose=movement_purpose,
            is_diff_pickup_location=is_diff_pickup,
            vehicle_pickup_location=pickup_location,
        )
        db.session.add(entry)
        db.session.flush()  # για να πάρουμε entry.id για το log

        # Κλήση ΑΑΔΕ (mock) — 1ος Χρόνος
        # Το branch από τις Settings· το entityVatNumber μόνο αν έχει οριστεί
        # (περίπτωση λογιστή που διαβιβάζει για λογαριασμό πελάτη).
        aade_payload = {
            "vehicleRegistrationNumber": plate,
            "branch": int(branch),
            "clientServiceType": entry.client_service_type,
            "serviceType": entry.service_type,
            "useCase": "rental" if is_rental else "garage",
            "vehicleCategory": data.get("vehicleCategory"),
            "vehicleFactory": data.get("vehicleFactory"),
        }
        if is_rental:
            aade_payload["vehicleMovementPurpose"] = movement_purpose
            aade_payload["isDiffVehPickupLocation"] = is_diff_pickup
            aade_payload["vehiclePickupLocation"] = pickup_location
        if settings.entity_vat_number:
            aade_payload["entityVatNumber"] = settings.entity_vat_number
        result = aade.send_client(aade_payload)

        if "error" in result:
            _log_aade(entry.id, "SendClient", aade_payload, result, False)
            db.session.commit()
            raise ApiError(f"ΑΑΔΕ SendClient error: {result['error']} — έλεγξε τα στοιχεία ΑΑΔΕ στις Ρυθμίσεις ή δοκίμασε ξανά σε λίγο.", 502)

        # Αποθήκευση απάντησης ΑΑΔΕ
        entry.id_dcl = result["idDcl"]
        entry.creation_date_time = utcnow()
        _log_aade(entry.id, "SendClient", aade_payload, result, True)
        db.session.commit()

        return (
            jsonify(
                {
                    "entry_id": entry.id,
                    "idDcl": entry.id_dcl,
                    "creationDateTime": result["creationDateTime"],
                    "status": entry.status,
                }
            ),
            201,
        )

    # ----------------------------------------------------------------
    # 2ος ΧΡΟΝΟΣ — UpdateClient (κατηγορία παρεχόμενης υπηρεσίας)
    # ----------------------------------------------------------------
    @app.route("/api/dcl/service", methods=["POST"])
    @require_auth
    def add_service():
        data = request.get_json(silent=True) or {}

        entry = _get_entry_or_404(data.get("entry_id"))
        if entry.client_service_type == 1:
            raise ApiError("Οι Ενοικιάσεις δεν έχουν 2ο Χρόνο (κατηγορία υπηρεσίας) — προχώρα κατευθείαν στην Ολοκλήρωση.")
        aade = _build_aade(_require_credentials())

        category = data.get("providedServiceCategory")
        if category is None:
            raise ApiError("Το πεδίο 'providedServiceCategory' είναι υποχρεωτικό.")

        category = _parse_int(category, "providedServiceCategory")
        other = data.get("providedServiceCategoryOther")

        # Validation: αν κατηγορία == 5 (Άλλο), το 'other' είναι υποχρεωτικό
        if category == 5 and not (other and str(other).strip()):
            raise ApiError(
                "Όταν providedServiceCategory==5, το 'providedServiceCategoryOther' "
                "είναι υποχρεωτικό."
            )

        # Αποθηκεύουμε ΠΑΝΤΑ τα δεδομένα (χρήσιμα για επαναποστολή αν αποτύχει
        # η κλήση), αλλά η κατάσταση ("in_progress") προχωράει ΜΟΝΟ μετά από
        # επιβεβαιωμένη επιτυχία — αλλιώς θα δείχναμε "εντάξει" κάτι που στην
        # πραγματικότητα δεν έφτασε ποτέ στην ΑΑΔΕ.
        entry.provided_service_category = category
        entry.provided_service_category_other = other
        if data.get("comments"):
            entry.comments = data.get("comments")

        # Κλήση ΑΑΔΕ (mock) — 2ος Χρόνος
        aade_payload = {
            "providedServiceCategory": category,
            "providedServiceCategoryOther": other,
        }
        # Οι κατηγορίες 4 (Δωρεάν), 6 (Εγγύηση) και 9 (Ιδιόχρηση) δεν οδηγούν
        # ποτέ σε παραστατικό — η ΑΑΔΕ απαιτεί nonIssueInvoice=true ήδη από
        # τον 2ο Χρόνο σε αυτές (business error 203 αλλιώς).
        if category in (4, 6, 9):
            aade_payload["nonIssueInvoice"] = True
        result = aade.update_client(entry.id_dcl, aade_payload)

        if "error" in result:
            _log_aade(entry.id, "UpdateClient", aade_payload, result, False)
            db.session.commit()
            raise ApiError(f"ΑΑΔΕ UpdateClient error: {result['error']} — έλεγξε τα στοιχεία ΑΑΔΕ στις Ρυθμίσεις ή δοκίμασε ξανά σε λίγο.", 502)

        entry.status = "in_progress"
        _log_aade(entry.id, "UpdateClient", aade_payload, result, True)
        db.session.commit()

        return jsonify(
            {"updateUniqueId": result["updateUniqueId"], "status": entry.status}
        )

    # ----------------------------------------------------------------
    # 3ος ΧΡΟΝΟΣ — UpdateClient με entryCompletion=true (ολοκλήρωση)
    # Η ΑΑΔΕ επιστρέφει το completionDateTime.
    # ----------------------------------------------------------------
    @app.route("/api/dcl/exit", methods=["POST"])
    @require_auth
    def complete_entry():
        data = request.get_json(silent=True) or {}

        entry = _get_entry_or_404(data.get("entry_id"))
        aade = _build_aade(_require_credentials())
        is_rental = entry.client_service_type == 1

        invoice_kind = data.get("invoiceKind")
        reason_non_issue = data.get("reasonNonIssueType")

        if invoice_kind is None and reason_non_issue is None:
            raise ApiError(
                "Απαιτείται είτε 'invoiceKind' (είδος παραστατικού) είτε "
                "'reasonNonIssueType' (αιτιολογία μη έκδοσης)."
            )

        # Οι κατηγορίες 4 (Δωρεάν), 6 (Εγγύηση) και 9 (Ιδιόχρηση) δεν οδηγούν
        # ΠΟΤΕ σε παραστατικό — αν επιλέχθηκαν στον 2ο Χρόνο, η Ολοκλήρωση
        # πρέπει να δηλώσει "Δεν εκδίδεται παραστατικό", αλλιώς η ΑΑΔΕ
        # απορρίπτει με το ίδιο business error 203 που είδαμε στον 2ο Χρόνο.
        if (
            not is_rental
            and entry.provided_service_category in (4, 6, 9)
            and invoice_kind is not None
        ):
            raise ApiError(
                "Η κατηγορία υπηρεσίας που επιλέχθηκε (Δωρεάν/Εγγύηση/Ιδιόχρηση) "
                "δεν εκδίδει παραστατικό — επίλεξε «Δεν εκδίδεται παραστατικό» "
                "αντί για είδος παραστατικού."
            )

        if invoice_kind is not None:
            entry.invoice_kind = _parse_int(invoice_kind, "invoiceKind")

        # --- Ενοικιάσεις: Συμφωνηθέν Ποσό + (προαιρετικά) τόπος επιστροφής ---
        if is_rental:
            amount = data.get("amount")
            if amount is None:
                raise ApiError("Το πεδίο 'amount' (Συμφωνηθέν Ποσό) είναι υποχρεωτικό για Ενοικιάσεις.")
            try:
                entry.amount = float(amount)
            except (TypeError, ValueError):
                raise ApiError("Το πεδίο 'amount' πρέπει να είναι αριθμός.")
            entry.is_diff_return_location = bool(data.get("isDiffVehReturnLocation"))
            entry.vehicle_return_location = (data.get("vehicleReturnLocation") or "").strip() or None

        # entry_completion/status προχωράνε ΜΟΝΟ μετά από επιβεβαιωμένη επιτυχία.

        # Κλήση ΑΑΔΕ — 3ος Χρόνος (UpdateClient με entryCompletion).
        # ⚠️ Για Συνεργεία το providedServiceCategory είναι ΥΠΟΧΡΕΩΤΙΚΟ σε ΚΑΘΕ
        # UpdateClient — το ξαναστέλνουμε από την εγγραφή (μπήκε στον 2ο Χρόνο).
        # Για Ενοικιάσεις δεν υπάρχει providedServiceCategory — αντ' αυτού
        # amount + (προαιρετικά) τόπος επιστροφής.
        aade_payload = {
            "entryCompletion": True,
            "invoiceKind": entry.invoice_kind,
        }
        if is_rental:
            aade_payload["amount"] = entry.amount
            aade_payload["isDiffVehReturnLocation"] = entry.is_diff_return_location
            aade_payload["vehicleReturnLocation"] = entry.vehicle_return_location
        else:
            aade_payload["providedServiceCategory"] = entry.provided_service_category
            aade_payload["providedServiceCategoryOther"] = entry.provided_service_category_other
        if reason_non_issue is not None:
            aade_payload["reasonNonIssueType"] = _parse_int(
                reason_non_issue, "reasonNonIssueType"
            )
            # Μη έκδοση παραστατικού
            aade_payload["nonIssueInvoice"] = True
        result = aade.update_client(entry.id_dcl, aade_payload)

        if "error" in result:
            _log_aade(entry.id, "UpdateClient", aade_payload, result, False)
            db.session.commit()
            raise ApiError(f"ΑΑΔΕ UpdateClient error: {result['error']} — έλεγξε τα στοιχεία ΑΑΔΕ στις Ρυθμίσεις ή δοκίμασε ξανά σε λίγο.", 502)

        # Η ΑΑΔΕ βάζει το completionDateTime
        entry.entry_completion = True
        entry.status = "completed"
        entry.completion_date_time = utcnow()
        _log_aade(entry.id, "UpdateClient", aade_payload, result, True)
        db.session.commit()

        return jsonify(
            {
                "completionDateTime": result.get("completionDateTime"),
                "status": entry.status,
            }
        )

    # ----------------------------------------------------------------
    # 4ος ΧΡΟΝΟΣ — ClientCorrelations (συσχέτιση ΜΑΡΚ παραστατικού)
    # ----------------------------------------------------------------
    @app.route("/api/dcl/correlate", methods=["POST"])
    @require_auth
    def correlate_entry():
        data = request.get_json(silent=True) or {}

        entry = _get_entry_or_404(data.get("entry_id"))
        aade = _build_aade(_require_credentials())

        mark = data.get("mark")
        if not mark:
            raise ApiError("Το πεδίο 'mark' (ΜΑΡΚ παραστατικού) είναι υποχρεωτικό.")

        entry.mark = str(mark)
        # status προχωράει σε "correlated" ΜΟΝΟ μετά από επιβεβαιωμένη επιτυχία.

        # Κλήση ΑΑΔΕ (mock) — 4ος Χρόνος
        aade_payload = {"mark": str(mark)}
        result = aade.client_correlations(entry.id_dcl, aade_payload)

        if "error" in result:
            _log_aade(entry.id, "ClientCorrelations", aade_payload, result, False)
            db.session.commit()
            raise ApiError(f"ΑΑΔΕ ClientCorrelations error: {result['error']} — έλεγξε τα στοιχεία ΑΑΔΕ στις Ρυθμίσεις ή δοκίμασε ξανά σε λίγο.", 502)

        entry.correlate_id = result["correlateId"]
        entry.status = "correlated"
        _log_aade(entry.id, "ClientCorrelations", aade_payload, result, True)
        db.session.commit()

        return jsonify({"correlateId": entry.correlate_id, "status": entry.status})

    # ----------------------------------------------------------------
    # CancelClient — ακύρωση εγγραφής
    # ----------------------------------------------------------------
    @app.route("/api/dcl/cancel", methods=["POST"])
    @require_auth
    def cancel_entry():
        data = request.get_json(silent=True) or {}

        entry = _get_entry_or_404(data.get("entry_id"))
        aade = _build_aade(_require_credentials())

        result = aade.cancel_client(entry.id_dcl)

        if "error" in result:
            _log_aade(entry.id, "CancelClient", {}, result, False)
            db.session.commit()
            raise ApiError(f"ΑΑΔΕ CancelClient error: {result['error']} — έλεγξε τα στοιχεία ΑΑΔΕ στις Ρυθμίσεις ή δοκίμασε ξανά σε λίγο.", 502)

        entry.status = "cancelled"
        _log_aade(entry.id, "CancelClient", {}, result, True)
        db.session.commit()

        return jsonify(
            {"cancellationId": result["cancellationId"], "status": entry.status}
        )

    # ----------------------------------------------------------------
    # Λίστα εγγραφών & λεπτομέρειες
    # ----------------------------------------------------------------
    # ----------------------------------------------------------------
    # Αναγνώριση πινακίδας μέσω εξειδικευμένου ALPR (Plate Recognizer) —
    # proxy ώστε το API token να ΜΗΝ βρίσκεται ποτέ στο frontend bundle.
    # Παίρνει multipart/form-data με το πεδίο "upload" (εικόνα), το προωθεί
    # στο Plate Recognizer και επιστρέφει { plate, confidence, raw }.
    # ----------------------------------------------------------------
    @app.route("/api/ocr/plate", methods=["POST"])
    @require_auth
    def ocr_plate():
        token = current_app.config["PLATE_RECOGNIZER_TOKEN"]
        if not token:
            raise ApiError(
                "Το ALPR API δεν έχει ρυθμιστεί (λείπει PLATE_RECOGNIZER_TOKEN "
                "στο backend/.env). Χρησιμοποίησε το δωρεάν tesseract recognizer "
                "ή πρόσθεσε το token.",
                503,
            )

        upload = request.files.get("upload")
        if not upload:
            raise ApiError("Λείπει το αρχείο εικόνας (πεδίο «upload»).")

        try:
            resp = requests.post(
                current_app.config["PLATE_RECOGNIZER_URL"],
                headers={"Authorization": f"Token {token}"},
                data={"regions": current_app.config["PLATE_RECOGNIZER_REGIONS"]},
                files={"upload": (upload.filename, upload.stream, upload.mimetype)},
                timeout=15,
            )
        except requests.RequestException as err:
            raise ApiError(f"Σφάλμα σύνδεσης με το ALPR API: {err}", 502)

        if resp.status_code >= 400:
            raise ApiError(
                f"Το ALPR API επέστρεψε σφάλμα ({resp.status_code}): {resp.text[:300]}",
                502,
            )

        try:
            payload = resp.json()
        except ValueError:
            raise ApiError(
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
    @app.route("/api/ocr/metrics", methods=["POST"])
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
        _forward_metric_to_telemetry(metric.to_dict())
        return jsonify(metric.to_dict()), 201

    @app.route("/api/ocr/metrics/<int:metric_id>", methods=["PATCH"])
    @require_auth
    def confirm_ocr_metric(metric_id):
        metric = OcrMetric.query.filter_by(
            id=metric_id, workshop_id=g.workshop_id
        ).first()
        if metric is None:
            raise ApiError("Δεν βρέθηκε η μετρική.", 404)

        data = request.get_json(silent=True) or {}
        final_plate = _canonical_plate((data.get("finalPlate") or "").strip()) or None

        metric.final_plate = final_plate
        metric.confirmed = True
        metric.user_edited = _normalize_plate(final_plate) != _normalize_plate(
            metric.ocr_plate
        )
        db.session.commit()
        _forward_metric_to_telemetry(metric.to_dict())
        return jsonify(metric.to_dict())

    @app.route("/api/ocr/metrics", methods=["GET"])
    @require_auth
    def list_ocr_metrics():
        limit = min(_parse_int(request.args.get("limit", 50), "limit"), 500)
        rows = (
            OcrMetric.query.filter_by(workshop_id=g.workshop_id)
            .order_by(OcrMetric.created_at.desc())
            .limit(limit)
            .all()
        )
        return jsonify([r.to_dict() for r in rows])

    @app.route("/api/ocr/metrics/summary", methods=["GET"])
    @require_auth
    def ocr_metrics_summary():
        rows = OcrMetric.query.filter_by(workshop_id=g.workshop_id).all()
        total = len(rows)
        successes = sum(1 for r in rows if r.ocr_plate)
        confirmed = [r for r in rows if r.confirmed]
        user_edited = sum(1 for r in confirmed if r.user_edited)
        confidences = [r.confidence for r in rows if r.confidence is not None]
        parser_corrected = sum(1 for r in rows if r.parser_corrected)

        def group_counts(key_fn):
            out = {}
            for r in rows:
                k = key_fn(r)
                out[k] = out.get(k, 0) + 1
            return out

        return jsonify(
            {
                "total": total,
                "successes": successes,
                "failures": total - successes,
                "successRate": round(successes / total * 100, 1) if total else None,
                "confirmed": len(confirmed),
                "userEdited": user_edited,
                "userEditedRate": round(user_edited / len(confirmed) * 100, 1)
                if confirmed
                else None,
                "parserCorrected": parser_corrected,
                "avgConfidence": round(sum(confidences) / len(confidences), 1)
                if confidences
                else None,
                "byEngine": group_counts(lambda r: r.engine),
                "byMode": group_counts(lambda r: r.mode),
            }
        )

    @app.route("/api/dcl/entries", methods=["GET"])
    @require_auth
    def list_entries():
        # Χωρίς όριο, αυτό το endpoint γυρνάει ΟΛΟ το ιστορικό του workshop σε
        # ΚΑΘΕ φόρτωση (π.χ. 7.000+ εγγραφές/χρόνο για ένα ενεργό συνεργείο) —
        # αργό σε κινητό/4G και άσκοπο, αφού τα tabs "Λειτουργία"/"Εγγραφές"
        # χρειάζονται μόνο τις πρόσφατες. limit/offset για βαθύτερη αναζήτηση.
        limit = min(_parse_int(request.args.get("limit", 200), "limit"), 500)
        offset = max(_parse_int(request.args.get("offset", 0), "offset"), 0)
        query = (
            DclEntry.query.filter_by(workshop_id=g.workshop_id)
            .order_by(DclEntry.created_at.desc())
        )
        total = query.count()
        entries = query.offset(offset).limit(limit).all()
        response = jsonify([e.to_dict() for e in entries])
        response.headers["X-Total-Count"] = str(total)
        return response

    @app.route("/api/dcl/entries/<int:entry_id>", methods=["GET"])
    @require_auth
    def get_entry(entry_id):
        entry = _get_entry_or_404(entry_id)
        customer = Customer.query.filter_by(
            plate=entry.plate, workshop_id=g.workshop_id
        ).first()
        data = entry.to_dict(include_logs=True)
        data["customer"] = customer.to_dict() if customer else None
        return jsonify(data)

    # ----------------------------------------------------------------
    # Επαναποστολή — η εγγραφή είναι αποθηκευμένη τοπικά αλλά ο τελευταίος
    # «Χρόνος» δεν επιβεβαιώθηκε από την ΑΑΔΕ (π.χ. έπεσε το internet στη
    # μέση). Ξαναστέλνει ΑΚΡΙΒΩΣ την ίδια, ήδη αποθηκευμένη πληροφορία.
    # ----------------------------------------------------------------
    @app.route("/api/dcl/entries/<int:entry_id>/resend", methods=["POST"])
    @require_auth
    def resend_entry(entry_id):
        entry = _get_entry_or_404(entry_id)
        action = entry.pending_action
        if action is None:
            raise ApiError("Δεν υπάρχει κάτι εκκρεμές προς επαναποστολή για αυτή την εγγραφή.")

        settings = _require_credentials()
        aade = _build_aade(settings)

        if action == "entry":
            is_rental = entry.client_service_type == 1
            aade_payload = {
                "vehicleRegistrationNumber": entry.plate,
                "branch": entry.branch,
                "clientServiceType": entry.client_service_type,
                "serviceType": entry.service_type,
                "useCase": "rental" if is_rental else "garage",
            }
            if is_rental:
                aade_payload["vehicleMovementPurpose"] = entry.vehicle_movement_purpose
                aade_payload["isDiffVehPickupLocation"] = entry.is_diff_pickup_location
                aade_payload["vehiclePickupLocation"] = entry.vehicle_pickup_location
            if settings.entity_vat_number:
                aade_payload["entityVatNumber"] = settings.entity_vat_number
            result = aade.send_client(aade_payload)
            method = "SendClient"
        elif action == "service":
            aade_payload = {
                "providedServiceCategory": entry.provided_service_category,
                "providedServiceCategoryOther": entry.provided_service_category_other,
            }
            result = aade.update_client(entry.id_dcl, aade_payload)
            method = "UpdateClient"
        elif action == "exit":
            aade_payload = {
                "entryCompletion": True,
                "invoiceKind": entry.invoice_kind,
            }
            if entry.client_service_type == 1:
                aade_payload["amount"] = entry.amount
                aade_payload["isDiffVehReturnLocation"] = entry.is_diff_return_location
                aade_payload["vehicleReturnLocation"] = entry.vehicle_return_location
            else:
                aade_payload["providedServiceCategory"] = entry.provided_service_category
                aade_payload["providedServiceCategoryOther"] = entry.provided_service_category_other
            result = aade.update_client(entry.id_dcl, aade_payload)
            method = "UpdateClient"
        else:  # "correlate"
            aade_payload = {"mark": entry.mark}
            result = aade.client_correlations(entry.id_dcl, aade_payload)
            method = "ClientCorrelations"

        if "error" in result:
            _log_aade(entry.id, method, aade_payload, result, False)
            db.session.commit()
            raise ApiError(
                f"Η επαναποστολή απέτυχε — {result['error']} "
                "Η εγγραφή παραμένει αποθηκευμένη τοπικά, δοκίμασε ξανά αργότερα.",
                502,
            )

        if action == "entry":
            entry.id_dcl = result["idDcl"]
            entry.creation_date_time = utcnow()
        elif action == "service":
            entry.status = "in_progress"
        elif action == "exit":
            entry.entry_completion = True
            entry.status = "completed"
            entry.completion_date_time = utcnow()
        else:
            entry.correlate_id = result["correlateId"]
            entry.status = "correlated"

        _log_aade(entry.id, method, aade_payload, result, True)
        db.session.commit()
        return jsonify(entry.to_dict())

    # ----------------------------------------------------------------
    # Reconciliation — σύγκριση τοπικής εγγραφής με την ΑΑΔΕ (RequestClients)
    # ----------------------------------------------------------------
    @app.route("/api/dcl/reconcile/<int:entry_id>", methods=["GET"])
    @require_auth
    def reconcile(entry_id):
        entry = _get_entry_or_404(entry_id)

        local = {
            "status": entry.status,
            "idDcl": entry.id_dcl,
            "creationDateTime": entry.creation_date_time.isoformat()
            if entry.creation_date_time
            else None,
            "completionDateTime": entry.completion_date_time.isoformat()
            if entry.completion_date_time
            else None,
            "mark": entry.mark,
        }

        # Σεβασμός mock/real switch (ίδια λογική με _build_aade/test-connection).
        settings = _get_settings()
        use_mock = current_app.config["USE_MOCK_AADE"] and not settings.force_real_aade
        if use_mock:
            return jsonify(
                {
                    "ok": True,
                    "mock": True,
                    "message": "Mock mode — δεν έγινε σύγκριση με ΑΑΔΕ.",
                    "local": local,
                    "aade": None,
                    "matches": None,
                }
            )

        if not settings.has_key or not settings.aade_username:
            raise ApiError(
                "Δεν έχουν οριστεί οι κωδικοί ΑΑΔΕ — πήγαινε στις Ρυθμίσεις.", 400
            )
        aade = _build_aade(settings)

        # ΠΡΟΣΟΧΗ: το dclid της RequestClients ΔΕΝ είναι "δώσε μου αυτή την
        # εγγραφή" — είναι cursor: επιστρέφει εγγραφές με DCLID > dclid (ίδια
        # λογική με το mark streaming στα τιμολόγια myDATA). Αν στείλουμε το
        # ίδιο id_dcl της εγγραφής, ζητάμε ό,τι είναι ΜΕΤΑ από αυτήν και ποτέ
        # δεν την βρίσκουμε. Γι' αυτό ζητάμε [id_dcl - 1, id_dcl] — το στενό
        # εύρος γύρω ΑΚΡΙΒΩΣ από τη συγκεκριμένη εγγραφή.
        if entry.id_dcl and str(entry.id_dcl).isdigit():
            target_id = int(entry.id_dcl)
            dclid = max(target_id - 1, 1)
            max_dclid = target_id
        else:
            dclid = 1
            max_dclid = None
        res = aade.request_clients(dclid=dclid, max_dclid=max_dclid)
        _log_aade(
            entry.id,
            "RequestClients",
            {"dclid": dclid, "max_dclid": max_dclid},
            res,
            "error" not in res,
        )

        if "error" in res:
            db.session.commit()
            return jsonify({"ok": False, "reason": res["error"], "local": local})

        aade_rec = _extract_aade_record(res, entry.id_dcl)
        if aade_rec is None:
            db.session.commit()
            return jsonify(
                {
                    "ok": False,
                    "reason": "Δεν βρέθηκε η εγγραφή στην ΑΑΔΕ (idDcl %s)."
                    % entry.id_dcl,
                    "local": local,
                    "aade": None,
                }
            )

        # Ενημέρωση τοπικής εγγραφής με τα ΑΥΘΕΝΤΙΚΑ στοιχεία της ΑΑΔΕ —
        # πηγή αλήθειας, ό,τι κι αν το ενημέρωσε (εμάς, λογιστικό λογισμικό
        # που κάνει ClientCorrelations/CancelClient με τα ίδια στοιχεία κ.λπ.).
        updated = []
        c_dt = _parse_aade_dt(aade_rec.get("creationDateTime"))
        if c_dt is not None and c_dt != entry.creation_date_time:
            entry.creation_date_time = c_dt
            updated.append("creationDateTime")
        comp_dt = _parse_aade_dt(aade_rec.get("completionDateTime"))
        if comp_dt is not None and comp_dt != entry.completion_date_time:
            entry.completion_date_time = comp_dt
            updated.append("completionDateTime")

        category = aade_rec.get("providedServiceCategory")
        if category not in (None, "") and _parse_int(category, "providedServiceCategory") != entry.provided_service_category:
            entry.provided_service_category = _parse_int(category, "providedServiceCategory")
            updated.append("providedServiceCategory")
        other = aade_rec.get("providedServiceCategoryOther")
        if other and other != entry.provided_service_category_other:
            entry.provided_service_category_other = other
            updated.append("providedServiceCategoryOther")
        invoice_kind = aade_rec.get("invoiceKind")
        if invoice_kind not in (None, "") and _parse_int(invoice_kind, "invoiceKind") != entry.invoice_kind:
            entry.invoice_kind = _parse_int(invoice_kind, "invoiceKind")
            updated.append("invoiceKind")

        cancellation = _find_cancellation(res, entry.id_dcl)
        correlation = _find_correlation(res, entry.id_dcl)

        # Ιεράρχηση τελικής κατάστασης: ακύρωση > συσχέτιση ΜΑΡΚ > ολοκλήρωση
        # > σε εξέλιξη (2ος Χρόνος) > ανοιχτή. Η ΑΑΔΕ υπερισχύει πάντα της
        # τοπικής κατάστασης — μπορεί να έχει προχωρήσει από άλλο λογισμικό.
        if cancellation is not None:
            new_status = "cancelled"
        elif correlation is not None:
            new_status = "correlated"
        elif str(aade_rec.get("entryCompletion")).lower() == "true":
            new_status = "completed"
        elif category not in (None, ""):
            new_status = "in_progress"
        else:
            new_status = entry.status  # δεν έχει προχωρήσει ακόμα στην ΑΑΔΕ

        if new_status != entry.status:
            entry.status = new_status
            updated.append("status")

        if correlation is not None:
            mark = correlation.get("mark")
            if mark and mark != entry.mark:
                entry.mark = mark
                updated.append("mark")
            correlate_id = correlation.get("correlateId")
            if correlate_id and correlate_id != entry.correlate_id:
                entry.correlate_id = correlate_id
                updated.append("correlateId")

        db.session.commit()

        matches = {"idDcl": str(aade_rec.get("idDcl")) == str(entry.id_dcl)}

        return jsonify(
            {
                "ok": True,
                "local": local,
                "aade": aade_rec,
                "updated": updated,
                "matches": matches,
            }
        )


# --------------------------------------------------------------------
# Error handlers
# --------------------------------------------------------------------
def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify({"error": err.message}), err.status_code

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify({"error": "Το endpoint δεν βρέθηκε. Έλεγξε ότι το backend έχει ενημερωθεί στην τελευταία έκδοση."}), 404

    @app.errorhandler(405)
    def handle_405(err):
        return jsonify({"error": "Μη επιτρεπτή μέθοδος HTTP. Πιθανό πρόβλημα συμβατότητας frontend/backend."}), 405

    @app.errorhandler(500)
    def handle_500(err):
        db.session.rollback()
        return jsonify({"error": "Εσωτερικό σφάλμα διακομιστή. Δοκίμασε ξανά· αν επιμένει, ελέγξε τα logs του backend."}), 500


app = create_app()


if __name__ == "__main__":
    import os

    # Default 5001 — το 5000 το κρατάει συχνά το AirPlay Receiver στο macOS.
    port = int(os.getenv("PORT", "5001"))
    # debug: ΠΟΤΕ True by default σε production (Werkzeug debugger = RCE risk).
    # Ακολουθεί το config.py (FLASK_DEBUG / FLASK_ENV=development).
    app.run(host="0.0.0.0", port=port, debug=app.config["DEBUG"])
