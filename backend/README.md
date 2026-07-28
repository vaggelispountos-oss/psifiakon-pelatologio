# Backend — Ψηφιακό Πελατολόγιο Οχημάτων (ΑΑΔΕ) — MVP

Flask backend για σύστημα Ψηφιακού Πελατολογίου Οχημάτων για συνεργείο
αυτοκινήτων. **MVP για ΕΝΑ συνεργείο (single-tenant)** με **ΨΕΥΤΙΚΟ (mock)
ΑΑΔΕ** — δεν καλεί ακόμα πραγματική ΑΑΔΕ.

## ⚠️ Σημαντικό — mock vs πραγματικό ΑΑΔΕ

Όλη η επικοινωνία με την ΑΑΔΕ γίνεται μέσω του αρχείου
[`mock_aade.py`](mock_aade.py) (κλάση `MockAadeService`). Αυτό **προσομοιώνει**
τις απαντήσεις — δεν κάνει πραγματικά HTTP calls.

Όταν έρθει η ώρα για σύνδεση με την **πραγματική ΑΑΔΕ**, φτιάχνεις ένα
`real_aade.py` με κλάση `RealAadeService` που έχει **ΤΗΝ ΙΔΙΑ διεπαφή**:

```python
send_client(data)
update_client(id_dcl, data)
client_correlations(id_dcl, data)
cancel_client(id_dcl)
```

Μετά αλλάζεις **μόνο** το `USE_MOCK_AADE=false` και το import στο
[`app.py`](app.py) (υπάρχει σχόλιο-placeholder). **Η λογική των 4 Χρόνων δεν
πειράζεται.**

## Η λογική των 4 «Χρόνων»

Το backend δεν είναι απλή είσοδος/έξοδος. Ακολουθεί τους 4 Χρόνους της ΑΑΔΕ:

| Χρόνος | Endpoint | Μέθοδος ΑΑΔΕ | Τι κάνει |
|--------|----------|--------------|----------|
| 1ος | `POST /api/dcl/entry` | SendClient | Δημιουργεί εγγραφή, παίρνει `idDcl` + `creationDateTime` |
| 2ος | `POST /api/dcl/service` | UpdateClient | Καταχώρηση κατηγορίας παρεχόμενης υπηρεσίας |
| 3ος | `POST /api/dcl/exit` | UpdateClient (`entryCompletion`) | Ολοκλήρωση, παίρνει `completionDateTime` |
| 4ος | `POST /api/dcl/correlate` | ClientCorrelations | Συσχέτιση παραστατικού (ΜΑΡΚ), παίρνει `correlateId` |
| — | `POST /api/dcl/cancel` | CancelClient | Ακύρωση εγγραφής |

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
Ο server ακούει στο `http://localhost:5000`.

## Endpoints

### `GET /api/health`
Έλεγχος ζωής. → `{"status": "ok"}`

### `POST /api/dcl/entry` — 1ος Χρόνος
```json
{ "plate": "ΑΒΓ1234", "branch": 0, "customerName": "Γιάννης",
  "vat": "123456789", "vehicleCategory": "ΙΧ", "vehicleFactory": "Toyota",
  "comments": "..." }
```
→ `{ "entry_id", "idDcl", "creationDateTime", "status": "open" }`

### `POST /api/dcl/service` — 2ος Χρόνος
```json
{ "entry_id": 1, "providedServiceCategory": 1,
  "providedServiceCategoryOther": null, "comments": "..." }
```
`providedServiceCategory` ∈ {1,2,3,9,4,6,5}. Αν είναι **5**, το
`providedServiceCategoryOther` είναι **υποχρεωτικό**.
→ `{ "updateUniqueId", "status": "in_progress" }`

### `POST /api/dcl/exit` — 3ος Χρόνος
```json
{ "entry_id": 1, "invoiceKind": 1, "reasonNonIssueType": null }
```
`invoiceKind` ∈ {1=ΑΛΠ/ΑΠΥ, 2=Τιμολόγιο, 3=ΑΛΠ/ΑΠΥ-ΦΗΜ}.
→ `{ "completionDateTime", "status": "completed" }`

### `POST /api/dcl/correlate` — 4ος Χρόνος
```json
{ "entry_id": 1, "mark": "400001234567890" }
```
→ `{ "correlateId", "status": "correlated" }`

