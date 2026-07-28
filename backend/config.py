"""
config.py
Ρυθμίσεις εφαρμογής μέσω environment variables (.env).
"""
import os
from dotenv import load_dotenv

# Φόρτωση μεταβλητών από αρχείο .env (αν υπάρχει)
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _normalize_db_url(url):
    """Το Render (και άλλοι) δίνουν DATABASE_URL με πρόθεμα postgres://, που το
    SQLAlchemy 1.4+ απορρίπτει — θέλει postgresql://. Ίδιο connection string,
    απλά διορθωμένο scheme."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
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
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-insecure-secret-change-me")
    # Access token: ζει λίγο. Refresh token: ζει πολύ — ανανεώνει το access.
    JWT_ACCESS_TOKEN_EXPIRES_MIN = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MIN", "60"))
    JWT_REFRESH_TOKEN_EXPIRES_DAYS = int(
        os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS", "30")
    )

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
