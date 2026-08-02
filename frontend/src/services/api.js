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
const WORKSHOP_KEY = "dcl_workshop";

let onUnauthorized = null;
/** App.jsx καλεί αυτό μία φορά ώστε να ξέρει η api.js πώς να κάνει logout σε 401. */
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setSession(accessToken, workshop) {
  localStorage.setItem(TOKEN_KEY, accessToken);
  if (workshop) localStorage.setItem(WORKSHOP_KEY, JSON.stringify(workshop));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(WORKSHOP_KEY);
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

/**
 * Εσωτερικός helper για κλήσεις fetch με καθαρό error handling.
 * Επιστρέφει το parsed JSON ή πετάει Error με ελληνικό μήνυμα.
 */
async function request(path, { method = "GET", body, skipAuth = false } = {}) {
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
export async function register({ name, email, password, businessType }) {
  const data = await request("/api/auth/register", {
    method: "POST",
    body: { name, email, password, businessType },
    skipAuth: true,
  });
  setSession(data.accessToken, data.workshop);
  return data;
}

export async function login({ email, password }) {
  const data = await request("/api/auth/login", {
    method: "POST",
    body: { email, password },
    skipAuth: true,
  });
  setSession(data.accessToken, data.workshop);
  return data;
}

export function logout() {
  clearSession();
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

// Reconciliation — σύγκριση τοπικής εγγραφής με την ΑΑΔΕ
export function reconcileEntry(entry_id) {
  return request(`/api/dcl/reconcile/${entry_id}`);
}

// Επαναποστολή — η εγγραφή είναι αποθηκευμένη αλλά ο τελευταίος Χρόνος δεν
// επιβεβαιώθηκε από την ΑΑΔΕ (π.χ. έπεσε το internet).
export function resendEntry(entry_id) {
  return request(`/api/dcl/entries/${entry_id}/resend`, { method: "POST" });
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

// ---- Λίστα / λεπτομέρειες ----
export function getEntries() {
  return request("/api/dcl/entries");
}

export function getEntry(id) {
  return request(`/api/dcl/entries/${id}`);
}

export { API_URL };
