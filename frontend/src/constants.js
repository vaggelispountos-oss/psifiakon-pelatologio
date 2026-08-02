// constants.js
// Σταθερές τιμές που αντιστοιχούν στους κωδικούς της ΑΑΔΕ.

// Τύπος επιχείρησης — επιλέγεται ΜΙΑ φορά στην εγγραφή, καθορίζει ποιο
// clientServiceType ΑΑΔΕ (και ποια ροή/πεδία) χρησιμοποιεί όλη η εφαρμογή.
export const BUSINESS_TYPES = [
  {
    value: "garage",
    icon: "🔧",
    label: "Συνεργείο Αυτοκινήτων",
    description: "Επισκευές/service — 4 Χρόνοι ΑΑΔΕ με κατηγορία εργασίας.",
  },
  {
    value: "rental",
    icon: "🚗",
    label: "Ενοικίαση Οχημάτων",
    description: "Αυτοκίνητα/μηχανάκια — παραλαβή/επιστροφή & συμφωνηθέν ποσό.",
  },
];

// Σκοπός Κίνησης Οχήματος (1ος Χρόνος, ΜΟΝΟ Ενοικιάσεις) — δες
// backend/aade_specs/.../SimpleTypes-v1.1.xsd: VehicleMovementPurposeType,
// xs:int 1-3. ⚠️ Το XSD ορίζει μόνο το εύρος τιμών χωρίς ετικέτες ανά κωδικό
// — οι ετικέτες παρακάτω είναι ΠΡΟΣΩΡΙΝΕΣ, όπως και με τα
// REASON_NON_ISSUE_TYPES. Επιβεβαίωσε την ΑΚΡΙΒΗ διατύπωση από τις επίσημες
// τεχνικές προδιαγραφές του Ψηφιακού Πελατολογίου πριν τη χρήση σε production.
export const VEHICLE_MOVEMENT_PURPOSES = [
  { value: 1, label: "Κωδικός 1" },
  { value: 2, label: "Κωδικός 2" },
  { value: 3, label: "Κωδικός 3" },
];

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

// Ενοικιάσεις: ΔΕΝ έχουν 2ο Χρόνο (κατηγορία υπηρεσίας) — 3 Χρόνοι αντί για 4.
export const STATUS_LABELS_RENTAL = {
  ...STATUS_LABELS,
  completed: { text: "Ολοκληρωμένη (2ος Χρόνος)", color: "#7c3aed" },
  correlated: { text: "Συσχετισμένη (3ος Χρόνος)", color: "#16a34a" },
};

export function serviceCategoryLabel(value) {
  const found = SERVICE_CATEGORIES.find((c) => c.value === Number(value));
  return found ? found.label : "-";
}

export function invoiceKindLabel(value) {
  const found = INVOICE_KINDS.find((c) => c.value === Number(value));
  return found ? found.label : "-";
}