### `POST /api/dcl/cancel`
```json
{ "entry_id": 1 }
```
→ `{ "cancellationId", "status": "cancelled" }`

### `GET /api/dcl/entries`
Λίστα όλων των εγγραφών με το status τους.

### `GET /api/dcl/entries/<id>`
Μία εγγραφή με πλήρη στοιχεία + τα `AadeLogs` της (audit).

## Δομή project

```
backend/
├── app.py            # Flask app + endpoints + λογική 4 Χρόνων
├── models.py         # SQLAlchemy models (Customer, DclEntry, AadeLog)
├── mock_aade.py      # ΨΕΥΤΙΚΗ ΑΑΔΕ — θα αντικατασταθεί από real_aade.py
├── config.py         # Ρυθμίσεις από .env
├── requirements.txt
├── .env.example
└── README.md
```

## Πραγματική ΑΑΔΕ (`real_aade.py`)

Το [`real_aade.py`](real_aade.py) είναι η **πραγματική** σύνδεση με το API
Ψηφιακού Πελατολογίου (myDATA DCL). Έχει **ίδιο interface** με το mock — η
εναλλαγή γίνεται μόνο με `USE_MOCK_AADE`.

- **Μεταφορά XML** (όχι JSON): χτίζει XML σύμφωνο με τα επίσημα XSD στο
  [`aade_specs/DCL_v1_1/`](aade_specs/DCL_v1_1/), κάνει **XSD validation πριν την
  αποστολή**, και διαβάζει το `ResponseDoc`.
- **Headers**: `aade-user-id`, `ocp-apim-subscription-key` (από τις Ρυθμίσεις).
- **URLs**: dev `https://mydataapidev.aade.gr/DCL/`, prod
  `https://mydatapi.aade.gr/DCL/` (μέσω `AADE_ENV`).
- **Δύο είδη σφαλμάτων**: τεχνικά (HTTP status — 401 = λάθος κωδικοί) και
  επιχειρησιακά (HTTP 200 **αλλά** `statusCode != Success` μέσα στο XML — π.χ.
  κωδικός 203 «mandatory field»). Ελέγχεται **πάντα** το `statusCode`.
- **Timeout + retry** (2 προσπάθειες) για δικτυακά σφάλματα.

### ⚠️ Απαραίτητα specs
Κατέβασε (μία φορά) τα επίσημα XSD/παραδείγματα στο `aade_specs/`:
- XSDs: `DCL_v1_1.zip` → `aade_specs/DCL_v1_1/`
- Παραδείγματα: `SendClient.zip`, `UpdateClient.zip`

### Unit tests (χωρίς πραγματική ΑΑΔΕ)
Τα tests κάνουν mock το HTTP layer (`responses`) — καμία πραγματική κλήση:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

### Τι μένει να επιβεβαιωθεί ΜΟΝΟ με πραγματικά dev credentials
1. Βγάλε dev credentials από `mydata-dev-register.azurewebsites.net`.
2. Βάλ' τα στις «Ρυθμίσεις ΑΑΔΕ» + `USE_MOCK_AADE=false`, `AADE_ENV=dev`.
3. Τρέξε πλήρη ροή 4 Χρόνων στο **δοκιμαστικό** και επιβεβαίωσε:
   - ότι τα endpoint paths/μορφή σώματος γίνονται δεκτά (η ΑΑΔΕ επιστρέφει
     `Success` + `newClientDclID` κ.λπ.),
   - τα `creationDateTime`/`completionDateTime` (η ΑΑΔΕ **δεν** τα επιστρέφει στο
     `ResponseDoc` — χρησιμοποιούμε τοπικό UTC· η αυθεντική τιμή αντλείται με
     `RequestClients`),
   - το πλήρες parsing του `RequestedDoc` (έχει `TODO` — τώρα επιστρέφει raw XML
     + `continuationToken`).

## Audit log

Κάθε κλήση προς την ΑΑΔΕ (SendClient/UpdateClient/ClientCorrelations/
CancelClient) καταγράφεται στον πίνακα `aade_logs` με το request/response και
αν πέτυχε. Τα βλέπεις μέσω `GET /api/dcl/entries/<id>`.
