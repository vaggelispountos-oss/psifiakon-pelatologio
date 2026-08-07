// components/RentalTodayPanel.jsx
// Η πρώτη ερώτηση κάθε πρωί σε ένα γραφείο ενοικιάσεων: «ποια οχήματα
// γυρνάνε σήμερα, και ποια άργησαν;». Πριν, αυτό ήταν θαμμένο σε ένα alert
// μέσα στο tab «Εγγραφές» — εδώ είναι η πρώτη κάρτα που βλέπει ο χρήστης
// μόλις ανοίξει την εφαρμογή. Εμφανίζεται μόνο όταν υπάρχει κάτι να δείξει
// (καθυστερεί ή γυρνάει σήμερα) — αλλιώς δεν προσθέτει θόρυβο.
import { useMemo } from "react";

function isSameLocalDay(isoString, reference) {
  const d = new Date(isoString);
  return (
    d.getFullYear() === reference.getFullYear() &&
    d.getMonth() === reference.getMonth() &&
    d.getDate() === reference.getDate()
  );
}

export default function RentalTodayPanel({ entries, onAct }) {
  const { overdue, dueToday, outCount } = useMemo(() => {
    const now = new Date();
    const openEntries = (entries || []).filter((e) => e.status === "open");
    return {
      overdue: openEntries.filter((e) => e.isOverdue),
      dueToday: openEntries.filter(
        (e) => !e.isOverdue && e.expectedReturnAt && isSameLocalDay(e.expectedReturnAt, now)
      ),
      outCount: openEntries.length,
    };
  }, [entries]);

  if (overdue.length === 0 && dueToday.length === 0) return null;

  return (
    <div className="card today-panel">
      {overdue.length > 0 && (
        <>
          <h2 className="today-panel-title today-panel-title-danger">
            ⏰ Άργησαν να επιστραφούν ({overdue.length})
          </h2>
          <div className="today-panel-list">
            {overdue.map((e) => (
              <div key={e.id} className="today-panel-row today-panel-row-danger">
                <div>
                  <span className="mono">{e.plate}</span>
                  <span className="today-panel-days">
                    {e.overdueDays} {e.overdueDays === 1 ? "μέρα" : "μέρες"} καθυστέρηση
                  </span>
                </div>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => onAct(e, "exit")}
                >
                  Επιστροφή
                </button>
              </div>
            ))}
          </div>
        </>
      )}

      {dueToday.length > 0 && (
        <>
          <h2 className="today-panel-title">
            📅 Επιστρέφουν σήμερα ({dueToday.length})
          </h2>
          <div className="today-panel-list">
            {dueToday.map((e) => (
              <div key={e.id} className="today-panel-row">
                <span className="mono">{e.plate}</span>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => onAct(e, "exit")}
                >
                  Επιστροφή
                </button>
              </div>
            ))}
          </div>
        </>
      )}

      <p className="muted small today-panel-footer">
        {outCount} {outCount === 1 ? "όχημα σε ενοικίαση" : "οχήματα σε ενοικίαση"} συνολικά.
      </p>
    </div>
  );
}
