# Frontend — Ψηφιακό Πελατολόγιο Οχημάτων (React + Vite)

React frontend (Vite) για το σύστημα Ψηφιακού Πελατολογίου. Συνδέεται με το
Flask backend και υλοποιεί τη ροή των **4 Χρόνων** της ΑΑΔΕ, με:

- **Κάμερα + OCR** (Tesseract.js) για αναγνώριση πινακίδας
- **Σκανάρισμα QR** (html5-qrcode) για εξαγωγή ΜΑΡΚ από απόδειξη
- Οθόνες **Εγγραφές / Πελάτες / Ιστορικό** — όλα από το backend (χωρίς localStorage)

## Ρύθμιση API URL

Το base URL διαβάζεται από `VITE_API_URL` (αρχείο `.env`). Default:
`http://localhost:5001`.

> ⚠️ Το Vite χρησιμοποιεί πρόθεμα **`VITE_`** (όχι `REACT_APP_`) και το backend
> τρέχει στο **5001** (στο macOS το 5000 το κρατάει το AirPlay Receiver).

```
VITE_API_URL=http://localhost:5001
```

## Εγκατάσταση & εκτέλεση

```bash
cd frontend
npm install
npm run dev
```

Ανοίγει στο `http://localhost:3000`. Το `host: true` στο `vite.config.js`
επιτρέπει πρόσβαση και από κινητό στο ίδιο δίκτυο (μέσω του LAN IP που τυπώνει
το Vite, π.χ. `http://192.168.1.x:3000`).

## Τρέξιμο frontend + backend μαζί (τοπικά)

Σε **δύο terminals**:

**Terminal 1 — backend**
```bash
cd backend
./venv/bin/python app.py      # ακούει στο http://localhost:5001
```

**Terminal 2 — frontend**
```bash
cd frontend
npm run dev                   # ανοίγει στο http://localhost:3000
```

Στην πάνω δεξιά γωνία της εφαρμογής ένα σήμα **● Online/Offline** δείχνει αν το
backend είναι προσβάσιμο.

## Δοκιμή σε κινητό (κάμερα/QR)

Η κάμερα και ο σαρωτής QR χρειάζονται **HTTPS ή localhost**. Στο κινητό:

- Άνοιξε το `http://<LAN-IP>:3000` (το IP που τυπώνει το Vite).
- Οι περισσότερες κινητές συσκευές **απαιτούν HTTPS** για την κάμερα σε μη-localhost
  διεύθυνση. Αν η κάμερα δεν ανοίγει, χρησιμοποίησε ένα HTTPS tunnel
  (π.χ. `ngrok http 3000`) και άνοιξε το https URL στο κινητό — ρυθμίζοντας το
  `VITE_API_URL` σε αντίστοιχο https tunnel του backend (5001).

## PWA (installable στο κινητό)

Το frontend είναι PWA (`vite-plugin-pwa`) — εγκαθίσταται στην αρχική οθόνη
("Add to Home Screen") σαν κανονική εφαρμογή. **Λειτουργεί μόνο στο production
build**, όχι στο `npm run dev`:

```bash
npm run build
npm run preview -- --port 4173
```

Δοκιμή σε κινητό: χρειάζεται HTTPS (ή localhost) όπως και η κάμερα παραπάνω —
χρησιμοποίησε ένα tunnel (ngrok/cloudflared) πάνω στο `4173`. Στο iOS Safari:
μενού Share → «Προσθήκη στην Αρχική Οθόνη». Στο Android Chrome: banner
«Εγκατάσταση εφαρμογής» ή μενού ⋮ → «Εγκατάσταση εφαρμογής».

Τα εικονίδια (`public/pwa-*.png`, `apple-touch-icon.png`, `maskable-512.png`)
είναι ένα απλό μονόγραμμα «Π» — αντικατέστησέ τα με το πραγματικό λογότυπο
πριν την κυκλοφορία.

## Δομή

```
frontend/
├── index.html
├── vite.config.js
├── .env.example
└── src/
    ├── main.jsx
    ├── App.jsx              # ενορχήστρωση 4 Χρόνων + tabs
    ├── App.css
    ├── constants.js         # κωδικοί ΑΑΔΕ (κατηγορίες, παραστατικά, status)
    ├── utils.js             # parsePlate() + parseMark()
    ├── services/
    │   └── api.js           # API client (createEntry, addService, ...)
    └── components/
        ├── CameraCapture.jsx # 1ος Χρόνος — κάμερα + OCR
        ├── ServiceForm.jsx   # 2ος Χρόνος — κατηγορία εργασίας
        ├── ExitForm.jsx      # 3ος Χρόνος — είδος παραστατικού
        ├── QrScanner.jsx     # 4ος Χρόνος — QR -> ΜΑΡΚ
        ├── EntriesList.jsx   # λίστα εγγραφών ανά status
        ├── CustomerDatabase.jsx
        └── HistoryLog.jsx
```

## Η ροή των 4 Χρόνων στο UI

1. **Λειτουργία → Κάμερα**: τράβα πινακίδα → `POST /api/dcl/entry` → παίρνεις
   `idDcl` (εμφανίζεται).
2. **Κατηγορία εργασίας** (dropdown· «Λοιπά» = ελεύθερο κείμενο υποχρεωτικό) →
   `POST /api/dcl/service`.
3. **Ολοκλήρωση** (Είδος Παραστατικού) → `POST /api/dcl/exit` → εμφανίζεται
   `completionDateTime`.
4. **Σκανάρισμα QR** → εξαγωγή ΜΑΡΚ (με χειροκίνητη διόρθωση) →
   `POST /api/dcl/correlate`.

Στην καρτέλα **Εγγραφές** κάθε όχημα δείχνει σε ποιον Χρόνο βρίσκεται και έχει
κουμπί για το επόμενο βήμα.
