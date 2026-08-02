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
import re
from functools import wraps

from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)

from models import Workshop, db

jwt = JWTManager()

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
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    business_type = (data.get("businessType") or "").strip().lower()

    if not name:
        return jsonify({"error": "Το όνομα επιχείρησης είναι υποχρεωτικό."}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"error": "Μη έγκυρο email."}), 400
    if len(password) < 8:
        return jsonify({"error": "Ο κωδικός πρέπει να έχει τουλάχιστον 8 χαρακτήρες."}), 400
    if business_type not in BUSINESS_TYPES:
        return jsonify({"error": "Επίλεξε τύπο επιχείρησης (Συνεργείο ή Ενοικίαση Οχημάτων)."}), 400

    if Workshop.query.filter_by(email=email).first() is not None:
        return jsonify({"error": "Υπάρχει ήδη λογαριασμός με αυτό το email."}), 409

    workshop = Workshop(name=name, email=email, business_type=business_type)
    workshop.set_password(password)
    db.session.add(workshop)
    db.session.commit()

    return jsonify(_issue_tokens(workshop)), 201


@auth_bp.route("/login", methods=["POST"])
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
