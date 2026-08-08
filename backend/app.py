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
from flask import Flask, current_app, jsonify
from flask_cors import CORS
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from aade_core import ApiError
from auth import init_auth
from config import Config, validate_production_config
from models import db
from routes_account import account_bp
from routes_customers import customers_bp
from routes_dcl import dcl_bp
from routes_fleet import fleet_bp
from routes_ocr import ocr_bp
from routes_settings import settings_bp


def _init_sentry():
    """
    Ενεργοποιεί το Sentry ΜΟΝΟ αν έχει οριστεί SENTRY_DSN (δες config.py) —
    χωρίς αυτό, καμία κλήση δικτύου, καμία εξάρτηση σε λειτουργία. Καλείται
    πριν το Flask app instance ώστε να πιάνει και σφάλματα στο ίδιο το
    create_app() (π.χ. στο validate_production_config).
    """
    if not Config.SENTRY_DSN:
        return
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

    sentry_sdk.init(
        dsn=Config.SENTRY_DSN,
        environment=Config.FLASK_ENV,
        integrations=[FlaskIntegration()],
    )


def create_app():
    _init_sentry()

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


def register_routes(app):
    """
    Καταχωρεί ΟΛΑ τα /api/* blueprints. Η καθαρή σχέση route -> blueprint
    αρχείο ζει εδώ ώστε να είναι εύκολο να δεις ΠΟΥ ζει κάθε endpoint χωρίς
    να ψάχνεις σε 2000+ γραμμές (δες routes_*.py — καθένα κρατά ένα σύνολο
    σχετικών endpoints, η κοινή λογική ΑΑΔΕ ζει στο aade_core.py).
    """

    @app.route("/api/health", methods=["GET"])
    def health():
        """
        LIVENESS — σκόπιμα ΡΗΧΟ: ΔΕΝ αγγίζει τη βάση.

        Το render.yaml το χρησιμοποιεί ως healthCheckPath. Αν έλεγχε τη βάση,
        ένα στιγμιαίο πρόβλημα σύνδεσης θα έκανε το Render να σκοτώσει και να
        ξαναστήσει το service — restart loop ακριβώς τη στιγμή που η βάση
        δυσκολεύεται, δηλαδή η χειρότερη δυνατή στιγμή. Απαντά «ζω», όχι
        «είμαι έτοιμο». Για το δεύτερο δες /api/health/ready.
        """
        return jsonify({"status": "ok"})

    @app.route("/api/health/ready", methods=["GET"])
    def health_ready():
        """
        READINESS — για monitoring/alerting, ΟΧΙ για healthCheckPath.

        Εδώ μπαίνει η βάση: ένα SELECT 1 πιάνει εξαντλημένο connection pool ή
        πεσμένο Postgres, που το liveness από πάνω δεν βλέπει.
        """
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify({"status": "ok", "database": "ok"})
        except Exception as err:
            # Χωρίς rollback η session μένει σε failed state και ΚΑΘΕ επόμενο
            # query στον ίδιο gunicorn worker σκάει — ένα αποτυχημένο health
            # check θα μόλυνε πραγματικά αιτήματα χρηστών.
            db.session.rollback()
            current_app.logger.error("readiness check failed: %s", err)
            # Γενικό μήνυμα προς τα έξω: το endpoint είναι δημόσιο και οι
            # λεπτομέρειες της βάσης δεν έχουν λόγο να διαρρέουν. Το πλήρες
            # σφάλμα πάει στα logs (και στο Sentry, αν έχει ρυθμιστεί).
            return jsonify({"status": "error", "database": "unreachable"}), 503

    app.register_blueprint(settings_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(fleet_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(dcl_bp)
    app.register_blueprint(ocr_bp)


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
    # Στο production, το ίδιο τρέχει ΜΙΑ φορά μέσα στο buildCommand (δες
    # render.yaml), πριν ξεκινήσουν οι workers.
    #
    # scripts.migrate.upgrade_to_head() αντί για σκέτο alembic upgrade
    # head — self-healing αν η βάση είναι σε "legacy" κατάσταση (δες το
    # module docstring στο scripts/migrate.py για το γιατί).
    from scripts.migrate import upgrade_to_head

    upgrade_to_head()

    # Default 5001 — το 5000 το κρατάει συχνά το AirPlay Receiver στο macOS.
    port = int(os.getenv("PORT", "5001"))
    # debug: ΠΟΤΕ True by default σε production (Werkzeug debugger = RCE risk).
    # Ακολουθεί το config.py (FLASK_DEBUG / FLASK_ENV=development).
    app.run(host="0.0.0.0", port=port, debug=app.config["DEBUG"])
