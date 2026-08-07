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
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from email_service import send_email
from models import PasswordResetToken, Settings, Workshop, db, utcnow

jwt = JWTManager()

# Brute-force protection στο login/register/forgot-password. In-memory
# storage — αρκεί για ένα μόνο Render instance (δεν χρειάζεται Redis για
# λίγους πρώτους πελάτες)· αν στο μέλλον τρέξουν πολλά instances, θα
# χρειαστεί shared storage (π.χ. Redis) ώστε τα όρια να μετράνε σωστά.
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def workshop_key():
    """Rate-limit key ανά workshop (όχι ανά IP) — π.χ. για /api/ocr/plate,
    όπου ένα ολόκληρο συνεργείο πίσω από NAT μοιράζεται μία δημόσια IP.
    Χρησιμοποιείται ΜΟΝΟ πίσω από @require_auth, που θέτει g.workshop_id
    πριν τρέξει το limiter.limit (η σειρά των decorators το εξασφαλίζει)."""
    workshop_id = getattr(g, "workshop_id", None)
    return f"workshop:{workshop_id}" if workshop_id is not None else get_remote_address()

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# garage (Συνεργείο) | rental (Ενοικίαση Οχημάτων) — επιλέγεται στην εγγραφή,
# καθορίζει μόνιμα ποιο clientServiceType/ροή ΑΑΔΕ χρησιμοποιεί το workshop.
BUSINESS_TYPES = {"garage", "rental"}

# Καταστάσεις που επιτρέπουν χρήση της εφαρμογής. "past_due"/"cancelled"
# μπλοκάρουν — ο πωλητής τα αλλάζει χειροκίνητα μέσω /api/admin μετά από
# τραπεζική μεταφορά (δεν υπάρχει Stripe/αυτόματη χρέωση).
ACTIVE_STATUSES = {"trial", "active"}


def require_auth(fn):
    """Decorator: απαιτεί έγκυρο access token ΚΑΙ ενεργή συνδρομή, θέτει g.workshop_id."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        workshop_id = int(get_jwt_identity())
        workshop = Workshop.query.get(workshop_id)
        if workshop is None:
            return jsonify({"error": "Δεν βρέθηκε ο λογαριασμός."}), 401
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
        g.workshop_id = workshop_id
        return fn(*args, **kwargs)

    return wrapper


def require_admin(fn):
    """Decorator: απαιτεί σωστό X-Admin-Key header. ΚΕΝΟ ADMIN_KEY = πάντα κλειστό."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        from flask import current_app

        expected = current_app.config.get("ADMIN_KEY")
        provided = request.headers.get("X-Admin-Key", "")
        if not expected or provided != expected:
            return jsonify({"error": "Μη έγκυρο ή λείπον admin key."}), 401
        return fn(*args, **kwargs)

    return wrapper


def _issue_tokens(workshop):
    identity = str(workshop.id)
    return {
        "accessToken": create_access_token(identity=identity),
        "refreshToken": create_refresh_token(identity=identity),
        "workshop": workshop.to_dict(),
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

    workshop = Workshop.query.filter_by(email=email).first()
    if workshop is None or not workshop.check_password(password):
        return jsonify({"error": "Λάθος email ή κωδικός."}), 401

    return jsonify(_issue_tokens(workshop))


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
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
    workshop = Workshop.query.get(g.workshop_id)
    if workshop is None:
        return jsonify({"error": "Δεν βρέθηκε ο λογαριασμός."}), 404

    data = request.get_json(silent=True) or {}
    current_password = data.get("currentPassword") or ""
    new_password = data.get("newPassword") or ""

    if not workshop.check_password(current_password):
        # ΟΧΙ 401: θα πυροδοτούσε το global "session expired" logout στο
        # frontend για ένα απλό λάθος στο πληκτρολόγιο (δες app.py delete_account).
        return jsonify({"error": "Ο τρέχων κωδικός δεν είναι σωστός."}), 400
    if len(new_password) < 8:
        return jsonify({"error": "Ο νέος κωδικός πρέπει να έχει τουλάχιστον 8 χαρακτήρες."}), 400

    workshop.set_password(new_password)
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

    @jwt.unauthorized_loader
    def _unauthorized(reason):
        return jsonify({"error": "Απαιτείται σύνδεση.", "reason": reason}), 401

    @jwt.invalid_token_loader
    def _invalid(reason):
        return jsonify({"error": "Μη έγκυρο token.", "reason": reason}), 401

    @jwt.expired_token_loader
    def _expired(header, payload):
        return jsonify({"error": "Η σύνδεση έληξε, ξανασυνδέσου.", "expired": True}), 401
