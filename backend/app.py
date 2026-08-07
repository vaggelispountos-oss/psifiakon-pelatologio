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
from datetime import datetime, timedelta

import requests
from flask import Flask, current_app, g, jsonify, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from auth import init_auth, require_auth
from config import Config, validate_production_config
from models import (
    AadeLog,
    Customer,
    DclEntry,
    FleetVehicle,
    OcrMetric,
    Settings,
    Workshop,
    db,
    utcnow,
)

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

    # Δημιουργία/ενημέρωση σχήματος βάσης: ΠΛΕΟΝ μέσω Alembic (migrations/),
    # ΟΧΙ αυτόματα εδώ.
    #
    # Παλιότερα, αυτό το σημείο έτρεχε db.create_all() + ένα χειροκίνητο
    # "auto-migration" (ALTER TABLE ADD COLUMN) σε ΚΑΘΕ εκκίνηση της
    # εφαρμογής. Δούλευε με 1 process, αλλά:
    #   - Με >1 gunicorn worker (χρειάζεται — δες render.yaml), πολλά
    #     processes τρέχουν το ΙΔΙΟ ALTER TABLE ταυτόχρονα στο boot ->
    #     DuplicateColumn σε Postgres -> crash loop στο deploy.
    #   - Δεν μπορούσε να προσθέσει indexes, NOT NULL στήλες, renames.
    # Το Alembic τρέχει ΜΙΑ φορά, ΠΡΙΝ ξεκινήσουν οι gunicorn workers (δες
    # render.yaml `preDeployCommand`) — ασφαλές ανεξαρτήτως αριθμού workers.
    #
    # Dev: για να μη χρειάζεται χειροκίνητο βήμα σε κάθε `python app.py`,
    # δες το `if __name__ == "__main__"` στο τέλος του αρχείου — τρέχει
    # `alembic upgrade head` ΜΟΝΟ εκεί (ποτέ κάτω από gunicorn).

    register_routes(app)
    register_error_handlers(app)
    return app


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


