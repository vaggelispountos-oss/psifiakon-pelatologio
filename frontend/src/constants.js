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

// Κατηγορία οχήματος στόλου (μόνο Ενοικιάσεις, τοπικό πεδίο — ΔΕΝ πάει στην
// ΑΑΔΕ). Χρησιμοποιείται για ομαδοποίηση στη λίστα επιλογής οχήματος.
export const VEHICLE_CATEGORIES = [
  { value: "car", icon: "🚗", label: "Αμάξια" },
  { value: "motorcycle", icon: "🏍️", label: "Μηχανάκια" },
  { value: "atv", icon: "🛺", label: "Γουρούνες (ATV/Buggy)" },
  { value: "bicycle", icon: "🚲", label: "Ποδήλατα" },
  { value: "ebike", icon: "🔋", label: "Ηλεκτρικά Ποδήλατα" },
  { value: "other", icon: "🚙", label: "Άλλο" },
];

// Σκοπός Κίνησης Οχήματος (1ος Χρόνος, ΜΟΝΟ Ενοικιάσεις) — επίσημες τιμές
// από το «Ψηφιακό Πελατολόγιο ΑΑΔΕ — Τεχνική Περιγραφή Διεπαφών REST API»
// (DCL API Documentation v1.0, §5.1.1, σελ. 18: πεδίο vehicleMovementPurpose).
export const VEHICLE_MOVEMENT_PURPOSES = [
  { value: 1, label: "Ενοικίαση" },
  { value: 2, label: "Ιδιόχρηση" },
  { value: 3, label: "Δωρεάν Υπηρεσία" },
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

// Αιτιολογία Μη Έκδοσης Παραστατικού (3ος Χρόνος, εναλλακτικά του invoiceKind)
// — επίσημες τιμές από το «Ψηφιακό Πελατολόγιο ΑΑΔΕ — Τεχνική Περιγραφή
// Διεπαφών REST API» (DCL API Documentation v1.0, §5, σελ. 8: πεδίο
// reasonNonIssueType). Και οι 3 τιμές ισχύουν για Ενοικιάσεις — η 3η
// ("Αποζημίωση Παροχής Εγγύησης") αφορά ΜΟΝΟ Συνεργεία στο πρωτότυπο, αλλά
// αφήνεται εδώ γιατί το backend/XSD δεν κάνει διάκριση ανά business_type.
export const REASON_NON_ISSUE_TYPES = [
  { value: 1, label: "Δωρεάν Υπηρεσία" },
  { value: 2, label: "Ιδιόχρηση" },
  { value: 3, label: "Αποζημίωση Παροχής Εγγύησης" },
];

// Ετικέτες κατάστασης (status) εγγραφής — απλή, κατανοητή γλώσσα (ο αριθμός
// του «Χρόνου» ΑΑΔΕ φαίνεται μόνο στο Stepper και στο tab «Ιστορικό»).
export const STATUS_LABELS = {
  open: { text: "Μπήκε", color: "#2563eb" },
  in_progress: { text: "Σε εξέλιξη", color: "#d97706" },
  completed: { text: "Ολοκληρωμένη", color: "#7c3aed" },
  correlated: { text: "Συσχετισμένη", color: "#16a34a" },
  cancelled: { text: "Ακυρωμένη", color: "#6b7280" },
};

// Ενοικιάσεις: ΔΕΝ έχουν 2ο Χρόνο (κατηγορία υπηρεσίας) — 3 Χρόνοι αντί για 4.
// Το "open" σημαίνει «το όχημα είναι έξω», όχι «μπήκε».
export const STATUS_LABELS_RENTAL = {
  ...STATUS_LABELS,
  open: { text: "Έξω", color: "#2563eb" },
  completed: { text: "Επιστράφηκε", color: "#7c3aed" },
  correlated: { text: "Συσχετισμένη", color: "#16a34a" },
};

export function serviceCategoryLabel(value) {
  const found = SERVICE_CATEGORIES.find((c) => c.value === Number(value));
  return found ? found.label : "-";
}

export function invoiceKindLabel(value) {
  const found = INVOICE_KINDS.find((c) => c.value === Number(value));
  return found ? found.label : "-";
}
