"""
auth.py
--------------------------------------------------------------------
Multi-tenant auth: κάθε Workshop (συνεργείο-πελάτης) έχει δικό του
λογαριασμό (email/password) και βλέπει ΜΟΝΟ τα δικά του δεδομένα.

- POST /api/auth/register  -> δημιουργεί Workshop, επιστρέφει tokens
- POST /api/auth/login     -> ελέγχει credentials, επιστρέφει tokens
- POST /api/auth/refresh   -> νέο access token από refresh token
- GET  /api/auth/me        -> στοιχεία του logged-in workshop

Το JWT identity είναι το workshop.id (string). Κάθε προστατευμένο route
καλεί `require_auth` (decorator) που θέτει `g.workshop_id` — ΟΛΑ τα queries
στο app.py φιλτράρουν με αυτό ώστε να μην διαρρέουν δεδομένα ανάμεσα σε
tenants.
--------------------------------------------------------------------
"""
import hashlib
import re
import secrets
from datetime import timedelta
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    create_refresh_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import Config
from email_service import send_email
from models import AadeLog, DclEntry, Employee, PasswordResetToken, Settings, Workshop, db, utcnow

jwt = JWTManager()

# Brute-force protection στο login/register/forgot-password. Χωρίς
# REDIS_URL, in-memory storage — ΑΝΑ gunicorn worker/process (render.yaml:
# --workers 2), οπότε ένα "10 per minute" γίνεται στην πράξη ~20, ΚΑΙ
# μηδενίζεται σε κάθε deploy. Με REDIS_URL (δες config.py), shared storage
# ανάμεσα σε workers/deploys — τα όρια μετράνε πραγματικά αυτό που λένε.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri=Config.REDIS_URL or "memory://",
)


def workshop_key():
    """Rate-limit key ανά workshop (όχι ανά IP) — π.χ. για /api/ocr/plate,
    όπου ένα ολόκληρο συνεργείο πίσω από NAT μοιράζεται μία δημόσια IP.
    Χρησιμοποιείται ΜΟΝΟ πίσω από @require_auth, που θέτει g.workshop_id
    πριν τρέξει το limiter.limit (η σειρά των decorators το εξασφαλίζει)."""
    workshop_id = getattr(g, "workshop_id", None)
    return f"workshop:{workshop_id}" if workshop_id is not None else get_remote_address()

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")
employees_bp = Blueprint("employees", __name__, url_prefix="/api/employees")

# Πρόθεμα identity για tokens υπαλλήλου — "emp:<employee.id>". Tokens
# owner παραμένουν ΑΠΛΑ ψηφία (str(workshop.id), ΧΩΡΙΣ πρόθεμα) ώστε ΚΑΘΕ
# ήδη εκδομένο token πριν από αυτή την αλλαγή να συνεχίσει να δουλεύει
# ακριβώς όπως πριν — μηδενικό αναγκαστικό logout σε υπάρχοντες owners.
EMPLOYEE_IDENTITY_PREFIX = "emp:"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# garage (Συνεργείο) | rental (Ενοικίαση Οχημάτων) — επιλέγεται στην εγγραφή,
# καθορίζει μόνιμα ποιο clientServiceType/ροή ΑΑΔΕ χρησιμοποιεί το workshop.
BUSINESS_TYPES = {"garage", "rental"}

# Καταστάσεις που επιτρέπουν χρήση της εφαρμογής. "past_due"/"cancelled"
# μπλοκάρουν — ο πωλητής τα αλλάζει χειροκίνητα μέσω /api/admin μετά από
# τραπεζική μεταφορά (δεν υπάρχει Stripe/αυτόματη χρέωση).
ACTIVE_STATUSES = {"trial", "active"}


def _epoch_mismatch_response():
    return (
        jsonify(
            {
                "error": "Η σύνδεση δεν ισχύει πια (άλλαξε ο κωδικός σε άλλη συσκευή/session) — ξανασυνδέσου.",
                "reason": "token_epoch_mismatch",
            }
        ),
        401,
    )


