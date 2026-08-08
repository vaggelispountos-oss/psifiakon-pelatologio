# Ψηφιακό Πελατολόγιο Οχημάτων (ΑΑΔΕ)

SaaS εφαρμογή για συνεργεία αυτοκινήτων και επιχειρήσεις ενοικίασης οχημάτων
στην Ελλάδα, που τηρεί το **Ψηφιακό Πελατολόγιο** της ΑΑΔΕ (myDATA) — οι 4
«Χρόνοι» (SendClient → UpdateClient → UpdateClient/entryCompletion →
ClientCorrelations), σάρωση πινακίδας με OCR, και ιστορικό/βάση πελατών.

**Multi-tenant**: κάθε συνεργείο-πελάτης (Workshop) έχει δικό του λογαριασμό
και βλέπει ΜΟΝΟ τα δικά του δεδομένα.

## Αρχιτεκτονική / Deployment

```
frontend/   React + Vite (PWA)  →  deploy: Vercel (static)
backend/    Flask + Postgres    →  deploy: Render (render.yaml, gunicorn)
telemetry-server/  προαιρετικός κεντρικός server για συγκεντρωτικά OCR metrics
                    από όλες τις εγκαταστάσεις — δικό σου deploy, ξεχωριστό
```

Το frontend μιλάει με το backend μέσω `VITE_API_URL` (βλέπε
[`frontend/src/services/api.js`](frontend/src/services/api.js)). Δεν υπάρχει
proxy/rewrite ανάμεσά τους σε production — είναι δύο ανεξάρτητα deployments.

`render.yaml` στη ρίζα είναι η αρχή αλήθειας για το backend deployment
(Render Blueprint). Το `frontend/vercel.json` αφορά ΜΟΝΟ headers για το
Vercel static hosting του frontend (π.χ. cache-control για service worker) —
δεν τρέχει backend κώδικα.

## Δομή

| Φάκελος | Τι είναι |
|---|---|
| [`backend/`](backend/README.md) | Flask API, Postgres/SQLite, auth, ΑΑΔΕ integration |
| [`frontend/`](frontend/README.md) | React PWA — κάμερα/OCR πινακίδας, ροή 4 Χρόνων, βάση πελατών |
| [`telemetry-server/`](telemetry-server/README.md) | Προαιρετικός server συγκεντρωτικών OCR metrics (πολλαπλές εγκαταστάσεις) |

## Τοπική εκτέλεση

```bash
# Backend (http://localhost:5001)
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py

# Frontend (http://localhost:3000), σε άλλο terminal
cd frontend
npm install
npm run dev
```

Λεπτομέρειες ρυθμίσεων (.env, mock vs πραγματική ΑΑΔΕ, migrations) στο
[backend/README.md](backend/README.md).

## Tests / CI

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Τρέχουν αυτόματα σε κάθε push/PR στο `main` ([`.github/workflows/tests.yml`](.github/workflows/tests.yml)).

## Backup / Restore

```bash
# Backup (Postgres ή SQLite — επιλέγεται αυτόματα από το DATABASE_URL)
DATABASE_URL=... backend/scripts/backup_db.sh backups

# Restore (⚠️ ΚΑΤΑΣΤΡΟΦΙΚΟ — ζητά επιβεβαίωση, FORCE=1 για παράκαμψη)
DATABASE_URL=... backend/scripts/restore_db.sh backups/dcl-backup-....db.gz
```

Καθημερινό backup της production Postgres μέσω
[`.github/workflows/backup.yml`](.github/workflows/backup.yml).

> ⚠️ **Το GitHub secret `DATABASE_URL` πρέπει να είναι το External Database
> URL του Render**, όχι το Internal. Το internal hostname
> (`dpg-xxxxx-a`, χωρίς domain) επιλύεται ΜΟΝΟ μέσα στο δίκτυο του Render,
> οπότε από GitHub Actions το `pg_dump` σκάει με «could not translate host
> name». Ακριβώς έτσι απέτυχε σιωπηλά **κάθε** εκτέλεση του backup μέχρι
> τις 2026-08-08 — καμία επιτυχής, δηλαδή κανένα backup. Το
> `backup_db.sh` πλέον το ανιχνεύει και βγάζει ρητό μήνυμα αντί για το
> κρυπτικό DNS σφάλμα.

Τα backups κρατιούνται ως GitHub artifacts για 30 ημέρες. Κράτα το
`ENCRYPTION_KEY` **μαζί** με τα backups: τα κλειδιά ΑΑΔΕ είναι
κρυπτογραφημένα μ' αυτό, και restore με διαφορετικό κλειδί τα αφήνει μη
αναγνώσιμα (δες [`backend/crypto.py`](backend/crypto.py)).

## Health checks

| Endpoint | Σκοπός |
|---|---|
| `/api/health` | **Liveness** — ρηχό, δεν αγγίζει τη βάση. Αυτό δείχνει το `healthCheckPath` του Render. |
| `/api/health/ready` | **Readiness** — κάνει `SELECT 1`, γυρνά 503 αν η βάση δεν απαντά. Για monitoring/alerting. |

Ο διαχωρισμός είναι σκόπιμος: αν το `healthCheckPath` έλεγχε τη βάση, ένα
στιγμιαίο πρόβλημα σύνδεσης θα έβαζε το Render σε restart loop ακριβώς τη
στιγμή που η βάση δυσκολεύεται.

## Παραγωγή — γνωστά ανοιχτά θέματα

- Render free plan: κρύο ξεκίνημα ~50s στο πρώτο request μετά από αδράνεια,
  και το Postgres free tier δεν έχει automated backups (καλύπτεται προσωρινά
  από το `backup.yml` παραπάνω) — προγραμματισμένη αναβάθμιση σε paid plan.
- Encryption migration: αν αναβάθμισες πρόσφατα σε κρυπτογραφημένα AADE
  keys (`crypto.py`), βεβαιώσου ότι έχεις τρέξει το
  `backend/migrate_encrypt_settings.py` ΜΙΑ φορά στην production βάση (δες
  οδηγίες μέσα στο αρχείο) — αλλιώς τα παλιά plaintext keys παραμένουν
  ακρυπτογράφητα.
