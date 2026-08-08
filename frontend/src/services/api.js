// services/api.js
// --------------------------------------------------------------------
// API client για το Flask backend (Ψηφιακό Πελατολόγιο - 4 Χρόνοι).
//
// Base URL από environment variable (Vite: import.meta.env.VITE_API_URL).
// Default: http://localhost:5001  (ΟΧΙ 5000 — το κρατάει το AirPlay στο macOS).
// --------------------------------------------------------------------

// Default: ΚΕΝΟ = σχετικές διαδρομές (/api/...) που περνούν από τον Vite proxy
// στο backend. Δουλεύει και σε localhost και μέσω tunnel (ngrok/cloudflared)
// με ΕΝΑ μόνο tunnel. Αν χρειαστείς δύο tunnels, όρισε VITE_API_URL στο https
// tunnel του backend.
const API_URL = (import.meta.env && import.meta.env.VITE_API_URL) || "";

// --------------------------------------------------------------------
// Auth: το access token μπαίνει σε ΚΑΘΕ request (Authorization: Bearer).
// Αποθηκεύεται στο localStorage ώστε να επιζεί από refresh της σελίδας.
// --------------------------------------------------------------------
const TOKEN_KEY = "dcl_access_token";
const REFRESH_TOKEN_KEY = "dcl_refresh_token";
const WORKSHOP_KEY = "dcl_workshop";
// {type: "owner"|"employee", id, name, email} — ΠΟΙΟΣ ΣΥΓΚΕΚΡΙΜΕΝΑ συνδέθηκε
// (δες backend auth._issue_tokens). Ξεχωριστό από WORKSHOP_KEY: το workshop
// είναι πάντα τα στοιχεία της επιχείρησης, το actor είναι το πρόσωπο.
const ACTOR_KEY = "dcl_actor";