def _lookup_actor(identity):
    """
    Επιστρέφει (workshop, employee) για ένα JWT identity string.

    "emp:<id>" -> (workshop του υπαλλήλου, το Employee) — ή (None, None)
    αν ο υπάλληλος διαγράφηκε. Οτιδήποτε άλλο (τα ψηφία str(workshop.id)
    από ΠΑΝΤΑ) -> (workshop, None) — owner, ΙΔΙΑ συμπεριφορά με πριν.
    """
    if identity.startswith(EMPLOYEE_IDENTITY_PREFIX):
        employee = Employee.query.get(int(identity[len(EMPLOYEE_IDENTITY_PREFIX):]))
        if employee is None:
            return None, None
        return Workshop.query.get(employee.workshop_id), employee
    return Workshop.query.get(int(identity)), None


def require_auth(fn):
    """Decorator: απαιτεί έγκυρο access token ΚΑΙ ενεργή συνδρομή, θέτει
    g.workshop_id/g.actor_type/g.actor_id/g.actor_name."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        workshop, employee = _lookup_actor(get_jwt_identity())
        if workshop is None:
            return jsonify({"error": "Δεν βρέθηκε ο λογαριασμός."}), 401
        # Ανάκληση tokens: αν το "ep" claim του access token δεν ταιριάζει
        # με το τρέχον token_epoch, ο κωδικός άλλαξε ΜΕΤΑ την έκδοση αυτού
        # του token — ΔΕΝ το εμπιστευόμαστε, ακόμη κι αν δεν έχει λήξει.
        # Employee ΚΑΙ owner έχουν ΞΕΧΩΡΙΣΤΟ token_epoch (δες models.Employee)
        # — η αλλαγή κωδικού του ενός δεν αγγίζει τα tokens του άλλου.
        current_epoch = employee.token_epoch if employee else workshop.token_epoch
        if get_jwt().get("ep") != current_epoch:
            return _epoch_mismatch_response()
        if employee is not None and not employee.is_active:
            # Ο owner απενεργοποίησε τον υπάλληλο — αποκλεισμός ΑΜΕΣΩΣ, όχι
            # μόνο στο επόμενο login (ελέγχεται σε ΚΑΘΕ request, όχι μέσω
            # epoch — δεν χρειάζεται να «σκάσει» το ήδη-εκδομένο token).
            return jsonify({"error": "Ο λογαριασμός υπαλλήλου έχει απενεργοποιηθεί."}), 401
        if workshop.subscription_status not in ACTIVE_STATUSES:
            return (
                jsonify(
                    {
                        "error": "Η συνδρομή δεν είναι ενεργή. Επικοινώνησε με τον "
                        "πάροχο για να ενεργοποιηθεί μετά την πληρωμή.",
                        "subscriptionStatus": workshop.subscription_status,
                    }
                ),
                402,
            )
        if workshop.subscription_status == "trial":
            # Fallback σε created_at + TRIAL_DAYS για workshops που υπήρχαν
            # πριν προστεθεί η στήλη trial_ends_at (nullable, δες models.py).
            ends_at = workshop.trial_ends_at or (
                workshop.created_at
                + timedelta(days=current_app.config["TRIAL_DAYS"])
            )
            if utcnow().replace(tzinfo=None) > ends_at:
                return (
                    jsonify(
                        {
                            "error": "Η δοκιμαστική περίοδος έληξε. Επικοινώνησε με "
                            "τον πάροχο για ενεργοποίηση συνδρομής.",
                            "subscriptionStatus": "trial",
                            "trialExpired": True,
                        }
                    ),
                    402,
                )
        g.workshop_id = workshop.id
        g.actor_type = "employee" if employee is not None else "owner"
        g.actor_id = employee.id if employee is not None else None
        g.actor_name = employee.name if employee is not None else workshop.name
        return fn(*args, **kwargs)

    return wrapper


def require_owner(fn):
    """
    Decorator: επιπλέον του require_auth, απαιτεί ο caller να είναι ο
    owner (Workshop), όχι Employee — για ενέργειες που δεν πρέπει να
    μπορεί να κάνει υπάλληλος (διαχείριση άλλων υπαλλήλων, διαγραφή
    λογαριασμού). ΠΑΝΤΑ ΜΕΤΑ το @require_auth στη σειρά decorators
    (χρειάζεται το g.actor_type που εκείνο θέτει).
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if getattr(g, "actor_type", "owner") != "owner":
            return (
                jsonify(
                    {"error": "Μόνο ο ιδιοκτήτης του λογαριασμού μπορεί να κάνει αυτή την ενέργεια."}
                ),
                403,
            )
        return fn(*args, **kwargs)

    return wrapper


