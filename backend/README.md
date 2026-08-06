# Backend — Ψηφιακό Πελατολόγιο Οχημάτων (ΑΑΔΕ)

Flask backend, **multi-tenant**: κάθε συνεργείο-πελάτης (`Workshop`) έχει
δικό του λογαριασμό (email/password + JWT) και βλέπει ΜΟΝΟ τα δικά του
δεδομένα. Δύο τύποι επιχείρησης ανά workshop: `garage` (Συνεργείο, 4 Χρόνοι
πλήρεις) και `rental` (Ενοικίαση Οχημάτων, 3 Χρόνοι — χωρίς κατηγορία
υπηρεσίας). Deploy: Render (`render.yaml`), Postgres σε production, SQLite σε
τοπική ανάπτυξη.

## mock vs πραγματική ΑΑΔΕ

Η επικοινωνία με την ΑΑΔΕ γίνεται είτε μέσω [`mock_aade.py`](mock_aade.py)
(`MockAadeService`, προσομοίωση — καμία πραγματική κλήση) είτε μέσω
[`real_aade.py`](real_aade.py) (`RealAadeService`, πραγματικές κλήσεις XML).
Ελέγχεται από το env var `USE_MOCK_AADE` (global default) — μπορεί να γίνει
override **ανά workshop** μέσω `force_real_aade` (admin endpoint, δες
παρακάτω), ώστε να δοκιμαστεί πραγματική ΑΑΔΕ σε ένα workshop χωρίς να
επηρεαστούν οι υπόλοιποι tenants. Και οι δύο υλοποιήσεις έχουν το ίδιο
interface (`send_client`, `update_client`, `client_correlations`,
`cancel_client`) — η λογική των 4 Χρόνων δεν ξέρει ποια χρησιμοποιείται.

## Η λογική των 4 «Χρόνων»

| Χρόνος | Endpoint | Μέθοδος ΑΑΔΕ | Τι κάνει |
|--------|----------|--------------|----------|
| 1ος | `POST /api/dcl/entry` | SendClient | Δημιουργεί εγγραφή, παίρνει `idDcl` + `creationDateTime` |
| 2ος | `POST /api/dcl/service` | UpdateClient | Κατηγορία υπηρεσίας (ΜΟΝΟ `garage` — τα `rental` πάνε κατευθείαν στην Ολοκλήρωση) |
| 3ος | `POST /api/dcl/exit` | UpdateClient (`entryCompletion`) | Ολοκλήρωση, παίρνει `completionDateTime` |
| 4ος | `POST /api/dcl/correlate` | ClientCorrelations | Συσχέτιση παραστατικού (ΜΑΡΚ), παίρνει `correlateId` |
| — | `POST /api/dcl/cancel` | CancelClient | Ακύρωση εγγραφής |
| — | `POST /api/dcl/entries/<id>/resend` | — | Ξαναστέλνει τον τελευταίο Χρόνο αν δεν επιβεβαιώθηκε από την ΑΑΔΕ (π.χ. έπεσε το internet) |

## Εγκατάσταση & εκτέλεση

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # προαιρετικό — δουλεύει και χωρίς αυτό
python app.py
```

Το SQLite DB (`dcl.db`) δημιουργείται **αυτόματα** στο πρώτο τρέξιμο.
Ο server ακούει στο `http://localhost:5001` (ΟΧΙ 5000 — το κρατάει το
AirPlay στο macOS). Σε production (`FLASK_ENV=production`), το backend
σηκώνεται με `validate_production_config()` που **σκάει νωρίς** αν λείπουν
κρίσιμα μυστικά (`JWT_SECRET_KEY`, `ENCRYPTION_KEY`) — δες `config.py`.

## Auth

Multi-tenant JWT auth (`auth.py`). Το JWT identity είναι το `workshop.id`.
Κάθε προστατευμένο endpoint καλεί `require_auth` που θέτει `g.workshop_id`
και ελέγχει ενεργή συνδρομή (`trial`/`active` — αλλιώς 402).

| Endpoint | Μέθοδος | Τι κάνει |
|---|---|---|
| `/api/auth/register` | POST | Νέο workshop + tokens (rate limited: 10/min) |
| `/api/auth/login` | POST | Έλεγχος credentials + tokens (rate limited: 10/min) |
| `/api/auth/refresh` | POST | Νέο access token από refresh token |
| `/api/auth/me` | GET | Στοιχεία του logged-in workshop |
| `/api/auth/password` | PUT | Αλλαγή κωδικού (`currentPassword`, `newPassword`) |
| `/api/auth/business-type` | PUT | Αλλαγή `garage`/`rental` (επηρεάζει μόνο ΝΕΕΣ εγγραφές) |
| `/api/auth/forgot-password` | POST | Στέλνει email επαναφοράς (rate limited: 5/min) — δες `email_service.py` |
| `/api/auth/reset-password` | POST | Ολοκλήρωση επαναφοράς με token |

Rate limiting: `Flask-Limiter`, in-memory storage (αρκεί για ένα Render
instance). Backend πίσω από `ProxyFix` ώστε το per-IP limiting να βλέπει την
πραγματική IP του χρήστη, όχι του Render proxy.

### Admin (`X-Admin-Key` header, `ADMIN_KEY` env var)

