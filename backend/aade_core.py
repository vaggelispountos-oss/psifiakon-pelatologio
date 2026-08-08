"""
aade_core.py
--------------------------------------------------------------------
Κοινή λογική επεξεργασίας ΑΑΔΕ — μοιρασμένη ανάμεσα σε routes_dcl.py
(οι 4 Χρόνοι) και routes_settings.py (test-connection). Ξεχωριστό module
(όχι μέσα σε app.py) ώστε τα blueprint route-modules να το εισάγουν
κανονικά (`import aade_core`) χωρίς κυκλική εξάρτηση με το app.py — που
θα ήταν εύθραυστη ανάλογα με το ΠΩΣ τρέχει το app.py (`python app.py`
φορτώνει το αρχείο ως `__main__`, όχι ως module `app`).
--------------------------------------------------------------------
"""
import json
import re
import threading
import uuid
from datetime import datetime, timedelta

import requests
from flask import current_app, g

from mock_aade import MockAadeService
from models import AadeLog, DclEntry, Settings, Workshop, db


def _log_aade(entry_id, method, request_payload, response_payload, success):
    """
    Καταγραφή κλήσης ΑΑΔΕ στο audit log. Καλείται ΠΑΝΤΑ μέσα σε
    authenticated request (g.workshop_id υπάρχει ήδη) — ακόμα και τα logs
    χωρίς dcl_entry_id (π.χ. «Έλεγχος σύνδεσης») ανήκουν σε συγκεκριμένο
    συνεργείο, γι' αυτό γράφεται εδώ ρητά αντί να μένει None.
    """
    log = AadeLog(
        workshop_id=g.workshop_id,
        actor_employee_id=g.actor_id,
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