def require_admin(fn):
    """Decorator: απαιτεί σωστό X-Admin-Key header. ΚΕΝΟ ADMIN_KEY = πάντα κλειστό."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        from flask import current_app

        expected = current_app.config.get("ADMIN_KEY")
        provided = request.headers.get("X-Admin-Key", "")
        # compare_digest: σύγκριση σταθερού χρόνου. Το `!=` σε strings
        # τερματίζει στον πρώτο διαφορετικό χαρακτήρα, δίνοντας timing
        # oracle που επιτρέπει ανακατασκευή του κλειδιού χαρακτήρα-χαρακτήρα.
        if not expected or not secrets.compare_digest(provided, expected):
            return jsonify({"error": "Μη έγκυρο ή λείπον admin key."}), 401
        return fn(*args, **kwargs)

    return wrapper


def _issue_tokens(workshop, employee=None):
    """
    Κοινό σημείο έκδοσης tokens για owner (employee=None) ΚΑΙ employee login.
    Το "workshop" key στην απάντηση είναι ΠΑΝΤΑ τα στοιχεία της επιχείρησης
    (ίδιο μοτίβο με πριν) — το "actor" δείχνει ΠΟΙΟΣ ΣΥΓΚΕΚΡΙΜΕΝΑ συνδέθηκε
    (owner ή συγκεκριμένος υπάλληλος), ώστε το frontend να δείχνει το σωστό
    όνομα στο topbar και να κρύβει τη διαχείριση υπαλλήλων από μη-owners.
    """
    if employee is not None:
        identity = f"{EMPLOYEE_IDENTITY_PREFIX}{employee.id}"
        actor = {
            "type": "employee",
            "id": employee.id,
            "name": employee.name,
            "email": employee.email,
        }
    else:
        identity = str(workshop.id)
        actor = {
            "type": "owner",
            "id": workshop.id,
            "name": workshop.name,
            "email": workshop.email,
        }
    return {
        "accessToken": create_access_token(identity=identity),
        "refreshToken": create_refresh_token(identity=identity),
        "workshop": workshop.to_dict(),
        "actor": actor,
    }


@auth_bp.route("/register", methods=["POST"])
@limiter.limit("10 per minute")
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    business_type = (data.get("businessType") or "").strip().lower()
    terms_accepted = bool(data.get("termsAccepted"))

    if not name:
        return jsonify({"error": "Το όνομα επιχείρησης είναι υποχρεωτικό."}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"error": "Μη έγκυρο email."}), 400
    if len(password) < 8:
        return jsonify({"error": "Ο κωδικός πρέπει να έχει τουλάχιστον 8 χαρακτήρες."}), 400
    if business_type not in BUSINESS_TYPES:
        return jsonify({"error": "Επίλεξε τύπο επιχείρησης (Συνεργείο ή Ενοικίαση Οχημάτων)."}), 400
    if not terms_accepted:
        return (
            jsonify(
                {"error": "Πρέπει να αποδεχθείς τους Όρους Χρήσης και την Πολιτική Απορρήτου."}
            ),
            400,
        )

    if Workshop.query.filter_by(email=email).first() is not None:
        return jsonify({"error": "Υπάρχει ήδη λογαριασμός με αυτό το email."}), 409

    workshop = Workshop(
        name=name,
        email=email,
        business_type=business_type,
        terms_accepted_at=utcnow(),
        trial_ends_at=utcnow() + timedelta(days=current_app.config["TRIAL_DAYS"]),
    )
    workshop.set_password(password)
    db.session.add(workshop)
    db.session.commit()

    return jsonify(_issue_tokens(workshop)), 201


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    # Έλεγχος ΠΡΩΤΑ Workshop (owner), ΜΕΤΑ Employee — το email είναι
    # μοναδικό ΚΑΙ στους δύο πίνακες μαζί (δες Employee.email), άρα ποτέ
    # δεν ταιριάζει και στα δύο.
    workshop = Workshop.query.filter_by(email=email).first()
    if workshop is not None and workshop.check_password(password):
        return jsonify(_issue_tokens(workshop))

    employee = Employee.query.filter_by(email=email).first()
    if (
        employee is not None
        and employee.is_active
        and employee.check_password(password)
    ):
        employee_workshop = Workshop.query.get(employee.workshop_id)
        return jsonify(_issue_tokens(employee_workshop, employee=employee))

    return jsonify({"error": "Λάθος email ή κωδικός."}), 401


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    workshop, employee = _lookup_actor(identity)
    # ΙΔΙΟΣ έλεγχος epoch με το require_auth — χωρίς αυτό, ένα ΚΛΕΜΜΕΝΟ
    # refresh token θα μπορούσε να κόψει ΝΕΟ access token με το ΤΡΕΧΟΝ
    # epoch (το additional_claims_loader διαβάζει πάντα το current value),
    # ακυρώνοντας εντελώς τον σκοπό της ανάκλησης — το κλεμμένο refresh
    # token ζει 30 μέρες.
    current_epoch = employee.token_epoch if employee else (workshop.token_epoch if workshop else None)
    if workshop is None or get_jwt().get("ep") != current_epoch:
        return _epoch_mismatch_response()
    if employee is not None and not employee.is_active:
        return jsonify({"error": "Ο λογαριασμός υπαλλήλου έχει απενεργοποιηθεί."}), 401
    return jsonify({"accessToken": create_access_token(identity=identity)})


@auth_bp.route("/me", methods=["GET"])
@require_auth
def me():
    workshop = Workshop.query.get(g.workshop_id)
    if workshop is None:
        return jsonify({"error": "Δεν βρέθηκε ο λογαριασμός."}), 404
    return jsonify(workshop.to_dict())


@auth_bp.route("/password", methods=["PUT"])
@require_auth
def change_password():
    # Owner ΚΑΙ employee αλλάζουν ΤΟΝ ΔΙΚΟ ΤΟΥΣ κωδικό από εδώ — g.actor_type
    # δείχνει ποιος πίνακας/row (δες require_auth). Ξεχωριστό token_epoch
    # ανά actor (δες models.Employee) -> η αλλαγή αγγίζει ΜΟΝΟ τα δικά του
    # tokens, όχι του owner ή των υπόλοιπων υπαλλήλων.
    if g.actor_type == "employee":
        account = Employee.query.get(g.actor_id)
    else:
        account = Workshop.query.get(g.workshop_id)
    if account is None:
        return jsonify({"error": "Δεν βρέθηκε ο λογαριασμός."}), 404

    data = request.get_json(silent=True) or {}
    current_password = data.get("currentPassword") or ""
    new_password = data.get("newPassword") or ""

    if not account.check_password(current_password):
        # ΟΧΙ 401: θα πυροδοτούσε το global "session expired" logout στο
        # frontend για ένα απλό λάθος στο πληκτρολόγιο (δες app.py delete_account).
        return jsonify({"error": "Ο τρέχων κωδικός δεν είναι σωστός."}), 400
    if len(new_password) < 8:
        return jsonify({"error": "Ο νέος κωδικός πρέπει να έχει τουλάχιστον 8 χαρακτήρες."}), 400

    account.set_password(new_password)
    db.session.commit()
    return jsonify({"message": "Ο κωδικός άλλαξε."})


@auth_bp.route("/business-type", methods=["PUT"])
@require_auth
def change_business_type():
    workshop = Workshop.query.get(g.workshop_id)
    if workshop is None:
        return jsonify({"error": "Δεν βρέθηκε ο λογαριασμός."}), 404

    data = request.get_json(silent=True) or {}
    business_type = (data.get("businessType") or "").strip().lower()
    if business_type not in BUSINESS_TYPES:
        return jsonify({"error": "Επίλεξε τύπο επιχείρησης (Συνεργείο ή Ενοικίαση Οχημάτων)."}), 400

    # Δεν αλλάζει τίποτα σε ήδη υπάρχουσες εγγραφές (κάθε DclEntry κρατά το
    # δικό της client_service_type, δεσμευμένο τη στιγμή δημιουργίας του) —
    # επηρεάζει μόνο τη ροή/πεδία που θα χρησιμοποιηθούν σε ΝΕΕΣ εγγραφές.
    workshop.business_type = business_type
    db.session.commit()
    return jsonify(workshop.to_dict())


STATUS_VALUES = {"trial", "active", "past_due", "cancelled"}


@admin_bp.route("/workshops", methods=["GET"])
@require_admin
def list_workshops():
    workshops = Workshop.query.order_by(Workshop.created_at.desc()).all()
    return jsonify([w.to_dict() for w in workshops])


@admin_bp.route("/workshops/<int:workshop_id>/status", methods=["PUT"])
@require_admin
def update_workshop_status(workshop_id):
    workshop = Workshop.query.get(workshop_id)
    if workshop is None:
        return jsonify({"error": "Δεν βρέθηκε το workshop."}), 404

    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip().lower()
    if status not in STATUS_VALUES:
        return (
            jsonify(
                {
                    "error": f"Μη έγκυρη κατάσταση. Επιτρεπτές: {', '.join(sorted(STATUS_VALUES))}."
                }
            ),
            400,
        )

    workshop.subscription_status = status
    db.session.commit()
    return jsonify(workshop.to_dict())


@admin_bp.route("/workshops/<int:workshop_id>/trial", methods=["PUT"])
@require_admin
def extend_trial(workshop_id):
    workshop = Workshop.query.get(workshop_id)
    if workshop is None:
        return jsonify({"error": "Δεν βρέθηκε το workshop."}), 404

    data = request.get_json(silent=True) or {}
    try:
        days = int(data.get("days"))
    except (TypeError, ValueError):
        return jsonify({"error": "Το πεδίο 'days' πρέπει να είναι ακέραιος."}), 400

    workshop.trial_ends_at = utcnow() + timedelta(days=days)
    db.session.commit()
    return jsonify(workshop.to_dict())


@admin_bp.route("/workshops/<int:workshop_id>/aade-mode", methods=["PUT"])
@require_admin
def set_aade_mode(workshop_id):
    """
    Per-workshop override: force_real_aade=true κάνει ΑΥΤΟ το workshop να
    χρησιμοποιεί πραγματική ΑΑΔΕ ακόμη κι όταν το global USE_MOCK_AADE=true —
    ώστε να γίνει ένα πρώτο ασφαλές τεστ χωρίς να επηρεαστούν άλλοι tenants
    (δες app._build_aade).
    """
    workshop = Workshop.query.get(workshop_id)
    if workshop is None:
        return jsonify({"error": "Δεν βρέθηκε το workshop."}), 404

    data = request.get_json(silent=True) or {}
    force_real = bool(data.get("forceReal"))

    settings = Settings.query.filter_by(workshop_id=workshop_id).first()
    if settings is None:
        settings = Settings(workshop_id=workshop_id, branch=0)
        db.session.add(settings)
    settings.force_real_aade = force_real
    db.session.commit()
    return jsonify({"workshopId": workshop_id, "forceRealAade": force_real})


# --------------------------------------------------------------------
# Διαχείριση υπαλλήλων — ΜΟΝΟ owner (δες require_owner). Οι υπάλληλοι
# βλέπουν ΤΑ ΙΔΙΑ δεδομένα με τον owner (ίδιο g.workshop_id), δεν έχουν
# δικά τους δικαιώματα/scoping — ο σκοπός εδώ είναι ΠΟΙΟΣ έκανε ΤΙ (δες
# models.Employee, app._log_aade), όχι διαφορετικά επίπεδα πρόσβασης.
# --------------------------------------------------------------------
@employees_bp.route("", methods=["GET"])
@require_auth
def list_employees():
    employees = (
        Employee.query.filter_by(workshop_id=g.workshop_id)
        .order_by(Employee.created_at.asc())
        .all()
    )
    return jsonify([e.to_dict() for e in employees])


@employees_bp.route("", methods=["POST"])
@require_auth
@require_owner
def create_employee():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name:
        return jsonify({"error": "Το όνομα είναι υποχρεωτικό."}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"error": "Μη έγκυρο email."}), 400
    if len(password) < 8:
        return jsonify({"error": "Ο κωδικός πρέπει να έχει τουλάχιστον 8 χαρακτήρες."}), 400

    # Το email είναι το ΜΟΝΑΔΙΚΟ κλειδί που ξέρει το login ΠΟΙΟΝ πίνακα να
    # ψάξει (Workshop ή Employee, δες login()) — πρέπει να είναι μοναδικό
    # ΚΑΙ ΣΤΟΥΣ ΔΥΟ, όχι μόνο μέσα στο ίδιο workshop.
    if Workshop.query.filter_by(email=email).first() is not None:
        return jsonify({"error": "Υπάρχει ήδη λογαριασμός με αυτό το email."}), 409
    if Employee.query.filter_by(email=email).first() is not None:
        return jsonify({"error": "Υπάρχει ήδη λογαριασμός με αυτό το email."}), 409

    employee = Employee(workshop_id=g.workshop_id, name=name, email=email)
    employee.set_password(password)
    db.session.add(employee)
    db.session.commit()
    return jsonify(employee.to_dict()), 201


@employees_bp.route("/<int:employee_id>", methods=["PATCH"])
@require_auth
@require_owner
def update_employee(employee_id):
    employee = Employee.query.filter_by(
        id=employee_id, workshop_id=g.workshop_id
    ).first()
    if employee is None:
        return jsonify({"error": "Δεν βρέθηκε ο υπάλληλος."}), 404

    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Το όνομα είναι υποχρεωτικό."}), 400
        employee.name = name
    if "isActive" in data:
        # Απενεργοποίηση: αποκλείει ΑΜΕΣΩΣ (δες require_auth) — δεν
        # χρειάζεται αύξηση του token_epoch, ελέγχεται σε ΚΑΘΕ request.
        employee.is_active = bool(data.get("isActive"))
    if "password" in data and data.get("password"):
        new_password = data["password"]
        if len(new_password) < 8:
            return jsonify({"error": "Ο κωδικός πρέπει να έχει τουλάχιστον 8 χαρακτήρες."}), 400
        # Ο owner κάνει reset χωρίς να ξέρει τον παλιό — ο σκοπός εδώ είναι
        # να ξεκλειδώσει έναν υπάλληλο που ξέχασε τον κωδικό του (δεν
        # υπάρχει ακόμα self-service forgot-password για υπαλλήλους).
        employee.set_password(new_password)

    db.session.commit()
    return jsonify(employee.to_dict())


@employees_bp.route("/<int:employee_id>", methods=["DELETE"])
@require_auth
@require_owner
def delete_employee(employee_id):
    employee = Employee.query.filter_by(
        id=employee_id, workshop_id=g.workshop_id
    ).first()
    if employee is None:
        return jsonify({"error": "Δεν βρέθηκε ο υπάλληλος."}), 404
    # Τα ιστορικά entries/logs του ΔΕΝ σβήνονται (θα ήταν λάθος να χαθεί το
    # audit trail επειδή έφυγε ο υπάλληλος) — μόνο η αναφορά καθαρίζεται σε
    # NULL, ρητά από την εφαρμογή (όχι μέσω DB-level ON DELETE) ώστε να
    # δουλεύει το ΙΔΙΟ σε SQLite (τεστ/dev — δεν επιβάλλει FK constraints
    # by default) και Postgres.
    DclEntry.query.filter_by(created_by_employee_id=employee.id).update(
        {"created_by_employee_id": None}
    )
    AadeLog.query.filter_by(actor_employee_id=employee.id).update(
        {"actor_employee_id": None}
    )
    db.session.delete(employee)
    db.session.commit()
    return "", 204


RESET_TOKEN_TTL_MINUTES = 30


@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit("5 per minute")
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    # Πάντα το ΙΔΙΟ γενικό μήνυμα — ανεξάρτητα αν υπάρχει ο λογαριασμός, ώστε
    # να μη μπορεί κανείς να ανακαλύψει ποια emails είναι εγγεγραμμένα.
    generic_response = jsonify(
        {"message": "Αν υπάρχει λογαριασμός με αυτό το email, στάλθηκε σύνδεσμος επαναφοράς."}
    )

    workshop = Workshop.query.filter_by(email=email).first() if email else None
    if workshop is None:
        return generic_response

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    reset_token = PasswordResetToken(
        workshop_id=workshop.id,
        token_hash=token_hash,
        expires_at=utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
    )
    db.session.add(reset_token)
    db.session.commit()

    reset_link = f"{current_app.config['FRONTEND_URL']}/reset-password?token={raw_token}"
    send_email(
        to=workshop.email,
        subject="Επαναφορά κωδικού — Ψηφιακό Πελατολόγιο",
        html=(
            f"<p>Ζητήθηκε επαναφορά κωδικού για τον λογαριασμό {workshop.email}.</p>"
            f'<p><a href="{reset_link}">Πάτησε εδώ για να ορίσεις νέο κωδικό</a> '
            f"(ισχύει για {RESET_TOKEN_TTL_MINUTES} λεπτά).</p>"
            "<p>Αν δεν το ζήτησες εσύ, αγνόησε αυτό το email.</p>"
        ),
    )
    return generic_response


@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json(silent=True) or {}
    raw_token = data.get("token") or ""
    password = data.get("password") or ""

    if len(password) < 8:
        return jsonify({"error": "Ο κωδικός πρέπει να έχει τουλάχιστον 8 χαρακτήρες."}), 400

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    reset_token = PasswordResetToken.query.filter_by(token_hash=token_hash).first()

    if (
        reset_token is None
        or reset_token.used_at is not None
        or utcnow().replace(tzinfo=None) > reset_token.expires_at
    ):
        return jsonify({"error": "Ο σύνδεσμος επαναφοράς δεν ισχύει πια — ζήτησε νέον."}), 400

    workshop = Workshop.query.get(reset_token.workshop_id)
    if workshop is None:
        return jsonify({"error": "Δεν βρέθηκε ο λογαριασμός."}), 404

    workshop.set_password(password)
    reset_token.used_at = utcnow()
    db.session.commit()
    return jsonify({"message": "Ο κωδικός άλλαξε. Συνδέσου με τον νέο κωδικό."})


def init_auth(app):
    app.config["JWT_SECRET_KEY"] = app.config["JWT_SECRET_KEY"]
    from datetime import timedelta

    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(
        minutes=app.config["JWT_ACCESS_TOKEN_EXPIRES_MIN"]
    )
    app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(
        days=app.config["JWT_REFRESH_TOKEN_EXPIRES_DAYS"]
    )
    jwt.init_app(app)
    limiter.init_app(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(employees_bp)

    @jwt.additional_claims_loader
    def _add_token_epoch_claim(identity):
        """Μπαίνει σε ΚΑΘΕ νέο token (access ΚΑΙ refresh — καλείται από τα
        create_access_token/create_refresh_token). Δες require_auth/refresh
        για το πού ελέγχεται. employee identity ("emp:<id>") -> το ΔΙΚΟ ΤΟΥ
        epoch, όχι του workshop (δες models.Employee)."""
        workshop, employee = _lookup_actor(identity)
        if employee is not None:
            return {"ep": employee.token_epoch}
        return {"ep": workshop.token_epoch if workshop else 0}

    @jwt.unauthorized_loader
    def _unauthorized(reason):
        return jsonify({"error": "Απαιτείται σύνδεση.", "reason": reason}), 401

    @jwt.invalid_token_loader
    def _invalid(reason):
        return jsonify({"error": "Μη έγκυρο token.", "reason": reason}), 401

    @jwt.expired_token_loader
    def _expired(header, payload):
        return jsonify({"error": "Η σύνδεση έληξε, ξανασυνδέσου.", "expired": True}), 401
