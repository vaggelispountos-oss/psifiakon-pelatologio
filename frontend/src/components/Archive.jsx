// components/Archive.jsx
// Ενοποιεί 3 πρώην top-level tabs (Πελάτες / Ιστορικό / Οχήματα) σε ΕΝΑ tab
// με εσωτερικό segmented control — ο χρήστης δεν χρειάζεται να ξέρει ΕΚ ΤΩΝ
// ΠΡΟΤΕΡΩΝ ποιο από τα τρία δείχνει τι για να βρει το σωστό. Το `view`/
// `onViewChange` είναι ελεγχόμενα από το App.jsx ώστε το «Λεπτομέρειες» στο
// tab «Εγγραφές» να μπορεί να ανοίξει κατευθείαν στο Ιστορικό.
import CustomerDatabase from "./CustomerDatabase";
import HistoryLog from "./HistoryLog";
import FleetVehicles from "./FleetVehicles";

const VIEWS = [
  { id: "customers", label: "Πελάτες" },
  { id: "history", label: "Ιστορικό" },
  { id: "fleet", label: "Οχήματα", rentalOnly: true },
];

export default function Archive({ view, onViewChange, entries, loading, onRefresh, isRental }) {
  const views = VIEWS.filter((v) => !v.rentalOnly || isRental);
  const active = views.some((v) => v.id === view) ? view : views[0].id;

  return (
    <>
      <div className="segmented archive-segmented" role="tablist" aria-label="Αρχείο">
        {views.map((v) => (
          <button
            key={v.id}
            type="button"
            className={`segmented-btn${active === v.id ? " is-active" : ""}`}
            onClick={() => onViewChange(v.id)}
          >
            {v.label}
          </button>
        ))}
      </div>

      {active === "customers" && (
        <CustomerDatabase entries={entries} loading={loading} onRefresh={onRefresh} />
      )}
      {active === "history" && (
        <HistoryLog entries={entries} loading={loading} onRefresh={onRefresh} />
      )}
      {active === "fleet" && isRental && <FleetVehicles entries={entries} />}
    </>
  );
}
