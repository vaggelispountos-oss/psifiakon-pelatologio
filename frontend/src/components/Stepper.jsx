// components/Stepper.jsx
// Δείχνει σε ποιο βήμα της ροής βρίσκεται η ενεργή εγγραφή — αντικαθιστά τα
// «1ος/2ος/3ος Χρόνος» μέσα στους τίτλους των φορμών με μια οπτική γραμμή
// προόδου, ώστε ο χρήστης να μη χρειάζεται να ξέρει την ορολογία ΑΑΔΕ.
const GARAGE_STEPS = ["Είσοδος", "Εργασία", "Απόδειξη", "ΜΑΡΚ"];
const RENTAL_STEPS = ["Παράδοση", "Επιστροφή", "ΜΑΡΚ"];

// Δείκτης του βήματος που είναι ΤΩΡΑ ενεργό, με βάση το status της εγγραφής.
// Χωρίς ενεργή εγγραφή (δεν έχει δημιουργηθεί ακόμα) -> βήμα 0.
function stepIndex(status, isRental) {
  if (isRental) {
    switch (status) {
      case "open":
        return 1; // περιμένει επιστροφή
      case "completed":
        return 2; // περιμένει ΜΑΡΚ
      case "correlated":
        return 3; // όλα ολοκληρωμένα
      default:
        return 0;
    }
  }
  switch (status) {
    case "open":
      return 1; // περιμένει κατηγορία εργασίας
    case "in_progress":
      return 2; // περιμένει απόδειξη
    case "completed":
      return 3; // περιμένει ΜΑΡΚ
    case "correlated":
      return 4; // όλα ολοκληρωμένα
    default:
      return 0;
  }
}

export default function Stepper({ status, isRental }) {
  const steps = isRental ? RENTAL_STEPS : GARAGE_STEPS;
  const current = stepIndex(status, isRental);

  return (
    <div className="stepper" role="list" aria-label="Πρόοδος εγγραφής">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <div
            key={label}
            role="listitem"
            className={`stepper-step${done ? " is-done" : ""}${
              active ? " is-active" : ""
            }`}
          >
            <span className="stepper-dot">{done ? "✓" : i + 1}</span>
            <span className="stepper-label">{label}</span>
            {i < steps.length - 1 && <span className="stepper-line" />}
          </div>
        );
      })}
    </div>
  );
}