let onUnauthorized = null;
/** App.jsx καλεί αυτό μία φορά ώστε να ξέρει η api.js πώς να κάνει logout σε 401. */
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function getRefreshToken() {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

function setSession(accessToken, workshop, refreshToken, actor) {
  localStorage.setItem(TOKEN_KEY, accessToken);
  if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  if (workshop) localStorage.setItem(WORKSHOP_KEY, JSON.stringify(workshop));
  if (actor) localStorage.setItem(ACTOR_KEY, JSON.stringify(actor));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(WORKSHOP_KEY);
  localStorage.removeItem(ACTOR_KEY);
}

// Το access token λήγει κάθε 60 λεπτά (JWT_ACCESS_TOKEN_EXPIRES_MIN). Πριν
// υπήρχε ΜΟΝΟ logout σε κάθε 401 — το backend εξέδιδε refreshToken αλλά
// κανείς δεν το χρησιμοποιούσε. Τώρα σε 401 προσπαθούμε ΠΡΩΤΑ ανανέωση
// μέσω /api/auth/refresh και ξαναδοκιμάζουμε το αίτημα, οπότε ο χρήστης
// μένει συνδεδεμένος μέχρι να λήξει το refresh token (30 μέρες).
// `refreshPromise` μαζεύει ταυτόχρονα 401 σε ΕΝΑ μόνο /refresh call.
let refreshPromise = null;
function refreshAccessToken() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return Promise.resolve(false);
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_URL}/api/auth/refresh`, {
      method: "POST",
      headers: { Authorization: `Bearer ${refreshToken}` },
    })
      .then(async (res) => {
        if (!res.ok) return false;
        const data = await res.json();
        localStorage.setItem(TOKEN_KEY, data.accessToken);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

export function getStoredWorkshop() {
  const raw = localStorage.getItem(WORKSHOP_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/** Ενημερώνει το cached workshop (localStorage) μετά από αλλαγή στοιχείων
 * (π.χ. businessType) — ώστε η επόμενη φόρτωση να δείχνει τη σωστή ροή. */
export function setStoredWorkshop(workshop) {
  localStorage.setItem(WORKSHOP_KEY, JSON.stringify(workshop));
}

export function getStoredActor() {
  const raw = localStorage.getItem(ACTOR_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * Εσωτερικός helper για κλήσεις fetch με καθαρό error handling.
 * Επιστρέφει το parsed JSON ή πετάει Error με ελληνικό μήνυμα.
 */
async function request(path, { method = "GET", body, skipAuth = false, _retried = false } = {}) {
  const url = `${API_URL}${path}`;
  let response;

  const headers = body ? { "Content-Type": "application/json" } : {};
  const token = getToken();
  if (token && !skipAuth) headers["Authorization"] = `Bearer ${token}`;

  try {
    response = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (networkErr) {
    // Δίκτυο / server down
    throw new Error(
      `Αποτυχία σύνδεσης με τον server (${API_URL}). ` +
        `Βεβαιώσου ότι το backend τρέχει. (${networkErr.message})`
    );
  }

  // Έληξε το access token -> προσπάθησε ανανέωση ΜΙΑ φορά και ξαναδοκίμασε
  // το ίδιο αίτημα πριν αποδεχτείς ότι χρειάζεται πραγματικό logout.
  if (response.status === 401 && !skipAuth && !_retried) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return request(path, { method, body, skipAuth, _retried: true });
    }
  }

  // Προσπάθησε να διαβάσεις JSON (ακόμη κι όταν είναι error)
  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
  }

  if (response.status === 401 && !skipAuth) {
    clearSession();
    if (onUnauthorized) onUnauthorized();
  }

  if (!response.ok) {
    const message =
      (data && data.error) ||
      `Σφάλμα διακομιστή (HTTP ${response.status}). Δοκίμασε ξανά σε λίγο· αν επιμένει, ελέγξε τα logs του backend.`;
    throw new Error(message);
  }

  return data;
}

// ---- Auth ----
export async function register({ name, email, password, businessType, termsAccepted }) {
  const data = await request("/api/auth/register", {
    method: "POST",
    body: { name, email, password, businessType, termsAccepted },
    skipAuth: true,
  });
  setSession(data.accessToken, data.workshop, data.refreshToken, data.actor);
  return data;
}

export async function login({ email, password }) {
  const data = await request("/api/auth/login", {
    method: "POST",
    body: { email, password },
    skipAuth: true,
  });
  setSession(data.accessToken, data.workshop, data.refreshToken, data.actor);
  return data;
}

export function logout() {
  clearSession();
}

// ---- Υπάλληλοι (μόνο owner μπορεί να δημιουργήσει/επεξεργαστεί/σβήσει —
// δες backend auth.require_owner) ----
export function getEmployees() {
  return request("/api/employees");
}

export function createEmployee({ name, email, password }) {
  return request("/api/employees", {
    method: "POST",
    body: { name, email, password },
  });
}

export function updateEmployee(id, data) {
  return request(`/api/employees/${id}`, {
    method: "PATCH",
    body: data,
  });
}

export function deleteEmployee(id) {
  return request(`/api/employees/${id}`, { method: "DELETE" });
}

export function forgotPassword(email) {
  return request("/api/auth/forgot-password", {
    method: "POST",
    body: { email },
    skipAuth: true,
  });
}

export function resetPassword(token, password) {
  return request("/api/auth/reset-password", {
    method: "POST",
    body: { token, password },
    skipAuth: true,
  });
}

export function verifyEmail(token) {
  return request("/api/auth/verify-email", {
    method: "POST",
    body: { token },
    skipAuth: true,
  });
}

export function resendVerificationEmail() {
  return request("/api/auth/resend-verification", { method: "POST" });
}

// ---- Λογαριασμός — αλλαγή κωδικού / τύπου επιχείρησης ----
export function changePassword(currentPassword, newPassword) {
  return request("/api/auth/password", {
    method: "PUT",
    body: { currentPassword, newPassword },
  });
}

export function changeBusinessType(businessType) {
  return request("/api/auth/business-type", {
    method: "PUT",
    body: { businessType },
  });
}

// ---- Λογαριασμός — εξαγωγή δεδομένων / διαγραφή (GDPR) ----
export function exportAccountData() {
  return request("/api/account/export");
}

/**
 * Κατεβάζει το Excel του audit log (λογιστικός έλεγχος).
 *
 * ΔΕΝ περνά από το request() παραπάνω: εκείνο κάνει πάντα response.text() +
 * JSON.parse, που πάνω σε binary .xlsx θα κατέστρεφε το αρχείο. Εδώ
 * χρειάζεται response.blob(). Επιστρέφει {blob, filename}.
 */
export async function downloadAuditLogXlsx() {
  const path = "/api/audit-log/export.xlsx";
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(`${API_URL}${path}`, { headers });
  } catch (networkErr) {
    throw new Error(
      `Αποτυχία σύνδεσης με τον server (${API_URL}). ` +
        `Βεβαιώσου ότι το backend τρέχει. (${networkErr.message})`
    );
  }

  // Έληξε το access token -> ανανέωσε ΜΙΑ φορά και ξαναδοκίμασε, ίδια
  // σημασιολογία με το request().
  if (response.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      const retryHeaders = { Authorization: `Bearer ${getToken()}` };
      response = await fetch(`${API_URL}${path}`, { headers: retryHeaders });
    } else {
      clearSession();
      if (onUnauthorized) onUnauthorized();
    }
  }

  if (!response.ok) {
    // Σε σφάλμα το backend στέλνει JSON, όχι xlsx — διάβασέ το ως κείμενο
    // ώστε ο χρήστης να δει το πραγματικό μήνυμα αντί για «κατέβηκε αρχείο».
    let message = `Σφάλμα διακομιστή (HTTP ${response.status}).`;
    try {
      const data = JSON.parse(await response.text());
      if (data?.error) message = data.error;
    } catch {
      /* κράτα το γενικό μήνυμα */
    }
    throw new Error(message);
  }

  // Το όνομα αρχείου το ορίζει το backend (Content-Disposition) — κράτα το
  // ώστε να μη διαφωνούν τα δύο άκρα για την ημερομηνία στο όνομα.
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return {
    blob: await response.blob(),
    filename: match ? match[1] : "audit-log.xlsx",
  };
}

export function deleteAccount(password) {
  return request("/api/account", {
    method: "DELETE",
    body: { password },
  });
}

// ---- Health ----
export function getHealth() {
  return request("/api/health");
}

// ---- Ρυθμίσεις ΑΑΔΕ (credentials) ----
export function getSettings() {
  return request("/api/settings");
}

export function updateSettings({
  aade_username,
  aade_subscription_key,
  branch,
  entity_vat_number,
}) {
  return request("/api/settings", {
    method: "PUT",
    body: { aade_username, aade_subscription_key, branch, entity_vat_number },
  });
}

// Έλεγχος σύνδεσης ΑΑΔΕ (ελαφριά κλήση)
export function testConnection() {
  return request("/api/settings/test-connection", { method: "POST" });
}

// Live/Mock switch — ενεργοποίηση πραγματικής ΑΑΔΕ για το δικό μας workshop
export function setAadeLiveMode(forceReal) {
  return request("/api/settings/aade-mode", {
    method: "PUT",
    body: { forceReal },
  });
}

// Reconciliation — σύγκριση τοπικής εγγραφής με την ΑΑΔΕ
export function reconcileEntry(entry_id) {
  return request(`/api/dcl/reconcile/${entry_id}`);
}

// Εισαγωγή εγγραφών που υπάρχουν στην ΑΑΔΕ αλλά όχι ακόμα τοπικά
export function importFromAade() {
  return request("/api/dcl/import-from-aade", { method: "POST" });
}

// Επαναποστολή — η εγγραφή είναι αποθηκευμένη αλλά ο τελευταίος Χρόνος δεν
// επιβεβαιώθηκε από την ΑΑΔΕ (π.χ. έπεσε το internet).
// Το backend ελέγχει ΠΡΩΤΑ τι ξέρει ήδη η ΑΑΔΕ: αν η καταχώρηση υπάρχει,
// απλώς συγχρονίζει (resendResult="already_recorded") αντί να τη διπλασιάσει.
export function resendEntry(entry_id) {
  return request(`/api/dcl/entries/${entry_id}/resend`, { method: "POST" });
}

// Έλεγχος στην ΑΑΔΕ — όταν η προηγούμενη αποστολή δεν πήρε σαφή απάντηση
// (aadeState="indeterminate"), η επαναποστολή μπλοκάρεται γιατί η εγγραφή
// μπορεί να έχει ήδη καταχωρηθεί. Αυτό απαντά «καταχωρήθηκε ή όχι;» και
// είτε συνδέει την υπάρχουσα εγγραφή είτε ξεμπλοκάρει την επαναποστολή.
export function verifyEntry(entry_id) {
  return request(`/api/dcl/entries/${entry_id}/verify`, { method: "POST" });
}

// ---- 1ος Χρόνος — SendClient ----
// Το branch έρχεται πλέον ΑΠΟ ΤΙΣ ΡΥΘΜΙΣΕΙΣ στο backend (όχι από εδώ).
// vehicleMovementPurpose/isDiffVehPickupLocation/vehiclePickupLocation:
// ΜΟΝΟ για Ενοικιάσεις (αγνοούνται από το backend για Συνεργεία).
export function createEntry({
  plate,
  customerName,
  vat,
  vehicleCategory,
  vehicleFactory,
  comments,
  vehicleMovementPurpose,
  isDiffVehPickupLocation,
  vehiclePickupLocation,
  rentalExpectedDays,
}) {
  return request("/api/dcl/entry", {
    method: "POST",
    body: {
      plate,
      customerName,
      vat,
      vehicleCategory,
      vehicleFactory,
      comments,
      vehicleMovementPurpose,
      isDiffVehPickupLocation,
      vehiclePickupLocation,
      rentalExpectedDays,
    },
  });
}

// ---- 2ος Χρόνος — UpdateClient (κατηγορία υπηρεσίας) ----
export function addService({
  entry_id,
  providedServiceCategory,
  providedServiceCategoryOther,
  comments,
}) {
  return request("/api/dcl/service", {
    method: "POST",
    body: {
      entry_id,
      providedServiceCategory,
      providedServiceCategoryOther,
      comments,
    },
  });
}

// ---- 3ος Χρόνος — UpdateClient (entryCompletion) ----
// amount/isDiffVehReturnLocation/vehicleReturnLocation: ΜΟΝΟ για Ενοικιάσεις.
export function completeExit({
  entry_id,
  invoiceKind,
  reasonNonIssueType,
  amount,
  isDiffVehReturnLocation,
  vehicleReturnLocation,
}) {
  return request("/api/dcl/exit", {
    method: "POST",
    body: {
      entry_id,
      invoiceKind,
      reasonNonIssueType,
      amount,
      isDiffVehReturnLocation,
      vehicleReturnLocation,
    },
  });
}

// ---- 4ος Χρόνος — ClientCorrelations (ΜΑΡΚ) ----
export function correlateMark({ entry_id, mark }) {
  return request("/api/dcl/correlate", {
    method: "POST",
    body: { entry_id, mark },
  });
}

// ---- CancelClient ----
export function cancelEntry({ entry_id }) {
  return request("/api/dcl/cancel", {
    method: "POST",
    body: { entry_id },
  });
}

// ---- Μετρικές OCR (πόσο καλά δουλεύει η αναγνώριση πινακίδας) ----
// Fire-and-forget από το CameraCapture — ΠΟΤΕ δεν πρέπει να μπλοκάρει ή να
// σπάσει τη ροή σάρωσης/δημιουργίας εγγραφής αν αποτύχει.
export function logOcrAttempt({
  mode,
  engine,
  ocrPlate,
  confidence,
  warningsCount,
  parserCorrected,
}) {
  return request("/api/ocr/metrics", {
    method: "POST",
    body: { mode, engine, ocrPlate, confidence, warningsCount, parserCorrected },
  });
}

export function confirmOcrMetric(id, finalPlate) {
  return request(`/api/ocr/metrics/${id}`, {
    method: "PATCH",
    body: { finalPlate },
  });
}

export function getOcrMetricsSummary() {
  return request("/api/ocr/metrics/summary");
}

export function getOcrMetrics(limit = 50) {
  return request(`/api/ocr/metrics?limit=${limit}`);
}

// ---- Βάση Πελατών/Οχημάτων ----
export function getCustomers(q = "") {
  const qs = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
  return request(`/api/customers${qs}`);
}

// Ελαφριά εκδοχή (μόνο plate/name) — για το "μήπως εννοείς" στο
// CameraCapture, που φορτώνει σε κάθε άνοιγμα κάμερας.
export function getCustomerPlates() {
  return request("/api/customers/plates");
}

export function updateCustomer(id, { name, vat, phone }) {
  return request(`/api/customers/${id}`, {
    method: "PATCH",
    body: { name, vat, phone },
  });
}

// ---- Στόλος οχημάτων (μόνο Ενοικιάσεις) ----
export function getFleetVehicles() {
  return request("/api/fleet-vehicles");
}

export function createFleetVehicle({ plate, label, category }) {
  return request("/api/fleet-vehicles", {
    method: "POST",
    body: { plate, label, category },
  });
}

export function updateFleetVehicle(id, { plate, label, category }) {
  return request(`/api/fleet-vehicles/${id}`, {
    method: "PATCH",
    body: { plate, label, category },
  });
}

export function deleteFleetVehicle(id) {
  return request(`/api/fleet-vehicles/${id}`, { method: "DELETE" });
}

// ---- Λίστα / λεπτομέρειες ----
export function getEntries() {
  return request("/api/dcl/entries");
}

export function getEntry(id) {
  return request(`/api/dcl/entries/${id}`);
}

export { API_URL };
