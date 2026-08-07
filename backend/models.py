"""
models.py
Ορισμός των μοντέλων SQLAlchemy για το Ψηφιακό Πελατολόγιο Οχημάτων (ΑΑΔΕ).

Multi-tenant: κάθε συνεργείο (Workshop) βλέπει ΜΟΝΟ τα δικά του δεδομένα.
Όλα τα tenant-scoped μοντέλα (Customer, DclEntry, OcrMetric, Settings) έχουν
workshop_id FK — filtering γίνεται σε ΚΑΘΕ query στο app.py μέσω g.workshop_id
(δες auth.py: require_auth).
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

import crypto

db = SQLAlchemy()


def utcnow():
    """Τρέχουσα ώρα σε UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


class Workshop(db.Model):
    """Ένας πελάτης-συνεργείο (tenant) του SaaS. Ένας λογαριασμός = ένα Workshop."""

    __tablename__ = "workshops"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # trial | active | past_due | cancelled — έλεγχος πρόσβασης βάσει αυτού
    # γίνεται όταν προστεθεί το billing layer (Stripe). Προς το παρόν "trial".
    subscription_status = db.Column(db.String(20), default="trial", nullable=False)
    # garage (Συνεργείο, clientServiceType=3) | rental (Ενοικίαση Οχημάτων,
    # clientServiceType=1) — επιλέγεται ΜΙΑ φορά στην εγγραφή, καθορίζει ποια
    # ροή/πεδία ΑΑΔΕ χρησιμοποιεί ολόκληρη η εφαρμογή για αυτό το workshop.
    # Nullable για να μην σπάνε παλιές εγκαταστάσεις χωρίς τη στήλη (auto-
    # migration προσθέτει μόνο nullable) — None αντιμετωπίζεται ως "garage"
    # (δες BUSINESS_TYPE_DEFAULT στο app.py).
    business_type = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    # Πότε αποδέχθηκε τους Όρους Χρήσης / Πολιτική Απορρήτου. Nullable ώστε
    # η auto-migration (app.py:_add_missing_columns) να το προσθέσει χωρίς
    # να σπάσει υπάρχοντα workshops (δες BUSINESS_TYPE_DEFAULT σχόλιο πιο πάνω).
    terms_accepted_at = db.Column(db.DateTime, nullable=True)
    # Πότε λήγει η δωρεάν δοκιμαστική περίοδος (μπαίνει στην εγγραφή, δες
    # auth.register). Nullable για παλιά workshops πριν τη στήλη — το
    # require_auth πέφτει τότε σε created_at + TRIAL_DAYS (δες auth.py).
    trial_ends_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def effective_business_type(self):
        return self.business_type or "garage"

    @property
    def client_service_type(self):
        """Κωδικός Τύπου Πελατολογίου ΑΑΔΕ: 1=Ενοικιάσεις, 3=Συνεργεία."""
        return 1 if self.effective_business_type == "rental" else 3

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "subscriptionStatus": self.subscription_status,
            "businessType": self.effective_business_type,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class Customer(db.Model):
    """Πελάτης / όχημα του συνεργείου."""

    __tablename__ = "customers"
    __table_args__ = (
        db.UniqueConstraint("workshop_id", "plate", name="uq_customer_workshop_plate"),
    )

    id = db.Column(db.Integer, primary_key=True)
    workshop_id = db.Column(
        db.Integer, db.ForeignKey("workshops.id"), nullable=False, index=True
    )
    name = db.Column(db.String(255), nullable=True)
    plate = db.Column(db.String(20), nullable=False)
    vat = db.Column(db.String(20), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    vehicle_category = db.Column(db.String(50), nullable=True)
    vehicle_factory = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "plate": self.plate,
            "vat": self.vat,
            "phone": self.phone,
            "vehicleCategory": self.vehicle_category,
            "vehicleFactory": self.vehicle_factory,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class FleetVehicle(db.Model):
    """Όχημα του στόλου ενός συνεργείου ενοικιάσεων — μόνο αυτές οι πινακίδες
    επιτρέπεται να επιλεγούν κατά τη δημιουργία νέας ενοικίασης."""

    __tablename__ = "fleet_vehicles"
    __table_args__ = (
        db.UniqueConstraint("workshop_id", "plate", name="uq_fleet_workshop_plate"),
    )

    id = db.Column(db.Integer, primary_key=True)
    workshop_id = db.Column(
        db.Integer, db.ForeignKey("workshops.id"), nullable=False, index=True
    )
    plate = db.Column(db.String(20), nullable=False)
    label = db.Column(db.String(100), nullable=True)  # π.χ. "Toyota Yaris λευκό"
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "plate": self.plate,
            "label": self.label,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class DclEntry(db.Model):
    """
    Μία εγγραφή Ψηφιακού Πελατολογίου (ΑΑΔΕ).

    Η ροή της ΑΑΔΕ έχει 4 «Χρόνους»:
      1ος Χρόνος (SendClient)        -> δημιουργία εγγραφής, παίρνουμε id_dcl + creation_date_time
      2ος Χρόνος (UpdateClient)      -> καταχώρηση κατηγορίας παρεχόμενης υπηρεσίας
      3ος Χρόνος (UpdateClient+exit) -> ολοκλήρωση (entry_completion=True) -> completion_date_time
      4ος Χρόνος (ClientCorrelations)-> συσχέτιση παραστατικού (ΜΑΡΚ) -> correlate_id
    """

    __tablename__ = "dcl_entries"

    id = db.Column(db.Integer, primary_key=True)
    workshop_id = db.Column(
        db.Integer, db.ForeignKey("workshops.id"), nullable=False, index=True
    )

    # Μοναδικός Αριθμός Εγγραφής που επιστρέφει η ΑΑΔΕ στον 1ο Χρόνο
    id_dcl = db.Column(db.String(50), nullable=True)

    plate = db.Column(db.String(20), nullable=False)  # vehicleRegistrationNumber
    branch = db.Column(db.Integer, nullable=False)  # αριθμός εγκατάστασης (υποχρεωτικό)

    # 3 = Συνεργεία
    client_service_type = db.Column(db.Integer, default=3, nullable=False)
    # Τύπος υπηρεσίας. Default "apax" = Άπαξ
    service_type = db.Column(db.String(20), default="apax", nullable=False)

    # --- 2ος Χρόνος (ΜΟΝΟ Συνεργεία — clientServiceType=3) ---
    provided_service_category = db.Column(db.Integer, nullable=True)
    provided_service_category_other = db.Column(db.String(255), nullable=True)

    # --- Ενοικιάσεις (clientServiceType=1) — δεν υπάρχει 2ος Χρόνος, οι
    # Ενοικιάσεις πάνε κατευθείαν από 1ο σε 3ο Χρόνο. Πεδία του rental
    # useCase (1ος Χρόνος) + του updateClientType (3ος Χρόνος).
    vehicle_movement_purpose = db.Column(db.Integer, nullable=True)  # 1ος Χρόνος
    is_diff_pickup_location = db.Column(db.Boolean, nullable=True)  # 1ος Χρόνος
    vehicle_pickup_location = db.Column(db.String(250), nullable=True)  # 1ος Χρόνος
    is_diff_return_location = db.Column(db.Boolean, nullable=True)  # 3ος Χρόνος
    vehicle_return_location = db.Column(db.String(250), nullable=True)  # 3ος Χρόνος
    amount = db.Column(db.Float, nullable=True)  # 3ος Χρόνος — Συμφωνηθέν Ποσό (προαιρετικό ανά ΑΑΔΕ spec)

    # --- 3ος Χρόνος ---
    entry_completion = db.Column(db.Boolean, default=False, nullable=False)
    # 1=ΑΛΠ/ΑΠΥ, 2=Τιμολόγιο, 3=ΑΛΠ/ΑΠΥ-ΦΗΜ
    invoice_kind = db.Column(db.Integer, nullable=True)
    # Εναλλακτικά του invoice_kind — 1=Δωρεάν Υπηρεσία, 2=Ιδιόχρηση,
    # 3=Αποζημίωση Εγγύησης. Όταν οριστεί, ΔΕΝ εκδίδεται παραστατικό.
    reason_non_issue_type = db.Column(db.Integer, nullable=True)

    # Ημερομηνίες που ΒΑΖΕΙ Η ΑΑΔΕ
    creation_date_time = db.Column(db.DateTime, nullable=True)  # 1ος Χρόνος
    completion_date_time = db.Column(db.DateTime, nullable=True)  # 3ος Χρόνος

    # --- 4ος Χρόνος ---
    mark = db.Column(db.String(50), nullable=True)  # ΜΑΡΚ παραστατικού
    correlate_id = db.Column(db.String(50), nullable=True)  # επιστρέφει η ΑΑΔΕ

    # open | in_progress | completed | correlated | cancelled
    status = db.Column(db.String(20), default="open", nullable=False)

    comments = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    logs = db.relationship(
        "AadeLog",
        backref="dcl_entry",
        lazy=True,
        cascade="all, delete-orphan",
    )

    @property
    def pending_action(self):
        """
        Ποιος «Χρόνος» έχει αποθηκευτεί τοπικά αλλά ΔΕΝ έχει επιβεβαιωθεί
        ακόμη από την ΑΑΔΕ (π.χ. λόγω διακοπής internet κατά την αποστολή).
        None -> τίποτα εκκρεμές, όλα όσα έχουν γίνει είναι επιβεβαιωμένα.
        Χρησιμοποιείται από το frontend για να δείξει κουμπί «Επαναποστολή».

        Ενοικιάσεις (client_service_type=1) ΔΕΝ έχουν 2ο Χρόνο (κατηγορία
        υπηρεσίας) — πάνε κατευθείαν "open" -> "completed" μέσω exit.
        """
        if self.status == "cancelled":
            return None
        if self.id_dcl is None:
            return "entry"
        is_rental = self.client_service_type == 1
        if not is_rental and self.status == "open" and self.provided_service_category is not None:
            return "service"
        if is_rental and self.status == "open" and (
            self.invoice_kind is not None
            or self.reason_non_issue_type is not None
            or self.amount is not None
        ) and not self.entry_completion:
            return "exit"
        if (
            not is_rental
            and self.status == "in_progress"
            and (self.invoice_kind is not None or self.reason_non_issue_type is not None)
            and not self.entry_completion
        ):
            return "exit"
        if self.status == "completed" and self.mark is not None and self.correlate_id is None:
            return "correlate"
        return None

    def to_dict(self, include_logs=False):
        data = {
            "id": self.id,
            "idDcl": self.id_dcl,
            "plate": self.plate,
            "branch": self.branch,
            "clientServiceType": self.client_service_type,
            "serviceType": self.service_type,
            "providedServiceCategory": self.provided_service_category,
            "providedServiceCategoryOther": self.provided_service_category_other,
            "vehicleMovementPurpose": self.vehicle_movement_purpose,
            "isDiffVehPickupLocation": self.is_diff_pickup_location,
            "vehiclePickupLocation": self.vehicle_pickup_location,
            "isDiffVehReturnLocation": self.is_diff_return_location,
            "vehicleReturnLocation": self.vehicle_return_location,
            "amount": self.amount,
            "entryCompletion": self.entry_completion,
            "invoiceKind": self.invoice_kind,
            "reasonNonIssueType": self.reason_non_issue_type,
            "creationDateTime": self.creation_date_time.isoformat()
            if self.creation_date_time
            else None,
            "completionDateTime": self.completion_date_time.isoformat()
            if self.completion_date_time
            else None,
            "mark": self.mark,
            "correlateId": self.correlate_id,
            "status": self.status,
            "pendingAction": self.pending_action,
            "comments": self.comments,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_logs:
            data["logs"] = [log.to_dict() for log in self.logs]
        return data


class Settings(db.Model):
    """
    Ρυθμίσεις ΑΑΔΕ — ΜΙΑ εγγραφή ΑΝΑ workshop (tenant).

    Κρατά τα credentials του myDATA REST API που μπαίνουν στα headers κάθε
    κλήσης προς την ΑΑΔΕ:
        aade-user-id            <- aade_username
        ocp-apim-subscription-key <- aade_subscription_key
    """

    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    workshop_id = db.Column(
        db.Integer,
        db.ForeignKey("workshops.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    aade_username = db.Column(db.String(255), nullable=True)  # «Όνομα Χρήστη»
    # Κρυπτογραφημένο στη βάση (Fernet, δες crypto.py) — ΠΟΤΕ δεν αποθηκεύεται
    # plaintext. Πρόσβαση μέσω του property `aade_subscription_key` παρακάτω,
    # που κρυπτογραφεί/αποκρυπτογραφεί διαφανώς· ο υπόλοιπος κώδικας
    # (app.py) το διαβάζει/γράφει σαν κανονικό string attribute.
    _aade_subscription_key_enc = db.Column(
        "aade_subscription_key", db.String(512), nullable=True
    )
    branch = db.Column(db.Integer, default=0, nullable=False)  # αρ. εγκατάστασης
    # ΑΦΜ υπόχρεης οντότητας — μόνο όταν διαβιβάζει λογιστής για λογαριασμό πελάτη
    entity_vat_number = db.Column(db.String(20), nullable=True)
    # Μοναδικό αναγνωριστικό ΑΥΤΗΣ της εγκατάστασης (ένα ανά συνεργείο-πελάτη).
    # Δημιουργείται αυτόματα στην πρώτη εκκίνηση (δες app._get_installation_id).
    # Χρησιμοποιείται ΜΟΝΟ για να ξεχωρίζει ο πωλητής του λογισμικού ποια
    # εγκατάσταση έστειλε ποια μετρική OCR στον κεντρικό telemetry server —
    # ΔΕΝ ταυτοποιεί προσωπικά δεδομένα πελάτη του συνεργείου.
    installation_id = db.Column(db.String(32), nullable=True)
    # Per-workshop override: True -> χρησιμοποίησε ΠΡΑΓΜΑΤΙΚΗ ΑΑΔΕ για ΑΥΤΟ
    # το workshop ακόμη κι όταν το global USE_MOCK_AADE=true (δες
    # app._build_aade). Επιτρέπει ένα πρώτο πραγματικό τεστ χωρίς να αλλάξει
    # συμπεριφορά για όλους τους υπόλοιπους tenants. Αλλάζει μέσω
    # /api/admin (require_admin) ή αυτοεξυπηρέτησης από τον ίδιο τον χρήστη
    # στο PUT /api/settings/aade-mode (δες app.py, require_auth).
    force_real_aade = db.Column(db.Boolean, nullable=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    @property
    def aade_subscription_key(self):
        return crypto.decrypt(self._aade_subscription_key_enc)

    @aade_subscription_key.setter
    def aade_subscription_key(self, value):
        self._aade_subscription_key_enc = crypto.encrypt(value)

    @property
    def has_key(self):
        return bool(self.aade_subscription_key)

    def to_dict(self):
        """Ασφαλής μορφή — ΠΟΤΕ ολόκληρο το key, μόνο masked."""
        return {
            "aade_username": self.aade_username,
            "branch": self.branch,
            "entity_vat_number": self.entity_vat_number,
            "has_key": self.has_key,
            "masked_key": mask_key(self.aade_subscription_key),
            "installation_id": self.installation_id,
            "force_real_aade": bool(self.force_real_aade),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def mask_key(key):
    """
    Μασκάρει το subscription key ώστε να μη διαρρέει.
    Επιστρέφει π.χ. "••••••1234" (τελευταία 4). Κενό -> None.
    """
    if not key:
        return None
    if len(key) <= 4:
        return "•" * len(key)
    return "•" * 6 + key[-4:]


class OcrMetric(db.Model):
    """
    Καταγραφή ΚΑΘΕ σάρωσης πινακίδας (client-side OCR), για να μετράμε πόσο
    καλά δουλεύει η αναγνώριση στην πράξη: ποσοστό επιτυχίας, πόσο συχνά
    χρειάζεται χειροκίνητη διόρθωση, ανά μηχανή/τύπο οχήματος.

    Ροή:
      1) Μόλις τελειώσει το recognizePlate() στο frontend -> POST εδώ
         (mode, engine, ocr_plate, confidence, ...). ΜΙΑ γραμμή ΑΝΑ σάρωση,
         άρα πολλαπλές αποτυχημένες προσπάθειες πριν την τελική εμφανίζονται
         ξεχωριστά (= "πόσες φορές χρειάστηκε μέχρι να πετύχει").
      2) Όταν ο χρήστης πατήσει «Δημιουργία εγγραφής» -> PATCH στην
         ΤΕΛΕΥΤΑΙΑ σάρωση με το τελικό (πιθανώς διορθωμένο) κείμενο, ώστε να
         υπολογιστεί το user_edited.
    """

    __tablename__ = "ocr_metrics"

    id = db.Column(db.Integer, primary_key=True)
    workshop_id = db.Column(
        db.Integer, db.ForeignKey("workshops.id"), nullable=False, index=True
    )
    created_at = db.Column(db.DateTime, default=utcnow)

    mode = db.Column(db.String(10), nullable=False)  # car | moto
    engine = db.Column(db.String(30), nullable=False)  # tesseract | plate_recognizer

    ocr_plate = db.Column(db.String(20), nullable=True)  # None = απέτυχε η αναγνώριση
    confidence = db.Column(db.Integer, nullable=True)
    warnings_count = db.Column(db.Integer, default=0, nullable=False)
    # True όταν ο parser χρειάστηκε να «μαντέψει» τη μορφή (δες utils.js)
    parser_corrected = db.Column(db.Boolean, default=False, nullable=False)

    # Συμπληρώνονται στο PATCH (confirm) — None μέχρι τότε
    final_plate = db.Column(db.String(20), nullable=True)
    user_edited = db.Column(db.Boolean, nullable=True)
    confirmed = db.Column(db.Boolean, default=False, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "mode": self.mode,
            "engine": self.engine,
            "ocrPlate": self.ocr_plate,
            "confidence": self.confidence,
            "warningsCount": self.warnings_count,
            "parserCorrected": self.parser_corrected,
            "finalPlate": self.final_plate,
            "userEdited": self.user_edited,
            "confirmed": self.confirmed,
        }


class AadeLog(db.Model):
    """
    Audit log: ΚΑΘΕ κλήση προς την ΑΑΔΕ καταγράφεται εδώ
    (request/response + επιτυχία).
    """

    __tablename__ = "aade_logs"

    id = db.Column(db.Integer, primary_key=True)
    # nullable: επιτρέπει system-level logs χωρίς εγγραφή (π.χ. test-connection)
    dcl_entry_id = db.Column(
        db.Integer, db.ForeignKey("dcl_entries.id"), nullable=True
    )
    # SendClient / UpdateClient / ClientCorrelations / CancelClient
    method = db.Column(db.String(30), nullable=False)
    request_json = db.Column(db.Text, nullable=True)
    response_json = db.Column(db.Text, nullable=True)
    success = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "dclEntryId": self.dcl_entry_id,
            "method": self.method,
            "requestJson": self.request_json,
            "responseJson": self.response_json,
            "success": self.success,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class PasswordResetToken(db.Model):
    """
    Token επαναφοράς κωδικού (forgot-password). Κρατάμε ΜΟΝΟ το sha256 hash
    του token — ποτέ το ίδιο το token — ώστε μια διαρροή της βάσης να μη
    δίνει έτοιμα, ενεργά reset links. Το token είναι ήδη υψηλής εντροπίας
    (secrets.token_urlsafe), οπότε sha256 lookup είναι ασφαλές (χωρίς το
    κόστος bcrypt που χρειάζεται μόνο για δεδομένα χαμηλής εντροπίας όπως
    κωδικοί χρήστη).
    """

    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    workshop_id = db.Column(
        db.Integer, db.ForeignKey("workshops.id"), nullable=False, index=True
    )
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