def _opt_int(value):
    """Σαν _parse_int αλλά επιστρέφει None αντί να σηκώνει σφάλμα — για
    προαιρετικά/άγνωστα πεδία όταν εισάγουμε δεδομένα από την ΑΑΔΕ."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Κατηγορίες οχημάτων στόλου (Ενοικιάσεις) — χρησιμοποιείται για ομαδοποίηση
# στη λίστα επιλογής οχήματος (RentalVehiclePicker) καθώς και για validation
# στο create/update fleet vehicle.
VEHICLE_CATEGORIES = {"car", "motorcycle", "atv", "bicycle", "ebike", "other"}

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
    if _use_mock(settings):
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
# Προστασία από ΔΙΠΛΕΣ εγγραφές στην ΑΑΔΕ
# --------------------------------------------------------------------
# Κάθε SendClient δημιουργεί ΝΕΑ εγγραφή στο Ψηφιακό Πελατολόγιο· δεν υπάρχει
# idempotency key ούτε τρόπος να «αναιρέσεις» μια διπλή καταχώρηση πέρα από
# CancelClient. Άρα ΠΟΤΕ δεν ξαναστέλνουμε κάτι που ΜΠΟΡΕΙ να έχει ήδη
# καταχωρηθεί, χωρίς πρώτα να ρωτήσουμε την ΑΑΔΕ (RequestClients).
#
# Δύο μηχανισμοί συνεργάζονται:
#   1) real_aade._post_xml σημαδεύει τα αιτήματα με άγνωστη έκβαση
#      (indeterminate) αντί να κάνει τυφλό retry.
#   2) Εδώ, ΚΑΘΕ επαναποστολή περνά πρώτα από έλεγχο του τι ξέρει η ΑΑΔΕ.
# --------------------------------------------------------------------

# Πόσες σελίδες RequestClients σαρώνουμε το πολύ ψάχνοντας «ορφανή» εγγραφή
# (στάλθηκε, αλλά χάθηκε η απάντηση με το idDcl).
ORPHAN_SEARCH_MAX_PAGES = 20

# Χρονικό περιθώριο γύρω από τον χρόνο δημιουργίας όταν ψάχνουμε ορφανή
# εγγραφή. Γενναιόδωρο σκόπιμα: η ΑΑΔΕ επιστρέφει ώρα Ελλάδος ενώ εμείς
# κρατάμε UTC (διαφορά 2-3 ώρες), συν τυχόν απόκλιση ρολογιών. Το φίλτρο
# χρόνου είναι ΔΕΥΤΕΡΕΥΟΝ κριτήριο — το κύριο είναι πινακίδα + αχρησιμοποίητο
# idDcl — οπότε προτιμάμε ένα φαρδύ παράθυρο από ένα false negative που θα
# οδηγούσε σε διπλή καταχώρηση.
ORPHAN_TIME_MARGIN = timedelta(hours=6)


def _as_naive(dt):
    """
    Κόβει το tzinfo ώστε να συγκρίνονται datetimes χωρίς TypeError.

    Αναγκαίο γιατί στο ίδιο σημείο συναντιούνται τρεις πηγές: το utcnow()
    (tz-aware), οι στήλες DateTime (naive όταν διαβαστούν από τη βάση) και το
    _parse_aade_dt (naive ή aware, ανάλογα με το τι στέλνει η ΑΑΔΕ). Χωρίς
    αυτό, ο έλεγχος διπλοεγγραφής θα έσκαγε ακριβώς τη στιγμή που τον
    χρειαζόμαστε. (Η ρίζα του προβλήματος — μεικτές ζώνες ώρας στην ίδια
    στήλη — παραμένει· δες _parse_aade_dt.)
    """
    if dt is not None and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def _mark_indeterminate(entry, action):
    """Σημαδεύει ότι ο «Χρόνος» `action` στάλθηκε αλλά η έκβαση είναι άγνωστη."""
    entry.aade_state = "indeterminate"
    entry.aade_pending_method = action


def _clear_indeterminate(entry):
    entry.aade_state = None
    entry.aade_pending_method = None


def _fail_aade(entry, method, action, payload, result):
    """
    Κοινός χειρισμός αποτυχημένης κλήσης ΑΑΔΕ: audit log + commit (ώστε να
    μη χαθεί ό,τι έχει αποθηκευτεί τοπικά) + καθαρό σφάλμα στον χρήστη.

    Ξεχωρίζει τη ΒΕΒΑΙΗ αποτυχία (ξαναδοκίμασε ελεύθερα) από την ΑΓΝΩΣΤΗ
    έκβαση (μπορεί να καταχωρήθηκε — απαιτείται έλεγχος πρώτα).
    """
    _log_aade(entry.id if entry is not None else None, method, payload, result, False)
    if result.get("indeterminate") and entry is not None:
        _mark_indeterminate(entry, action)
        db.session.commit()
        raise ApiError(
            f"{result['error']} Πάτησε «Έλεγχος στην ΑΑΔΕ» για να διαπιστωθεί "
            "αν καταχωρήθηκε, πριν δοκιμάσεις ξανά.",
            502,
        )
    db.session.commit()
    raise ApiError(
        f"ΑΑΔΕ {method} error: {result['error']} — έλεγξε τα στοιχεία ΑΑΔΕ στις "
        "Ρυθμίσεις ή δοκίμασε ξανά σε λίγο.",
        502,
    )


def _use_mock(settings):
    """Ίδια λογική με _build_aade — το per-workshop override υπερισχύει."""
    return current_app.config["USE_MOCK_AADE"] and not settings.force_real_aade


def _request_around(aade, id_dcl):
    """
    RequestClients στενά γύρω από ΜΙΑ συγκεκριμένη εγγραφή.

    ΠΡΟΣΟΧΗ: το dclid της RequestClients είναι cursor (επιστρέφει εγγραφές με
    DCLID > dclid), όχι «δώσε μου αυτήν». Γι' αυτό ζητάμε [id_dcl-1, id_dcl].
    """
    if id_dcl and str(id_dcl).isdigit():
        target = int(id_dcl)
        return aade.request_clients(dclid=max(target - 1, 1), max_dclid=target)
    return aade.request_clients(dclid=1)


def _apply_aade_progress(entry, res):
    """
    Συγχρονίζει την τοπική εγγραφή με τα ΑΥΘΕΝΤΙΚΑ στοιχεία της ΑΑΔΕ — πηγή
    αλήθειας, ό,τι κι αν την ενημέρωσε (εμείς ή π.χ. το λογισμικό του λογιστή).

    Κοινή λογική για reconcile / έλεγχο πριν από επαναποστολή / verify, ώστε
    να μην υπάρχουν τρεις εκδοχές του «τι λέει η ΑΑΔΕ» που αποκλίνουν.

    @returns (updated_fields, aade_record|None)
    """
    aade_rec = _extract_aade_record(res, entry.id_dcl)
    if aade_rec is None:
        return [], None

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
    if category not in (None, "") and _parse_int(
        category, "providedServiceCategory"
    ) != entry.provided_service_category:
        entry.provided_service_category = _parse_int(category, "providedServiceCategory")
        updated.append("providedServiceCategory")
    other = aade_rec.get("providedServiceCategoryOther")
    if other and other != entry.provided_service_category_other:
        entry.provided_service_category_other = other
        updated.append("providedServiceCategoryOther")
    invoice_kind = aade_rec.get("invoiceKind")
    if invoice_kind not in (None, "") and _parse_int(
        invoice_kind, "invoiceKind"
    ) != entry.invoice_kind:
        entry.invoice_kind = _parse_int(invoice_kind, "invoiceKind")
        updated.append("invoiceKind")

    cancellation = _find_cancellation(res, entry.id_dcl)
    correlation = _find_correlation(res, entry.id_dcl)

    # Ιεράρχηση τελικής κατάστασης: ακύρωση > συσχέτιση ΜΑΡΚ > ολοκλήρωση
    # > σε εξέλιξη (2ος Χρόνος) > ό,τι ξέρουμε τοπικά.
    if cancellation is not None:
        new_status = "cancelled"
    elif correlation is not None:
        new_status = "correlated"
    elif str(aade_rec.get("entryCompletion")).lower() == "true":
        new_status = "completed"
        entry.entry_completion = True
    elif category not in (None, ""):
        new_status = "in_progress"
    else:
        new_status = entry.status

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

    return updated, aade_rec


def _aade_already_has(entry, action, res, aade_rec):
    """
    True αν η ΑΑΔΕ έχει ΗΔΗ καταχωρημένο αυτό που θα έστελνε το `action` —
    δηλαδή η επαναποστολή θα δημιουργούσε ΔΙΠΛΗ εγγραφή.
    """
    if action == "entry":
        return aade_rec is not None
    if aade_rec is None:
        return False
    if action == "service":
        return aade_rec.get("providedServiceCategory") not in (None, "")
    if action == "exit":
        return str(aade_rec.get("entryCompletion")).lower() == "true"
    if action == "correlate":
        return _find_correlation(res, entry.id_dcl) is not None
    return False


def _known_dcl_ids(workshop_id):
    """Όλα τα idDcl που ήδη χρησιμοποιούνται τοπικά — ώστε η αναζήτηση ορφανής
    εγγραφής να μη «υιοθετήσει» idDcl που ανήκει σε άλλη τοπική εγγραφή."""
    rows = (
        db.session.query(DclEntry.id_dcl)
        .filter(DclEntry.workshop_id == workshop_id, DclEntry.id_dcl.isnot(None))
        .all()
    )
    return {str(r[0]) for r in rows}


def _find_orphan_send(aade, workshop_id, plate, not_before):
    """
    Ψάχνει στην ΑΑΔΕ εγγραφή που ΕΜΕΙΣ στείλαμε αλλά της οποίας η απάντηση
    (και μαζί το idDcl) χάθηκε — το κλασικό read timeout στον 1ο Χρόνο.

    Χωρίς αυτόν τον έλεγχο, η μόνη επιλογή του χρήστη είναι «Επαναποστολή»,
    που δημιουργεί ΔΕΥΤΕΡΗ εγγραφή για το ίδιο όχημα χωρίς να το μάθει ποτέ.

    Κριτήρια ταύτισης (όλα μαζί):
      - ίδια πινακίδα (κανονικοποιημένη, ελληνικά/λατινικά αδιάφορα)
      - idDcl που ΔΕΝ χρησιμοποιείται ήδη από άλλη τοπική εγγραφή
      - χρόνος δημιουργίας μέσα στο ORPHAN_TIME_MARGIN από την προσπάθειά μας

    Ξεκινά τη σάρωση από το μεγαλύτερο idDcl που ήδη ξέρουμε (cursor), οπότε
    δεν ξανασαρώνει όλο το ιστορικό.

    @returns {"match": {...}|None} ή {"error": ...}
    """
    target = _normalize_plate(plate)
    not_before = _as_naive(not_before)
    taken = _known_dcl_ids(workshop_id)
    numeric = [int(x) for x in taken if str(x).isdigit()]
    dclid = max(numeric) - 1 if numeric else 0

    continuation = None
    for _ in range(ORPHAN_SEARCH_MAX_PAGES):
        res = aade.request_clients(dclid=dclid, continuation_token=continuation)
        if "error" in res:
            return {"error": res["error"]}

        clients = res.get("clients") or []
        if not clients:
            return {"match": None}

        for client in clients:
            init = client.get("InitialClientData", {}) or {}
            id_dcl = str(init.get("idDcl") or "").strip()
            if not id_dcl or id_dcl in taken:
                continue

            use_case = init.get("useCase") or {}
            found_plate = (use_case.get("garage") or {}).get(
                "vehicleRegistrationNumber"
            ) or (use_case.get("rental") or {}).get("vehicleRegistrationNumber")
            if not found_plate or _normalize_plate(found_plate) != target:
                continue

            created = _as_naive(_parse_aade_dt(init.get("creationDateTime")))
            if (
                created is not None
                and not_before is not None
                and created < not_before - ORPHAN_TIME_MARGIN
            ):
                continue

            return {
                "match": {"idDcl": id_dcl, "creationDateTime": created, "res": res}
            }

        continuation = res.get("continuationToken")
        if not continuation:
            return {"match": None}

    # Φτάσαμε στο όριο σελίδων χωρίς εύρεση — ΔΕΝ δηλώνουμε «δεν υπάρχει»,
    # γιατί ένα false negative εδώ σημαίνει διπλή καταχώρηση.
    return {"match": None, "truncated": True}


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
    # Στόλος οχημάτων (μόνο Ενοικιάσεις) — οι ΜΟΝΕΣ πινακίδες που επιτρέπεται
    # να επιλεγούν κατά τη δημιουργία νέας ενοικίασης (δες create_entry).
    # ----------------------------------------------------------------
    @app.route("/api/fleet-vehicles", methods=["GET"])
    @require_auth
    def list_fleet_vehicles():
        vehicles = (
            FleetVehicle.query.filter_by(workshop_id=g.workshop_id)
            .order_by(FleetVehicle.plate.asc())
            .all()
        )
        return jsonify([v.to_dict() for v in vehicles])

    @app.route("/api/fleet-vehicles", methods=["POST"])
    @require_auth
    def create_fleet_vehicle():
        data = request.get_json(silent=True) or {}
        plate = _canonical_plate((data.get("plate") or "").strip())
        if not plate:
            raise ApiError("Το πεδίο 'plate' (πινακίδα) είναι υποχρεωτικό.")

        existing = FleetVehicle.query.filter_by(
            workshop_id=g.workshop_id, plate=plate
        ).first()
        if existing is not None:
            raise ApiError("Η πινακίδα υπάρχει ήδη στον στόλο.")

        category = (data.get("category") or "").strip().lower() or None
        if category and category not in VEHICLE_CATEGORIES:
            raise ApiError("Μη έγκυρη κατηγορία οχήματος.")

        vehicle = FleetVehicle(
            workshop_id=g.workshop_id,
            plate=plate,
            label=(data.get("label") or "").strip() or None,
            category=category,
        )
        db.session.add(vehicle)
        db.session.commit()
        return jsonify(vehicle.to_dict()), 201

    @app.route("/api/fleet-vehicles/<int:vehicle_id>", methods=["PATCH"])
    @require_auth
    def update_fleet_vehicle(vehicle_id):
        vehicle = FleetVehicle.query.filter_by(
            id=vehicle_id, workshop_id=g.workshop_id
        ).first()
        if vehicle is None:
            raise ApiError("Δεν βρέθηκε το όχημα.", 404)

        data = request.get_json(silent=True) or {}
        if "plate" in data:
            plate = _canonical_plate((data.get("plate") or "").strip())
            if not plate:
                raise ApiError("Το πεδίο 'plate' (πινακίδα) είναι υποχρεωτικό.")
            dup = FleetVehicle.query.filter(
                FleetVehicle.workshop_id == g.workshop_id,
                FleetVehicle.plate == plate,
                FleetVehicle.id != vehicle_id,
            ).first()
            if dup is not None:
                raise ApiError("Η πινακίδα υπάρχει ήδη στον στόλο.")
            vehicle.plate = plate
        if "label" in data:
            vehicle.label = (data.get("label") or "").strip() or None
        if "category" in data:
            category = (data.get("category") or "").strip().lower() or None
            if category and category not in VEHICLE_CATEGORIES:
                raise ApiError("Μη έγκυρη κατηγορία οχήματος.")
            vehicle.category = category

        db.session.commit()
        return jsonify(vehicle.to_dict())

    @app.route("/api/fleet-vehicles/<int:vehicle_id>", methods=["DELETE"])
    @require_auth
    def delete_fleet_vehicle(vehicle_id):
        vehicle = FleetVehicle.query.filter_by(
            id=vehicle_id, workshop_id=g.workshop_id
        ).first()
        if vehicle is None:
            raise ApiError("Δεν βρέθηκε το όχημα.", 404)
        db.session.delete(vehicle)
        db.session.commit()
        return "", 204

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
        if _use_mock(settings):
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

        # --- Ενοικιάσεις: επιτρέπονται ΜΟΝΟ πινακίδες του δηλωμένου στόλου ---
        if is_rental:
            in_fleet = FleetVehicle.query.filter_by(
                workshop_id=g.workshop_id, plate=plate
            ).first()
            if in_fleet is None:
                raise ApiError(
                    "Η πινακίδα δεν ανήκει στον στόλο οχημάτων. Πρόσθεσέ την πρώτα "
                    "από το tab «Οχήματα»."
                )

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

        # --- Ενοικιάσεις: πόσες μέρες (προαιρετικό, ΔΕΝ πάει στην ΑΑΔΕ) ---
        # Χρησιμοποιείται μόνο τοπικά για να ειδοποιήσουμε αν καθυστερεί η
        # επιστροφή του οχήματος (δες DclEntry.is_overdue). Δεν είναι
        # υποχρεωτικό — αν δεν δοθεί, δεν γίνεται κανένας έλεγχος.
        rental_days = None
        expected_return_at = None
        if is_rental:
            raw_days = data.get("rentalExpectedDays")
            if raw_days not in (None, ""):
                rental_days = _parse_int(raw_days, "rentalExpectedDays")
                if rental_days <= 0:
                    raise ApiError("Το 'rentalExpectedDays' πρέπει να είναι θετικός αριθμός.")
                expected_return_at = utcnow() + timedelta(days=rental_days)

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
            rental_expected_days=rental_days,
            expected_return_at=expected_return_at,
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
            _fail_aade(entry, "SendClient", "entry", aade_payload, result)

        # Αποθήκευση απάντησης ΑΑΔΕ
        entry.id_dcl = result["idDcl"]
        entry.creation_date_time = utcnow()
        _clear_indeterminate(entry)
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
            _fail_aade(entry, "UpdateClient", "service", aade_payload, result)

        entry.status = "in_progress"
        _clear_indeterminate(entry)
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
        if reason_non_issue is not None:
            entry.reason_non_issue_type = _parse_int(reason_non_issue, "reasonNonIssueType")

        # --- Ενοικιάσεις: Συμφωνηθέν Ποσό (προαιρετικό ανά ΑΑΔΕ spec — π.χ.
        # Ιδιόχρηση/Δωρεάν Υπηρεσία δεν έχουν συμφωνηθέν ποσό) + (προαιρετικά)
        # τόπος επιστροφής ---
        if is_rental:
            amount = data.get("amount")
            if amount is not None and str(amount).strip() != "":
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
            _fail_aade(entry, "UpdateClient", "exit", aade_payload, result)

        # Η ΑΑΔΕ βάζει το completionDateTime
        entry.entry_completion = True
        entry.status = "completed"
        entry.completion_date_time = utcnow()
        _clear_indeterminate(entry)
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
            _fail_aade(entry, "ClientCorrelations", "correlate", aade_payload, result)

        entry.correlate_id = result["correlateId"]
        entry.status = "correlated"
        _clear_indeterminate(entry)
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
            _fail_aade(entry, "CancelClient", "cancel", {}, result)

        entry.status = "cancelled"
        _clear_indeterminate(entry)
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

        # ΦΡΑΓΜΟΣ #1: η προηγούμενη αποστολή έμεινε σε άγνωστη κατάσταση —
        # μπορεί να καταχωρήθηκε ήδη. Επαναποστολή εδώ = σχεδόν βέβαιη διπλή
        # εγγραφή στο Ψηφιακό Πελατολόγιο. Ο χρήστης πρέπει πρώτα να τρέξει
        # τον έλεγχο (/verify), που είτε τη συνδέει είτε ξεκαθαρίζει ότι
        # δεν καταχωρήθηκε ποτέ.
        if entry.aade_state == "indeterminate":
            raise ApiError(
                "Η προηγούμενη αποστολή δεν είχε σαφή απάντηση από την ΑΑΔΕ — "
                "η εγγραφή μπορεί να έχει ήδη καταχωρηθεί. Πάτησε πρώτα "
                "«Έλεγχος στην ΑΑΔΕ» ώστε να μη δημιουργηθεί διπλή εγγραφή.",
                409,
            )

        settings = _require_credentials()
        aade = _build_aade(settings)

        # ΦΡΑΓΜΟΣ #2: πριν ξαναστείλουμε ΟΤΙΔΗΠΟΤΕ, ρωτάμε την ΑΑΔΕ τι ξέρει
        # ήδη. Το «Επαναποστολή» υπάρχει για διακοπές δικτύου, αλλά μια
        # διακοπή ΜΕΤΑ την επιτυχή παραλαβή από την ΑΑΔΕ είναι εξίσου πιθανή
        # με μία πριν — και μόνο η ΑΑΔΕ ξέρει ποια από τις δύο συνέβη.
        # (Στο mock δεν έχει νόημα: δεν υπάρχει πραγματική κατάσταση εκεί.)
        if entry.id_dcl and not _use_mock(settings):
            check = _request_around(aade, entry.id_dcl)
            if "error" not in check:
                updated, aade_rec = _apply_aade_progress(entry, check)
                if _aade_already_has(entry, action, check, aade_rec):
                    _clear_indeterminate(entry)
                    db.session.commit()
                    payload = entry.to_dict()
                    payload["resendResult"] = "already_recorded"
                    payload["resendMessage"] = (
                        "Η ΑΑΔΕ έχει ήδη αυτή την καταχώρηση — δεν στάλθηκε "
                        "ξανά. Η τοπική εγγραφή συγχρονίστηκε."
                    )
                    payload["updated"] = updated
                    return jsonify(payload)
                # Δεν την έχει: συνεχίζουμε στην κανονική αποστολή παρακάτω,
                # κρατώντας ό,τι μάθαμε (π.χ. διορθωμένες ημερομηνίες).

        if action == "entry":
            is_rental = entry.client_service_type == 1
            # ⚠️ Το payload πρέπει να είναι ΤΑΥΤΟΣΗΜΟ με του create_entry —
            # τα vehicleCategory/vehicleFactory ζουν στον Customer (η αρχική
            # κλήση τα είχε από το request body, εδώ τα διαβάζουμε από τη βάση).
            customer = Customer.query.filter_by(
                plate=entry.plate, workshop_id=g.workshop_id
            ).first()
            aade_payload = {
                "vehicleRegistrationNumber": entry.plate,
                "branch": entry.branch,
                "clientServiceType": entry.client_service_type,
                "serviceType": entry.service_type,
                "useCase": "rental" if is_rental else "garage",
                "vehicleCategory": customer.vehicle_category if customer else None,
                "vehicleFactory": customer.vehicle_factory if customer else None,
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
            if entry.provided_service_category in (4, 6, 9):
                aade_payload["nonIssueInvoice"] = True
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
            if entry.reason_non_issue_type is not None:
                aade_payload["reasonNonIssueType"] = entry.reason_non_issue_type
                aade_payload["nonIssueInvoice"] = True
            result = aade.update_client(entry.id_dcl, aade_payload)
            method = "UpdateClient"
        else:  # "correlate"
            aade_payload = {"mark": entry.mark}
            result = aade.client_correlations(entry.id_dcl, aade_payload)
            method = "ClientCorrelations"

        if "error" in result:
            # Ίδιος χειρισμός με την αρχική αποστολή: αν η έκβαση είναι
            # άγνωστη, η εγγραφή σημαδεύεται και η επόμενη επαναποστολή
            # μπλοκάρεται μέχρι να γίνει έλεγχος.
            _fail_aade(entry, method, action, aade_payload, result)

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

        _clear_indeterminate(entry)
        _log_aade(entry.id, method, aade_payload, result, True)
        db.session.commit()
        payload = entry.to_dict()
        payload["resendResult"] = "sent"
        return jsonify(payload)

    # ----------------------------------------------------------------
    # Έλεγχος μετά από αποστολή ΑΓΝΩΣΤΗΣ έκβασης (aade_state="indeterminate")
    #
    # Απαντά στη μοναδική ερώτηση που δεν μπορεί να απαντήσει ο χρήστης:
    # «καταχωρήθηκε τελικά ή όχι;». Είναι η ΜΟΝΗ διέξοδος από το μπλόκο του
    # resend_entry — και ο λόγος που το μπλόκο είναι ανεκτό.
    # ----------------------------------------------------------------
    @app.route("/api/dcl/entries/<int:entry_id>/verify", methods=["POST"])
    @require_auth
    def verify_entry(entry_id):
        entry = _get_entry_or_404(entry_id)
        settings = _require_credentials()

        # Στο mock δεν υπάρχει πραγματική κατάσταση να ελεγχθεί — απλώς
        # ξεμπλοκάρουμε, αλλιώς η εγγραφή θα έμενε κολλημένη για πάντα.
        if _use_mock(settings):
            _clear_indeterminate(entry)
            db.session.commit()
            payload = entry.to_dict()
            payload["verification"] = "mock"
            payload["verificationMessage"] = (
                "Mock mode — δεν έγινε πραγματικός έλεγχος. Η εγγραφή "
                "ξεμπλοκαρίστηκε."
            )
            return jsonify(payload)

        aade = _build_aade(settings)

        # --- Περίπτωση Α: ξέρουμε το idDcl -> στοχευμένος έλεγχος ---
        if entry.id_dcl:
            res = _request_around(aade, entry.id_dcl)
            _log_aade(entry.id, "RequestClients", {"verify": entry.id_dcl}, res,
                      "error" not in res)
            if "error" in res:
                db.session.commit()
                raise ApiError(
                    f"Ο έλεγχος με την ΑΑΔΕ απέτυχε: {res['error']} "
                    "Η εγγραφή παραμένει σε αναμονή ελέγχου — δοκίμασε ξανά.",
                    502,
                )
            updated, aade_rec = _apply_aade_progress(entry, res)
            _clear_indeterminate(entry)
            db.session.commit()
            payload = entry.to_dict()
            payload["updated"] = updated
            payload["verification"] = "found" if aade_rec else "not_found"
            payload["verificationMessage"] = (
                "Η εγγραφή βρέθηκε στην ΑΑΔΕ και συγχρονίστηκε."
                if aade_rec
                else "Δεν βρέθηκε στην ΑΑΔΕ — μπορείς να ξαναστείλεις με ασφάλεια."
            )
            return jsonify(payload)

        # --- Περίπτωση Β: χάθηκε το idDcl -> αναζήτηση «ορφανής» εγγραφής ---
        # Αυτή είναι η επικίνδυνη περίπτωση: αν στα τυφλά ξαναστείλουμε και η
        # ΑΑΔΕ είχε ήδη καταχωρήσει, το όχημα μπαίνει δύο φορές στο πελατολόγιο.
        found = _find_orphan_send(
            aade, g.workshop_id, entry.plate, entry.created_at
        )
        _log_aade(
            entry.id,
            "RequestClients",
            {"verify": "orphan-search", "plate": entry.plate},
            {k: v for k, v in found.items() if k != "match"},
            "error" not in found,
        )

        if "error" in found:
            db.session.commit()
            raise ApiError(
                f"Ο έλεγχος με την ΑΑΔΕ απέτυχε: {found['error']} "
                "Η εγγραφή παραμένει σε αναμονή ελέγχου — δοκίμασε ξανά.",
                502,
            )

        match = found.get("match")
        if match:
            # Βρέθηκε: την υιοθετούμε αντί να στείλουμε δεύτερη.
            entry.id_dcl = match["idDcl"]
            entry.creation_date_time = match["creationDateTime"] or entry.creation_date_time
            updated, _ = _apply_aade_progress(entry, match["res"])
            _clear_indeterminate(entry)
            db.session.commit()
            payload = entry.to_dict()
            payload["updated"] = ["idDcl"] + updated
            payload["verification"] = "adopted"
            payload["verificationMessage"] = (
                f"Η εγγραφή ΕΙΧΕ καταχωρηθεί στην ΑΑΔΕ (idDcl {entry.id_dcl}) — "
                "συνδέθηκε τοπικά. Δεν χρειάζεται επαναποστολή."
            )
            return jsonify(payload)

        if found.get("truncated"):
            # Δεν σαρώσαμε όλο το εύρος: ΔΕΝ δηλώνουμε «δεν υπάρχει», γιατί
            # ένα λάθος εδώ οδηγεί κατευθείαν σε διπλή καταχώρηση.
            db.session.commit()
            raise ApiError(
                "Ο έλεγχος δεν ολοκληρώθηκε (πολλές εγγραφές προς σάρωση). "
                "Δοκίμασε «Εισαγωγή από ΑΑΔΕ» και μετά ξανά τον έλεγχο, ή "
                "επιβεβαίωσε χειροκίνητα στο myDATA πριν ξαναστείλεις.",
                409,
            )

        # Δεν καταχωρήθηκε ποτέ -> ασφαλές να ξαναστείλει ο χρήστης.
        _clear_indeterminate(entry)
        db.session.commit()
        payload = entry.to_dict()
        payload["verification"] = "not_found"
        payload["verificationMessage"] = (
            "Δεν βρέθηκε καμία αντίστοιχη εγγραφή στην ΑΑΔΕ — μπορείς να "
            "πατήσεις «Επαναποστολή» με ασφάλεια."
        )
        return jsonify(payload)

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
        if _use_mock(settings):
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

        res = _request_around(aade, entry.id_dcl)
        _log_aade(
            entry.id,
            "RequestClients",
            {"reconcile": entry.id_dcl},
            res,
            "error" not in res,
        )

        if "error" in res:
            db.session.commit()
            return jsonify({"ok": False, "reason": res["error"], "local": local})

        # Κοινή λογική συγχρονισμού με resend/verify — μία πηγή αλήθειας για
        # το «τι λέει η ΑΑΔΕ», ώστε οι τρεις διαδρομές να μην αποκλίνουν.
        updated, aade_rec = _apply_aade_progress(entry, res)
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

    # ----------------------------------------------------------------
    # Εισαγωγή από ΑΑΔΕ — φέρνει εγγραφές που υπάρχουν στο Ψηφιακό
    # Πελατολόγιο (RequestClients) αλλά όχι ακόμα τοπικά (π.χ. καταχωρήθηκαν
    # απευθείας στο back-office της ΑΑΔΕ, ή πριν συνδεθεί αυτή η εφαρμογή).
    # Το reconcile() ενημερώνει ό,τι ήδη ξέρουμε· αυτό φέρνει ό,τι λείπει.
    # ----------------------------------------------------------------
    @app.route("/api/dcl/import-from-aade", methods=["POST"])
    @require_auth
    def import_from_aade():
        settings = _get_settings()
        if not settings.has_key or not settings.aade_username:
            raise ApiError(
                "Δεν έχουν οριστεί οι κωδικοί ΑΑΔΕ — πήγαινε στις Ρυθμίσεις.", 400
            )

        if _use_mock(settings):
            return jsonify(
                {
                    "ok": True,
                    "mock": True,
                    "message": "Mock mode — δεν έγινε εισαγωγή από ΑΑΔΕ.",
                    "imported": 0,
                    "skipped": 0,
                }
            )

        aade = _build_aade(settings)

        existing_ids = {
            e.id_dcl
            for e in DclEntry.query.filter_by(workshop_id=g.workshop_id).all()
            if e.id_dcl
        }

        imported = 0
        skipped = 0
        dclid = 0
        continuation = None
        pages = 0
        MAX_PAGES = 200  # ασφαλιστική δικλείδα κατά ατέρμονου loop

        while pages < MAX_PAGES:
            res = aade.request_clients(dclid=dclid, continuation_token=continuation)
            _log_aade(
                None,
                "RequestClients",
                {"dclid": dclid, "continuationToken": continuation},
                res,
                "error" not in res,
            )
            if "error" in res:
                db.session.commit()
                return jsonify(
                    {
                        "ok": False,
                        "reason": res["error"],
                        "imported": imported,
                        "skipped": skipped,
                    }
                )

            clients = res.get("clients") or []
            if not clients:
                break

            for client in clients:
                init = client.get("InitialClientData", {}) or {}
                upd = client.get("UpdatedClientData", {}) or {}
                id_dcl = str(init.get("idDcl") or "").strip()
                if not id_dcl or id_dcl in existing_ids:
                    skipped += 1
                    continue

                use_case = init.get("useCase") or {}
                garage = use_case.get("garage") or {}
                rental = use_case.get("rental") or {}
                plate = (
                    garage.get("vehicleRegistrationNumber")
                    or rental.get("vehicleRegistrationNumber")
                    or "—"
                )

                cancellation = _find_cancellation(res, id_dcl)
                correlation = _find_correlation(res, id_dcl)
                category = upd.get("providedServiceCategory")

                if cancellation is not None:
                    status = "cancelled"
                elif correlation is not None:
                    status = "correlated"
                elif str(upd.get("entryCompletion")).lower() == "true":
                    status = "completed"
                elif category not in (None, ""):
                    status = "in_progress"
                else:
                    status = "open"

                entry = DclEntry(
                    workshop_id=g.workshop_id,
                    id_dcl=id_dcl,
                    plate=plate.strip().upper(),
                    branch=_opt_int(init.get("branch")) or settings.branch,
                    client_service_type=_opt_int(init.get("clientServiceType")) or 3,
                    status=status,
                    provided_service_category=_opt_int(category),
                    provided_service_category_other=upd.get(
                        "providedServiceCategoryOther"
                    ),
                    invoice_kind=_opt_int(upd.get("invoiceKind")),
                    creation_date_time=_parse_aade_dt(init.get("creationDateTime")),
                    completion_date_time=_parse_aade_dt(upd.get("completionDateTime")),
                    entry_completion=str(upd.get("entryCompletion")).lower() == "true",
                )
                if correlation is not None:
                    entry.mark = correlation.get("mark")
                    entry.correlate_id = correlation.get("correlateId")
                db.session.add(entry)
                existing_ids.add(id_dcl)
                imported += 1

            pages += 1
            continuation = res.get("continuationToken")
            if not continuation:
                break

        db.session.commit()
        return jsonify({"ok": True, "imported": imported, "skipped": skipped})


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

    # Dev convenience: εφαρμόζει αυτόματα τυχόν εκκρεμή migrations πριν το
    # boot — ώστε να ΜΗΝ χρειάζεται να θυμάσαι `alembic upgrade head` σε
    # κάθε `python app.py` (ίδιο ρόλο έπαιζε παλιότερα το db.create_all() +
    # _add_missing_columns που έτρεχαν μέσα στο create_app()).
    #
    # ΑΣΦΑΛΕΣ ΜΟΝΟ εδώ, ΟΧΙ στο create_app(): αυτό το block τρέχει ΜΙΑ φορά,
    # σε ΕΝΑ process, όταν κάποιος τρέχει `python app.py` απευθείας.
    # Ο gunicorn (production, δες render.yaml) ΔΕΝ περνά ποτέ από εδώ —
    # φορτώνει κατευθείαν το `app` module-level object, με πολλαπλούς
    # workers που θα έτρεχαν το ΙΔΙΟ migration ταυτόχρονα αν ήταν εδώ.
    # Στο production, το `alembic upgrade head` τρέχει ΜΙΑ φορά ως
    # preDeployCommand, πριν ξεκινήσουν οι workers.
    from alembic import command
    from alembic.config import Config as AlembicConfig

    from config import BASE_DIR

    _alembic_ini = os.path.join(BASE_DIR, "alembic.ini")
    command.upgrade(AlembicConfig(_alembic_ini), "head")

    # Default 5001 — το 5000 το κρατάει συχνά το AirPlay Receiver στο macOS.
    port = int(os.getenv("PORT", "5001"))
    # debug: ΠΟΤΕ True by default σε production (Werkzeug debugger = RCE risk).
    # Ακολουθεί το config.py (FLASK_DEBUG / FLASK_ENV=development).
    app.run(host="0.0.0.0", port=port, debug=app.config["DEBUG"])
