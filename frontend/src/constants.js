// constants.js
// Σταθερές τιμές που αντιστοιχούν στους κωδικούς της ΑΑΔΕ.

// Κατηγορία Παρεχόμενης Υπηρεσίας (2ος Χρόνος)
// ΠΡΟΣΟΧΗ: οι τιμές/κωδικοί πρέπει να ταιριάζουν ΑΚΡΙΒΩΣ με την ΑΑΔΕ.
export const SERVICE_CATEGORIES = [
  { value: 1, label: "Εργασία με χρήση ανταλλακτικών" },
  { value: 2, label: "Εργασία με ανταλλακτικά που φέρνει ο πελάτης" },
  { value: 3, label: "Εργασία χωρίς ανταλλακτικά" },
  { value: 9, label: "Ιδιόχρηση" },
  { value: 4, label: "Δωρεάν υπηρεσία" },
  { value: 6, label: "Αποζημίωση παροχής εγγύησης" },
  { value: 5, label: "Λοιπά" },
];

// Η κατηγορία που απαιτεί ελεύθερο κείμενο (υποχρεωτικό)
export const SERVICE_CATEGORY_OTHER = 5;

// Είδος Παραστατικού (3ος Χρόνος)
export const INVOICE_KINDS = [
  { value: 1, label: "ΑΛΠ / ΑΠΥ" },
  { value: 2, label: "Τιμολόγιο" },
  { value: 3, label: "ΑΛΠ / ΑΠΥ - ΦΗΜ" },
];

// Αιτιολογία Μη Έκδοσης Παραστατικού (3ος Χρόνος, εναλλακτικά του invoiceKind
// — δες backend/aade_specs/.../SimpleTypes-v1.1.xsd: ReasonNonIssueType, xs:int 1-3).
// ⚠️ Το XSD ορίζει μόνο το εύρος τιμών (1-3) χωρίς ετικέτες ανά κωδικό — οι
// ετικέτες παρακάτω είναι ΠΡΟΣΩΡΙΝΕΣ. Επιβεβαίωσε την ΑΚΡΙΒΗ διατύπωση από τις
// επίσημες τεχνικές προδιαγραφές του Ψηφιακού Πελατολογίου (myDATA) πριν τη
// χρήση σε production, όπως και με τα SERVICE_CATEGORIES/INVOICE_KINDS.
export const REASON_NON_ISSUE_TYPES = [
  { value: 1, label: "Κωδικός 1" },
  { value: 2, label: "Κωδικός 2" },
  { value: 3, label: "Κωδικός 3" },
];

// Ετικέτες κατάστασης (status) εγγραφής + σε ποιον «Χρόνο» αντιστοιχεί
export const STATUS_LABELS = {
  open: { text: "Ανοιχτή (1ος Χρόνος)", color: "#2563eb" },
  in_progress: { text: "Σε εξέλιξη (2ος Χρόνος)", color: "#d97706" },
  completed: { text: "Ολοκληρωμένη (3ος Χρόνος)", color: "#7c3aed" },
  correlated: { text: "Συσχετισμένη (4ος Χρόνος)", color: "#16a34a" },
  cancelled: { text: "Ακυρωμένη", color: "#6b7280" },
};

export function serviceCategoryLabel(value) {
  const found = SERVICE_CATEGORIES.find((c) => c.value === Number(value));
  return found ? found.label : "-";
}

export function invoiceKindLabel(value) {
  const found = INVOICE_KINDS.find((c) => c.value === Number(value));
  return found ? found.label : "-";
}
