# OCR Telemetry Server

Ξεχωριστός, ελαφρύς server — τον φιλοξενείς ΕΣΥ (ο πωλητής του λογισμικού),
ΟΧΙ ο κάθε πελάτης. Μαζεύει δεδομένα OCR από ΟΛΕΣ τις εγκαταστάσεις του
`backend/` ώστε να βλέπεις συγκεντρωτικά πόσο καλά δουλεύει η αναγνώριση
πινακίδας, χωρίς να χρειάζεσαι πρόσβαση στο μηχάνημα κάθε συνεργείου.

## Τοπική δοκιμή

```bash
cd telemetry-server
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # συμπλήρωσε INGEST_KEY και DASHBOARD_KEY
python app.py
```

Δοκίμασε: `http://localhost:5050/health`

## Σύνδεση με κάθε εγκατάσταση πελάτη

Σε κάθε `backend/.env` πελάτη, πρόσθεσε:

```
TELEMETRY_URL=https://<το-δικό-σου-deployment>/ingest
TELEMETRY_KEY=<ίδιο με το INGEST_KEY εδώ>
```

Από εκεί και πέρα, κάθε σάρωση πινακίδας προωθείται αυτόματα (best-effort,
δεν επηρεάζει ποτέ τον πελάτη αν αποτύχει).

## Deployment (γρήγορη επιλογή: Render.com free tier)

1. Push αυτόν τον φάκελο σε ένα git repo (ή μόνο του, ή ως μέρος του
   μεγαλύτερου repo — βάλε "Root Directory: telemetry-server" στο Render).
2. Render -> New -> Web Service -> σύνδεσε το repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Environment variables: `INGEST_KEY`, `DASHBOARD_KEY` (και προαιρετικά
   `DATABASE_URL` αν θες Postgres αντί για το default SQLite).

## Προβολή στατιστικών

```
https://<deployment>/dashboard?key=<DASHBOARD_KEY>
```

⚠️ Το `/dashboard` δεν έχει σοβαρή προστασία πέρα από το query-param key —
είναι σκόπιμα απλό γιατί προορίζεται ΜΟΝΟ για δική σου εσωτερική χρήση, όχι
για δημόσια έκθεση. Μην το μοιραστείς και μην το indexάρεις.
