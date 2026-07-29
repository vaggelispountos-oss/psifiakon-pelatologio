// components/ContactSupport.jsx
// --------------------------------------------------------------------
// Στοιχεία επικοινωνίας με τον πάροχο/developer της εφαρμογής.
// --------------------------------------------------------------------
const SUPPORT_EMAIL = "vaggelispountos@gmail.com";

export default function ContactSupport() {
  return (
    <div className="contact">
      <p className="muted">
        Βρήκες bug, θέλεις βοήθεια με κάτι που δεν λύθηκε από τον οδηγό
        σφαλμάτων, ή χρειάζεσαι ενεργοποίηση συνδρομής; Στείλε μας email —
        απαντάμε άμεσα.
      </p>
      <a className="btn btn-primary btn-block" href={`mailto:${SUPPORT_EMAIL}`}>
        {SUPPORT_EMAIL}
      </a>
      <p className="muted small">
        Βοηθάει πολύ αν επισυνάψεις screenshot του σφάλματος και πεις τι
        έκανες τη στιγμή που εμφανίστηκε.
      </p>
    </div>
  );
}