| Endpoint | Μέθοδος | Τι κάνει |
|---|---|---|
| `/api/admin/workshops` | GET | Λίστα όλων των workshops |
| `/api/admin/workshops/<id>/status` | PUT | Αλλαγή `subscription_status` (χειροκίνητο billing) |
| `/api/admin/workshops/<id>/trial` | PUT | Παράταση trial (`days`) |
| `/api/admin/workshops/<id>/aade-mode` | PUT | Per-workshop override σε πραγματική ΑΑΔΕ |

## Βασικά endpoints (όλα `@require_auth` εκτός `/api/health`)

- `GET/PUT /api/settings` — credentials ΑΑΔΕ (subscription key κρυπτογραφημένο στη βάση, δες `crypto.py`)
- `POST /api/settings/test-connection` — ελαφριά κλήση RequestClients
- `GET /api/customers?q=` — βάση πελατών/οχημάτων (αναζήτηση σε πινακίδα/όνομα/ΑΦΜ/τηλέφωνο)
- `PATCH /api/customers/<id>` — επεξεργασία στοιχείων πελάτη
- `GET /api/dcl/entries?limit=&offset=` — λίστα εγγραφών, **paginated** (default limit 200, max 500· `X-Total-Count` header)
- `GET /api/dcl/entries/<id>` — μία εγγραφή + audit log (`AadeLogs`)
- `GET /api/dcl/reconcile/<id>` — σύγκριση τοπικής εγγραφής με την ΑΑΔΕ
- `GET/POST/PATCH /api/ocr/metrics*` — μετρικές ποιότητας OCR (fire-and-forget από το frontend)
- `GET /api/account/export` / `DELETE /api/account` — GDPR: εξαγωγή δεδομένων / οριστική διαγραφή

## Δομή project

```
backend/
├── app.py                       # Flask app + endpoints + λογική 4 Χρόνων
├── auth.py                      # Multi-tenant auth, JWT, rate limiting, admin
├── models.py                    # SQLAlchemy models (Workshop, Customer, DclEntry, AadeLog, Settings, OcrMetric)
├── crypto.py                    # Κρυπτογράφηση aade_subscription_key (Fernet)
├── email_service.py             # Resend REST API (password reset) — καταγράφει link στο log αν δεν έχει ρυθμιστεί
├── mock_aade.py / real_aade.py  # Δύο υλοποιήσεις του ίδιου ΑΑΔΕ interface
├── migrate_encrypt_settings.py  # One-off migration: plaintext -> encrypted keys (δες παρακάτω)
├── config.py                    # Ρυθμίσεις από .env + validate_production_config()
├── scripts/backup_db.sh         # pg_dump backup (τρέχει από .github/workflows/backup.yml)
├── requirements.txt / requirements-dev.txt
└── tests/
```

## Migration: κρυπτογράφηση AADE keys σε production

Αν αυτή είναι η πρώτη φορά που ενεργοποιείς την κρυπτογράφηση
(`crypto.py`/`ENCRYPTION_KEY`) σε ένα backend που έτρεχε ήδη με plaintext
`aade_subscription_key` στη βάση, πρέπει να τρέξεις **μία φορά**, με
πρόσβαση στην production βάση:

```bash
# Render dashboard -> dcl-backend -> Shell
cd backend && python migrate_encrypt_settings.py
```

Idempotent (μπορείς να το ξανατρέξεις χωρίς βλάβη — τιμές που είναι ήδη
κρυπτογραφημένες παραμένουν όπως είναι). Χωρίς αυτό, οι ΗΔΗ αποθηκευμένες
τιμές παραμένουν σε plaintext στη βάση (οι ΝΕΕΣ αποθηκεύσεις κρυπτογραφούνται
κανονικά — το πρόβλημα αφορά μόνο ιστορικά δεδομένα).

## Πραγματική ΑΑΔΕ (`real_aade.py`)

- **Μεταφορά XML** (όχι JSON): χτίζει XML σύμφωνο με τα επίσημα XSD στο
  [`aade_specs/DCL_v1_1/`](aade_specs/DCL_v1_1/), κάνει **XSD validation πριν την
  αποστολή**, και διαβάζει το `ResponseDoc`.
- **Headers**: `aade-user-id`, `ocp-apim-subscription-key` (από τις Ρυθμίσεις, ανά workshop).
- **URLs**: dev `https://mydataapidev.aade.gr/DCL/`, prod
  `https://mydatapi.aade.gr/DCL/` (μέσω `AADE_ENV`).
- **Δύο είδη σφαλμάτων**: τεχνικά (HTTP status — 401 = λάθος κωδικοί) και
  επιχειρησιακά (HTTP 200 **αλλά** `statusCode != Success` μέσα στο XML).
  Ελέγχεται **πάντα** το `statusCode`.
- **Timeout + retry** (2 προσπάθειες) για δικτυακά σφάλματα.

### Απαραίτητα specs
Κατέβασε (μία φορά) τα επίσημα XSD/παραδείγματα στο `aade_specs/`:
- XSDs: `DCL_v1_1.zip` → `aade_specs/DCL_v1_1/`
- Παραδείγματα: `SendClient.zip`, `UpdateClient.zip`

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest -v
```

Καμία πραγματική κλήση ΑΑΔΕ (mock HTTP layer με `responses`). Τρέχουν
αυτόματα σε κάθε push/PR ([`../.github/workflows/tests.yml`](../.github/workflows/tests.yml)).

## Audit log

Κάθε κλήση προς την ΑΑΔΕ (SendClient/UpdateClient/ClientCorrelations/
CancelClient) καταγράφεται στον πίνακα `aade_logs` με το request/response και
αν πέτυχε. Τα βλέπεις μέσω `GET /api/dcl/entries/<id>`.
