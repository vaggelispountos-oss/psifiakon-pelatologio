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
Καθημερινό backup της production Postgres μέσω
[`.github/workflows/backup.yml`](.github/workflows/backup.yml) (χρειάζεται το
GitHub secret `DATABASE_URL`).

## Παραγωγή — γνωστά ανοιχτά θέματα

- Render free plan: κρύο ξεκίνημα ~50s στο πρώτο request μετά από αδράνεια,
  και το Postgres free tier δεν έχει automated backups (καλύπτεται προσωρινά
  από το `backup.yml` παραπάνω) — προγραμματισμένη αναβάθμιση σε paid plan.
- Encryption migration: αν αναβάθμισες πρόσφατα σε κρυπτογραφημένα AADE
  keys (`crypto.py`), βεβαιώσου ότι έχεις τρέξει το
  `backend/migrate_encrypt_settings.py` ΜΙΑ φορά στην production βάση (δες
  οδηγίες μέσα στο αρχείο) — αλλιώς τα παλιά plaintext keys παραμένουν
  ακρυπτογράφητα.
