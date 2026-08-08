"""
routes_dcl.py
--------------------------------------------------------------------
Οι 4 Χρόνοι της ΑΑΔΕ (SendClient/UpdateClient/UpdateClient/ClientCorrelations
+ CancelClient) + λίστα/λεπτομέρειες εγγραφών, επαναποστολή, verify,
reconciliation, εισαγωγή από ΑΑΔΕ.

Η κοινή λογική επεξεργασίας ΑΑΔΕ (_build_aade, _apply_aade_progress,
_find_orphan_send, κλπ) ζει στο aade_core.py — μοιράζεται με routes_settings
(test-connection) και είναι πολύ πιο ευανάγνωστη σαν ΕΝΑ cohesive module παρά
σκορπισμένη.
--------------------------------------------------------------------
"""
from datetime import timedelta

import aade_core
from auth import require_auth
from flask import Blueprint, g, jsonify, request
from models import Customer, DclEntry, FleetVehicle, db, utcnow

dcl_bp = Blueprint("dcl", __name__)


# ----------------------------------------------------------------
# 1ος ΧΡΟΝΟΣ — SendClient
# Δημιουργία εγγραφής Ψηφιακού Πελατολογίου. Η ΑΑΔΕ επιστρέφει
# τον Μοναδικό Αριθμό Εγγραφής (idDcl) και την ώρα δημιουργίας.
# ----------------------------------------------------------------
@dcl_bp.route("/api/dcl/entry", methods=["POST"])
@require_auth
def create_entry():
    data = request.get_json(silent=True) or {}

    # Guard: πρέπει να έχουν οριστεί credentials ΑΑΔΕ
    settings = aade_core._require_credentials()
    aade = aade_core._build_aade(settings)
    workshop = aade_core._get_workshop()
    is_rental = workshop.client_service_type == 1

    # Κανονικοποίηση ΕΔΩ (όχι μόνο στο frontend): η ίδια πινακίδα σε
    # ελληνικά/λατινικά γράμματα πρέπει ΠΑΝΤΑ να καταλήγει στον ΙΔΙΟ
    # Customer — αλλιώς το unique constraint plate+workshop δημιουργεί
    # σιωπηλά διπλότυπους πελάτες για την ίδια πινακίδα.
    plate = aade_core._canonical_plate((data.get("plate") or "").strip())
    # Το branch έρχεται ΑΠΟ ΤΙΣ ΡΥΘΜΙΣΕΙΣ (όχι hardcoded/από το body)
    branch = settings.branch

    if not plate:
        raise aade_core.ApiError("Το πεδίο 'plate' (πινακίδα) είναι υποχρεωτικό.")

    # --- Ενοικιάσεις: επιτρέπονται ΜΟΝΟ πινακίδες του δηλωμένου στόλου ---
    if is_rental:
        in_fleet = FleetVehicle.query.filter_by(
            workshop_id=g.workshop_id, plate=plate
        ).first()
        if in_fleet is None:
            raise aade_core.ApiError(
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
            raise aade_core.ApiError("Το πεδίο 'vehicleMovementPurpose' (Σκοπός Κίνησης) είναι υποχρεωτικό για Ενοικιάσεις.")
        movement_purpose = aade_core._parse_int(movement_purpose, "vehicleMovementPurpose")
        if movement_purpose not in (1, 2, 3):
            raise aade_core.ApiError("Το 'vehicleMovementPurpose' πρέπει να είναι 1, 2 ή 3.")
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
            rental_days = aade_core._parse_int(raw_days, "rentalExpectedDays")
            if rental_days <= 0:
                raise aade_core.ApiError("Το 'rentalExpectedDays' πρέπει να είναι θετικός αριθμός.")
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
        created_by_employee_id=g.actor_id,
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
        aade_core._fail_aade(entry, "SendClient", "entry", aade_payload, result)

    # Αποθήκευση απάντησης ΑΑΔΕ
    entry.id_dcl = result["idDcl"]
    entry.creation_date_time = utcnow()
    aade_core._clear_indeterminate(entry)
    aade_core._log_aade(entry.id, "SendClient", aade_payload, result, True)
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
@dcl_bp.route("/api/dcl/service", methods=["POST"])
@require_auth
def add_service():
    data = request.get_json(silent=True) or {}

    entry = aade_core._get_entry_or_404(data.get("entry_id"))
    if entry.client_service_type == 1:
        raise aade_core.ApiError("Οι Ενοικιάσεις δεν έχουν 2ο Χρόνο (κατηγορία υπηρεσίας) — προχώρα κατευθείαν στην Ολοκλήρωση.")
    aade = aade_core._build_aade(aade_core._require_credentials())

    category = data.get("providedServiceCategory")
    if category is None:
        raise aade_core.ApiError("Το πεδίο 'providedServiceCategory' είναι υποχρεωτικό.")

    category = aade_core._parse_int(category, "providedServiceCategory")
    other = data.get("providedServiceCategoryOther")

    # Validation: αν κατηγορία == 5 (Άλλο), το 'other' είναι υποχρεωτικό
    if category == 5 and not (other and str(other).strip()):
        raise aade_core.ApiError(
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
        aade_core._fail_aade(entry, "UpdateClient", "service", aade_payload, result)

    entry.status = "in_progress"
    aade_core._clear_indeterminate(entry)
    aade_core._log_aade(entry.id, "UpdateClient", aade_payload, result, True)
    db.session.commit()

    return jsonify(
        {"updateUniqueId": result["updateUniqueId"], "status": entry.status}
    )


# ----------------------------------------------------------------
# 3ος ΧΡΟΝΟΣ — UpdateClient με entryCompletion=true (ολοκλήρωση)
# Η ΑΑΔΕ επιστρέφει το completionDateTime.
# ----------------------------------------------------------------
@dcl_bp.route("/api/dcl/exit", methods=["POST"])
@require_auth
def complete_entry():
    data = request.get_json(silent=True) or {}

    entry = aade_core._get_entry_or_404(data.get("entry_id"))
    aade = aade_core._build_aade(aade_core._require_credentials())
    is_rental = entry.client_service_type == 1

    invoice_kind = data.get("invoiceKind")
    reason_non_issue = data.get("reasonNonIssueType")

    if invoice_kind is None and reason_non_issue is None:
        raise aade_core.ApiError(
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
        raise aade_core.ApiError(
            "Η κατηγορία υπηρεσίας που επιλέχθηκε (Δωρεάν/Εγγύηση/Ιδιόχρηση) "
            "δεν εκδίδει παραστατικό — επίλεξε «Δεν εκδίδεται παραστατικό» "
            "αντί για είδος παραστατικού."
        )

    if invoice_kind is not None:
        entry.invoice_kind = aade_core._parse_int(invoice_kind, "invoiceKind")
    if reason_non_issue is not None:
        entry.reason_non_issue_type = aade_core._parse_int(reason_non_issue, "reasonNonIssueType")

    # --- Ενοικιάσεις: Συμφωνηθέν Ποσό (προαιρετικό ανά ΑΑΔΕ spec — π.χ.
    # Ιδιόχρηση/Δωρεάν Υπηρεσία δεν έχουν συμφωνηθέν ποσό) + (προαιρετικά)
    # τόπος επιστροφής ---
    if is_rental:
        amount = data.get("amount")
        if amount is not None and str(amount).strip() != "":
            try:
                entry.amount = float(amount)
            except (TypeError, ValueError):
                raise aade_core.ApiError("Το πεδίο 'amount' πρέπει να είναι αριθμός.")
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
        aade_payload["reasonNonIssueType"] = aade_core._parse_int(
            reason_non_issue, "reasonNonIssueType"
        )
        # Μη έκδοση παραστατικού
        aade_payload["nonIssueInvoice"] = True
    result = aade.update_client(entry.id_dcl, aade_payload)

    if "error" in result:
        aade_core._fail_aade(entry, "UpdateClient", "exit", aade_payload, result)

    # Η ΑΑΔΕ βάζει το completionDateTime
    entry.entry_completion = True
    entry.status = "completed"
    entry.completion_date_time = utcnow()
    aade_core._clear_indeterminate(entry)
    aade_core._log_aade(entry.id, "UpdateClient", aade_payload, result, True)
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
@dcl_bp.route("/api/dcl/correlate", methods=["POST"])
@require_auth
def correlate_entry():
    data = request.get_json(silent=True) or {}

    entry = aade_core._get_entry_or_404(data.get("entry_id"))
    aade = aade_core._build_aade(aade_core._require_credentials())

    mark = data.get("mark")
    if not mark:
        raise aade_core.ApiError("Το πεδίο 'mark' (ΜΑΡΚ παραστατικού) είναι υποχρεωτικό.")

    entry.mark = str(mark)
    # status προχωράει σε "correlated" ΜΟΝΟ μετά από επιβεβαιωμένη επιτυχία.

    # Κλήση ΑΑΔΕ (mock) — 4ος Χρόνος
    aade_payload = {"mark": str(mark)}
    result = aade.client_correlations(entry.id_dcl, aade_payload)

    if "error" in result:
        aade_core._fail_aade(entry, "ClientCorrelations", "correlate", aade_payload, result)

    entry.correlate_id = result["correlateId"]
    entry.status = "correlated"
    aade_core._clear_indeterminate(entry)
    aade_core._log_aade(entry.id, "ClientCorrelations", aade_payload, result, True)
    db.session.commit()

    return jsonify({"correlateId": entry.correlate_id, "status": entry.status})


# ----------------------------------------------------------------
# CancelClient — ακύρωση εγγραφής
# ----------------------------------------------------------------
@dcl_bp.route("/api/dcl/cancel", methods=["POST"])
@require_auth
def cancel_entry():
    data = request.get_json(silent=True) or {}

    entry = aade_core._get_entry_or_404(data.get("entry_id"))
    aade = aade_core._build_aade(aade_core._require_credentials())

    result = aade.cancel_client(entry.id_dcl)

    if "error" in result:
        aade_core._fail_aade(entry, "CancelClient", "cancel", {}, result)

    entry.status = "cancelled"
    aade_core._clear_indeterminate(entry)
    aade_core._log_aade(entry.id, "CancelClient", {}, result, True)
    db.session.commit()

    return jsonify(
        {"cancellationId": result["cancellationId"], "status": entry.status}
    )


# ----------------------------------------------------------------
# Λίστα εγγραφών & λεπτομέρειες
# ----------------------------------------------------------------
@dcl_bp.route("/api/dcl/entries", methods=["GET"])
@require_auth
def list_entries():
    # Χωρίς όριο, αυτό το endpoint γυρνάει ΟΛΟ το ιστορικό του workshop σε
    # ΚΑΘΕ φόρτωση (π.χ. 7.000+ εγγραφές/χρόνο για ένα ενεργό συνεργείο) —
    # αργό σε κινητό/4G και άσκοπο, αφού τα tabs "Λειτουργία"/"Εγγραφές"
    # χρειάζονται μόνο τις πρόσφατες. limit/offset για βαθύτερη αναζήτηση.
    limit = min(aade_core._parse_int(request.args.get("limit", 200), "limit"), 500)
    offset = max(aade_core._parse_int(request.args.get("offset", 0), "offset"), 0)
    query = (
        DclEntry.query.filter_by(workshop_id=g.workshop_id)
        .order_by(DclEntry.created_at.desc())
    )
    total = query.count()
    entries = query.offset(offset).limit(limit).all()
    response = jsonify([e.to_dict() for e in entries])
    response.headers["X-Total-Count"] = str(total)
    return response


@dcl_bp.route("/api/dcl/entries/<int:entry_id>", methods=["GET"])
@require_auth
def get_entry(entry_id):
    entry = aade_core._get_entry_or_404(entry_id)
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
@dcl_bp.route("/api/dcl/entries/<int:entry_id>/resend", methods=["POST"])
@require_auth
def resend_entry(entry_id):
    entry = aade_core._get_entry_or_404(entry_id)
    action = entry.pending_action
    if action is None:
        raise aade_core.ApiError("Δεν υπάρχει κάτι εκκρεμές προς επαναποστολή για αυτή την εγγραφή.")

    # ΦΡΑΓΜΟΣ #1: η προηγούμενη αποστολή έμεινε σε άγνωστη κατάσταση —
    # μπορεί να καταχωρήθηκε ήδη. Επαναποστολή εδώ = σχεδόν βέβαιη διπλή
    # εγγραφή στο Ψηφιακό Πελατολόγιο. Ο χρήστης πρέπει πρώτα να τρέξει
    # τον έλεγχο (/verify), που είτε τη συνδέει είτε ξεκαθαρίζει ότι
    # δεν καταχωρήθηκε ποτέ.
    if entry.aade_state == "indeterminate":
        raise aade_core.ApiError(
            "Η προηγούμενη αποστολή δεν είχε σαφή απάντηση από την ΑΑΔΕ — "
            "η εγγραφή μπορεί να έχει ήδη καταχωρηθεί. Πάτησε πρώτα "
            "«Έλεγχος στην ΑΑΔΕ» ώστε να μη δημιουργηθεί διπλή εγγραφή.",
            409,
        )

    settings = aade_core._require_credentials()
    aade = aade_core._build_aade(settings)

    # ΦΡΑΓΜΟΣ #2: πριν ξαναστείλουμε ΟΤΙΔΗΠΟΤΕ, ρωτάμε την ΑΑΔΕ τι ξέρει
    # ήδη. Το «Επαναποστολή» υπάρχει για διακοπές δικτύου, αλλά μια
    # διακοπή ΜΕΤΑ την επιτυχή παραλαβή από την ΑΑΔΕ είναι εξίσου πιθανή
    # με μία πριν — και μόνο η ΑΑΔΕ ξέρει ποια από τις δύο συνέβη.
    # (Στο mock δεν έχει νόημα: δεν υπάρχει πραγματική κατάσταση εκεί.)
    if entry.id_dcl and not aade_core._use_mock(settings):
        check = aade_core._request_around(aade, entry.id_dcl)
        if "error" not in check:
            updated, aade_rec = aade_core._apply_aade_progress(entry, check)
            if aade_core._aade_already_has(entry, action, check, aade_rec):
                aade_core._clear_indeterminate(entry)
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
        aade_core._fail_aade(entry, method, action, aade_payload, result)

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

    aade_core._clear_indeterminate(entry)
    aade_core._log_aade(entry.id, method, aade_payload, result, True)
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
@dcl_bp.route("/api/dcl/entries/<int:entry_id>/verify", methods=["POST"])
@require_auth
def verify_entry(entry_id):
    entry = aade_core._get_entry_or_404(entry_id)
    settings = aade_core._require_credentials()

    # Στο mock δεν υπάρχει πραγματική κατάσταση να ελεγχθεί — απλώς
    # ξεμπλοκάρουμε, αλλιώς η εγγραφή θα έμενε κολλημένη για πάντα.
    if aade_core._use_mock(settings):
        aade_core._clear_indeterminate(entry)
        db.session.commit()
        payload = entry.to_dict()
        payload["verification"] = "mock"
        payload["verificationMessage"] = (
            "Mock mode — δεν έγινε πραγματικός έλεγχος. Η εγγραφή "
            "ξεμπλοκαρίστηκε."
        )
        return jsonify(payload)

    aade = aade_core._build_aade(settings)

    # --- Περίπτωση Α: ξέρουμε το idDcl -> στοχευμένος έλεγχος ---
    if entry.id_dcl:
        res = aade_core._request_around(aade, entry.id_dcl)
        aade_core._log_aade(entry.id, "RequestClients", {"verify": entry.id_dcl}, res,
                       "error" not in res)
        if "error" in res:
            db.session.commit()
            raise aade_core.ApiError(
                f"Ο έλεγχος με την ΑΑΔΕ απέτυχε: {res['error']} "
                "Η εγγραφή παραμένει σε αναμονή ελέγχου — δοκίμασε ξανά.",
                502,
            )
        updated, aade_rec = aade_core._apply_aade_progress(entry, res)
        aade_core._clear_indeterminate(entry)
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
    found = aade_core._find_orphan_send(
        aade, g.workshop_id, entry.plate, entry.created_at
    )
    aade_core._log_aade(
        entry.id,
        "RequestClients",
        {"verify": "orphan-search", "plate": entry.plate},
        {k: v for k, v in found.items() if k != "match"},
        "error" not in found,
    )

    if "error" in found:
        db.session.commit()
        raise aade_core.ApiError(
            f"Ο έλεγχος με την ΑΑΔΕ απέτυχε: {found['error']} "
            "Η εγγραφή παραμένει σε αναμονή ελέγχου — δοκίμασε ξανά.",
            502,
        )

    match = found.get("match")
    if match:
        # Βρέθηκε: την υιοθετούμε αντί να στείλουμε δεύτερη.
        entry.id_dcl = match["idDcl"]
        entry.creation_date_time = match["creationDateTime"] or entry.creation_date_time
        updated, _ = aade_core._apply_aade_progress(entry, match["res"])
        aade_core._clear_indeterminate(entry)
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
        raise aade_core.ApiError(
            "Ο έλεγχος δεν ολοκληρώθηκε (πολλές εγγραφές προς σάρωση). "
            "Δοκίμασε «Εισαγωγή από ΑΑΔΕ» και μετά ξανά τον έλεγχο, ή "
            "επιβεβαίωσε χειροκίνητα στο myDATA πριν ξαναστείλεις.",
            409,
        )

    # Δεν καταχωρήθηκε ποτέ -> ασφαλές να ξαναστείλει ο χρήστης.
    aade_core._clear_indeterminate(entry)
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
@dcl_bp.route("/api/dcl/reconcile/<int:entry_id>", methods=["GET"])
@require_auth
def reconcile(entry_id):
    entry = aade_core._get_entry_or_404(entry_id)

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
    settings = aade_core._get_settings()
    if aade_core._use_mock(settings):
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
        raise aade_core.ApiError(
            "Δεν έχουν οριστεί οι κωδικοί ΑΑΔΕ — πήγαινε στις Ρυθμίσεις.", 400
        )
    aade = aade_core._build_aade(settings)

    res = aade_core._request_around(aade, entry.id_dcl)
    aade_core._log_aade(
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
    updated, aade_rec = aade_core._apply_aade_progress(entry, res)
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
@dcl_bp.route("/api/dcl/import-from-aade", methods=["POST"])
@require_auth
def import_from_aade():
    settings = aade_core._get_settings()
    if not settings.has_key or not settings.aade_username:
        raise aade_core.ApiError(
            "Δεν έχουν οριστεί οι κωδικοί ΑΑΔΕ — πήγαινε στις Ρυθμίσεις.", 400
        )

    if aade_core._use_mock(settings):
        return jsonify(
            {
                "ok": True,
                "mock": True,
                "message": "Mock mode — δεν έγινε εισαγωγή από ΑΑΔΕ.",
                "imported": 0,
                "skipped": 0,
            }
        )

    aade = aade_core._build_aade(settings)

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
        aade_core._log_aade(
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

            cancellation = aade_core._find_cancellation(res, id_dcl)
            correlation = aade_core._find_correlation(res, id_dcl)
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
                branch=aade_core._opt_int(init.get("branch")) or settings.branch,
                client_service_type=aade_core._opt_int(init.get("clientServiceType")) or 3,
                status=status,
                provided_service_category=aade_core._opt_int(category),
                provided_service_category_other=upd.get(
                    "providedServiceCategoryOther"
                ),
                invoice_kind=aade_core._opt_int(upd.get("invoiceKind")),
                creation_date_time=aade_core._parse_aade_dt(init.get("creationDateTime")),
                completion_date_time=aade_core._parse_aade_dt(upd.get("completionDateTime")),
                entry_completion=str(upd.get("entryCompletion")).lower() == "true",
            )
            if correlation is not None:
                entry.mark = correlation.get("mark")
                entry.correlate_id = correlation.get("correlateId")
            db.session.add(entry)
            existing_ids.add(id_dcl)
            imported += 1

        # Commit ΑΝΑ ΣΕΛΙΔΑ, όχι μία φορά στο τέλος: με έως 200 σελίδες ×
        # κλήση ΑΑΔΕ, το request υπερβαίνει εύκολα το gunicorn timeout ή
        # χάνει το δίκτυο στη μέση. Με ένα τελικό commit, ΟΛΗ η δουλειά
        # (π.χ. 150 σελίδες) χανόταν και ο χρήστης ξεκινούσε από την
        # αρχή — για να ξαναποτύχει στο ίδιο σημείο. Ό,τι έχει ήδη
        # εισαχθεί παραμένει, και το existing_ids το κρατά idempotent.
        db.session.commit()

        pages += 1
        continuation = res.get("continuationToken")
        if not continuation:
            break

    db.session.commit()
    return jsonify({"ok": True, "imported": imported, "skipped": skipped})
