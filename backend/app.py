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

from auth import init_auth, require_auth
from config import Config
from models import AadeLog, Customer, DclEntry, OcrMetric, Settings, db, utcnow

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

    if app.config["FLASK_ENV"] != "development":
        if app.config["JWT_SECRET_KEY"] == "dev-insecure-secret-change-me":
            app.logger.warning(
                "JWT_SECRET_KEY δεν έχει οριστεί ρητά σε production — "
                "ΟΛΑ τα tokens γίνονται μη έγκυρα σε κάθε restart. Όρισε το "
                "στα env vars."
            )

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


def _normalize_plate(plate):
    """Αφαιρεί ό,τι δεν είναι γράμμα/ψηφίο ώστε η σύγκριση "ΙΚΧ-1833" vs
    "ΙΚΧ1833" να μην μετράει σαν χειροκίνητη διόρθωση."""
    if not plate:
        return ""
    return re.sub(r"[^A-Z0-9Α-Ω]", "", plate.upper())


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
    body = {**payload, "installationId": installation_id}

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
    if current_app.config["USE_MOCK_AADE"]:
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
    completionDateTime από UpdatedClientData).
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
                "entryCompletion": upd.get("entryCompletion"),
            }
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
    # Έλεγχος σύνδεσης ΑΑΔΕ (ελαφριά κλήση RequestClients)
    # ----------------------------------------------------------------
    @app.route("/api/settings/test-connection", methods=["POST"])
    @require_auth
    def test_connection():
        settings = _get_settings()

        if not settings.has_key or not settings.aade_username:
            return jsonify({"ok": False, "reason": "Όρισε πρώτα κωδικούς ΑΑΔΕ."})

        # Σεβασμός mock/real switch: σε mock δεν γίνεται πραγματική κλήση.
        if current_app.config["USE_MOCK_AADE"]:
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

        plate = (data.get("plate") or "").strip()
        # Το branch έρχεται ΑΠΟ ΤΙΣ ΡΥΘΜΙΣΕΙΣ (όχι hardcoded/από το body)
        branch = settings.branch

        if not plate:
            raise ApiError("Το πεδίο 'plate' (πινακίδα) είναι υποχρεωτικό.")

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
            comments=data.get("comments"),
            status="open",
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
        }
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

        invoice_kind = data.get("invoiceKind")
        reason_non_issue = data.get("reasonNonIssueType")

        if invoice_kind is None and reason_non_issue is None:
            raise ApiError(
                "Απαιτείται είτε 'invoiceKind' (είδος παραστατικού) είτε "
                "'reasonNonIssueType' (αιτιολογία μη έκδοσης)."
            )

        if invoice_kind is not None:
            entry.invoice_kind = _parse_int(invoice_kind, "invoiceKind")

        # entry_completion/status προχωράνε ΜΟΝΟ μετά από επιβεβαιωμένη επιτυχία.

        # Κλήση ΑΑΔΕ — 3ος Χρόνος (UpdateClient με entryCompletion).
        # ⚠️ Για Συνεργεία το providedServiceCategory είναι ΥΠΟΧΡΕΩΤΙΚΟ σε ΚΑΘΕ
        # UpdateClient — το ξαναστέλνουμε από την εγγραφή (μπήκε στον 2ο Χρόνο).
        aade_payload = {
            "entryCompletion": True,
            "providedServiceCategory": entry.provided_service_category,
            "providedServiceCategoryOther": entry.provided_service_category_other,
            "invoiceKind": entry.invoice_kind,
        }
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
        final_plate = (data.get("finalPlate") or "").strip().upper() or None

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
        entries = (
            DclEntry.query.filter_by(workshop_id=g.workshop_id)
            .order_by(DclEntry.created_at.desc())
            .all()
        )
        return jsonify([e.to_dict() for e in entries])

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
            aade_payload = {
                "vehicleRegistrationNumber": entry.plate,
                "branch": entry.branch,
                "clientServiceType": entry.client_service_type,
                "serviceType": entry.service_type,
            }
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
                "providedServiceCategory": entry.provided_service_category,
                "providedServiceCategoryOther": entry.provided_service_category_other,
                "invoiceKind": entry.invoice_kind,
            }
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

        # Σεβασμός mock/real switch — σε mock δεν σκάει, απλώς δεν συγκρίνει.
        if current_app.config["USE_MOCK_AADE"]:
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

        settings = _require_credentials()
        aade = _build_aade(settings)

        dclid = (
            int(entry.id_dcl)
            if (entry.id_dcl and str(entry.id_dcl).isdigit())
            else 1
        )
        res = aade.request_clients(dclid=dclid)
        _log_aade(entry.id, "RequestClients", {"dclid": dclid}, res, "error" not in res)

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

        # Ενημέρωση τοπικής εγγραφής με τους ΑΥΘΕΝΤΙΚΟΥΣ χρόνους της ΑΑΔΕ
        # (αντικαθιστά το προσωρινό local UTC που είχε μπει).
        updated = []
        c_dt = _parse_aade_dt(aade_rec.get("creationDateTime"))
        if c_dt is not None:
            entry.creation_date_time = c_dt
            updated.append("creationDateTime")
        comp_dt = _parse_aade_dt(aade_rec.get("completionDateTime"))
        if comp_dt is not None:
            entry.completion_date_time = comp_dt
            updated.append("completionDateTime")
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
