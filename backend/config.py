"""
config.py
Ρυθμίσεις εφαρμογής μέσω environment variables (.env).
"""
import os
from dotenv import load_dotenv

# Φόρτωση μεταβλητών από αρχείο .env (αν υπάρχει)
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Flask (Flask-SQLAlchemy) βάζει το instance_path εδώ by default — εκεί
# καταλήγει στην πράξη το SQLite αρχείο όταν το URI είναι σχετικό διάδρομος
# (π.χ. "sqlite:///dcl.db" -> backend/instance/dcl.db, ΟΧΙ backend/dcl.db).
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


def _normalize_db_url(url):
    """
    Το Render (και άλλοι) δίνουν DATABASE_URL με πρόθεμα postgres://, που το
    SQLAlchemy 1.4+ απορρίπτει — θέλει postgresql://. Ίδιο connection string,
    απλά διορθωμένο scheme.

    Για SQLite με ΣΧΕΤΙΚΟ path, μετατρέπουμε ρητά σε απόλυτο μέσα στο
    instance/ — ΙΔΙΑ σύμβαση με το Flask-SQLAlchemy. Χωρίς αυτό, δύο
    εργαλεία που ανοίγουν το ΙΔΙΟ "sqlite:///dcl.db" καταλήγουν σε
    ΔΙΑΦΟΡΕΤΙΚΑ αρχεία ανάλογα με το cwd από το οποίο τρέχουν: το Flask app
    (μέσω app.py, οπουδήποτε κι αν εκκινείται) πάει σε backend/instance/
    dcl.db, ενώ ένα plain SQLAlchemy engine (π.χ. Alembic) θα έφτιαχνε
    backend/dcl.db — δύο βάσεις που «χάνουν» η μία την άλλη σιωπηλά.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        rel_path = url[len("sqlite:///"):]
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        url = "sqlite:///" + os.path.join(INSTANCE_DIR, rel_path)
    return url


class Config:
    # Περιβάλλον εκτέλεσης του Flask
    FLASK_ENV = os.getenv("FLASK_ENV", "development")

    # Σύνδεση βάσης δεδομένων. Default: τοπικό SQLite αρχείο.
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'dcl.db')}")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Αν True, χρησιμοποιείται το mock ΑΑΔΕ (MockAadeService).
    # Όταν έρθει το πραγματικό, αλλάζει σε false και φορτώνεται ο real client.
    USE_MOCK_AADE = os.getenv("USE_MOCK_AADE", "true").lower() == "true"

    # CORS origins για τα /api/* routes. Default "*" (βολικό για tunnels στο
    # dev/testing — δες app.py). ΓΙΑ PRODUCTION όρισε ρητά CORS_ORIGINS στο
    # .env με το πραγματικό origin του frontend (π.χ. https://app.mygarage.gr),
    # ή comma-separated λίστα για πολλαπλά origins.
    _cors_env = os.getenv("CORS_ORIGINS", "*").strip()
    CORS_ORIGINS = (
        "*" if _cors_env == "*" else [o.strip() for o in _cors_env.split(",") if o.strip()]
    )

    # Ενεργοποιεί τον Werkzeug debugger (ΠΟΤΕ σε production — επιτρέπει
    # εκτέλεση αυθαίρετου κώδικα μέσω της error page). Default: ακολουθεί το
    # FLASK_ENV, ΟΧΙ πάντα True.
    DEBUG = os.getenv("FLASK_DEBUG", "true" if FLASK_ENV == "development" else "false").lower() == "true"

    # --- Auth (multi-tenant) ---
    # ΥΠΟΧΡΕΩΤΙΚΟ να οριστεί ρητά σε production (.env) — το default εδώ είναι
    # ΜΟΝΟ για τοπική ανάπτυξη, ώστε να μη σκάει σε πρώτη εκκίνηση χωρίς .env.
    _DEV_JWT_SECRET = "dev-insecure-secret-change-me"
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", _DEV_JWT_SECRET)
    # Access token: ζει λίγο. Refresh token: ζει πολύ — ανανεώνει το access.
    JWT_ACCESS_TOKEN_EXPIRES_MIN = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MIN", "60"))
    JWT_REFRESH_TOKEN_EXPIRES_DAYS = int(
        os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS", "30")
    )

    # --- Trial ---
    # Μέρες δωρεάν δοκιμαστικής περιόδου από την εγγραφή. Μετά, το require_auth
    # μπλοκάρει (402) μέχρι χειροκίνητη ενεργοποίηση μέσω /api/admin.
    TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "14"))

    # --- Admin (χειροκίνητη έγκριση συνδρομών μετά από τραπεζική μεταφορά) ---
    # Μοιραζόμενο μυστικό — μπαίνει στο header X-Admin-Key. Άδειο (default) =
    # τα admin endpoints είναι ΚΛΕΙΣΤΑ (401 σε όλα), όχι ανοιχτά χωρίς κλειδί.
    ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()

    # Αριθμός εγκατάστασης (branch) του συνεργείου. 0 = κεντρικό/έδρα.
    BRANCH_NUMBER = int(os.getenv("BRANCH_NUMBER", "0"))

    # --- Πραγματική ΑΑΔΕ (real_aade.py) ---
    # Περιβάλλον: "dev" (δοκιμαστικό) ή "prod" (παραγωγή). Default dev.
    AADE_ENV = os.getenv("AADE_ENV", "dev").lower()

    # Base URL του API Ψηφιακού Πελατολογίου. Αν δεν οριστεί ρητά, επιλέγεται
    # βάσει του AADE_ENV.
    _AADE_URLS = {
        "dev": "https://mydataapidev.aade.gr/DCL/",
        "prod": "https://mydatapi.aade.gr/DCL/",
    }
    AADE_BASE_URL = os.getenv("AADE_BASE_URL") or _AADE_URLS.get(
        AADE_ENV, _AADE_URLS["dev"]
    )

    # --- Αναγνώριση πινακίδας μέσω ALPR (Plate Recognizer) ---
    # Το token μένει ΜΟΝΟ στο backend: το frontend χτυπά το /api/ocr/plate και
    # ο Flask προωθεί. Αν το βάζαμε σε VITE_* θα κατέληγε στο bundle, δηλαδή
    # ορατό σε οποιονδήποτε ανοίγει το site.
    PLATE_RECOGNIZER_TOKEN = os.getenv("PLATE_RECOGNIZER_TOKEN", "").strip()
    PLATE_RECOGNIZER_URL = os.getenv(
        "PLATE_RECOGNIZER_URL", "https://api.platerecognizer.com/v1/plate-reader/"
    )
    # Περιορισμός σε ελληνικές πινακίδες — ανεβάζει αισθητά την ακρίβεια.
    PLATE_RECOGNIZER_REGIONS = os.getenv("PLATE_RECOGNIZER_REGIONS", "gr")

    # Μέγιστο μέγεθος request body (bytes) — προστασία από τεράστια uploads
    # (π.χ. στο /api/ocr/plate). Default 8MB. Το Flask επιστρέφει 413
    # αυτόματα αν ξεπεραστεί.
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(8 * 1024 * 1024)))

    # --- Κρυπτογράφηση ευαίσθητων στηλών στη βάση (aade_subscription_key) ---
    # Fernet key (32 bytes urlsafe-base64), π.χ. `python -c "from
    # cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    # ΥΠΟΧΡΕΩΤΙΚΟ να οριστεί ρητά σε production. Χωρίς αυτό στο dev, παράγεται
    # ένα προσωρινό κλειδί ΣΤΗ ΜΝΗΜΗ σε κάθε εκκίνηση — προηγούμενα
    # κρυπτογραφημένα δεδομένα γίνονται μη αναγνώσιμα μετά από restart, οπότε
    # ΜΗΝ το αφήνεις έτσι πέρα από τοπική δοκιμή.
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "").strip()

    # --- Telemetry OCR (προαιρετικό) ---
    # Αν TELEMETRY_URL οριστεί, ΚΑΘΕ μετρική OCR (κάθε σάρωση πινακίδας)
    # προωθείται ΚΑΙ σε αυτό το URL — τυπικά τον δικό σου κεντρικό server
    # (δες telemetry-server/). Έτσι, όταν πουλάς το πρόγραμμα και το κάθε
    # συνεργείο τρέχει το ΔΙΚΟ ΤΟΥ backend/βάση, εσύ βλέπεις συγκεντρωτικά
    # δεδομένα από ΟΛΕΣ τις εγκαταστάσεις χωρίς να χρειάζεσαι πρόσβαση στο
    # μηχάνημα του καθενός. Κενό (default) = τίποτα δεν στέλνεται πουθενά.
    TELEMETRY_URL = os.getenv("TELEMETRY_URL", "").strip()
    # Κοινό μυστικό ανάμεσα σε ΟΛΕΣ τις εγκαταστάσεις και τον server σου —
    # πρέπει να ταιριάζει με το INGEST_KEY του telemetry-server.
    TELEMETRY_KEY = os.getenv("TELEMETRY_KEY", "").strip()

    # --- Email (επαναφορά κωδικού, μέσω Resend REST API) ---
    # Κενό (default) = δεν στέλνεται πραγματικό email· το email_service.py
    # καταγράφει το link στο log αντί να σκάει, ώστε να δουλεύει η ροή
    # τοπικά πριν ρυθμιστεί πραγματικός λογαριασμός Resend.
    RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
    RESEND_FROM_EMAIL = os.getenv(
        "RESEND_FROM_EMAIL", "Ψηφιακό Πελατολόγιο <onboarding@resend.dev>"
    )
    # Origin του frontend — χρησιμοποιείται για να χτιστεί το link επαναφοράς
    # κωδικού (/reset-password?token=...) μέσα στο email.
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")


def validate_production_config(config=Config):
    """
    Σκάει νωρίς (στην εκκίνηση) αν λείπουν κρίσιμα μυστικά σε production, αντί
    να τρέξει η εφαρμογή με ανασφαλή defaults (κοινό JWT secret, κλειδιά ΑΑΔΕ
    χωρίς πραγματική κρυπτογράφηση). Καλείται από το app.py μόνο όταν
    FLASK_ENV == "production".
    """
    problems = []
    if config.JWT_SECRET_KEY == config._DEV_JWT_SECRET:
        problems.append(
            "JWT_SECRET_KEY δεν έχει οριστεί (χρησιμοποιείται το ανασφαλές "
            "dev default) — όρισέ το στο .env."
        )
    if not config.ENCRYPTION_KEY:
        problems.append(
            "ENCRYPTION_KEY δεν έχει οριστεί — το aade_subscription_key θα "
            "κρυπτογραφείται με προσωρινό κλειδί που χάνεται σε κάθε restart. "
            "Όρισέ το στο .env (python -c \"from cryptography.fernet import "
            "Fernet; print(Fernet.generate_key().decode())\")."
        )
    # ⚠️ ΠΡΟΕΙΔΟΠΟΙΗΣΗ, ΟΧΙ σφάλμα — σκόπιμα.
    # Το CORS_ORIGINS είναι σήμερα `sync: false` στο render.yaml (δηλαδή
    # χωρίς τιμή -> "*"). Αν αυτό γινόταν hard failure, το ΕΠΟΜΕΝΟ deploy θα
    # έριχνε το production αντί απλώς να το κάνει πιο ασφαλές.
    # ΕΠΟΜΕΝΟ ΒΗΜΑ: όρισε CORS_ORIGINS στο Render dashboard με το πραγματικό
    # origin του frontend, ΜΕΤΑ μετέτρεψε αυτό σε problems.append(...) ώστε
    # να μη μπορεί να ξαναφύγει ανασφαλές σε production.
    if config.CORS_ORIGINS == "*":
        print(
            "[config] ΠΡΟΣΟΧΗ: CORS_ORIGINS='*' σε production — οποιοδήποτε "
            "site μπορεί να καλέσει το API από τον browser του χρήστη. Όρισε "
            "το πραγματικό origin του frontend στο Render."
        )
    if problems:
        raise RuntimeError(
            "Μη ασφαλής ρύθμιση production:\n- " + "\n- ".join(problems)
        )
