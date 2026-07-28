// components/CustomerDatabase.jsx
// Βάση Πελατών/Οχημάτων — ομαδοποίηση των εγγραφών ανά πινακίδα.
// Τα δεδομένα έρχονται ΑΠΟ ΤΟ BACKEND (όχι localStorage).
import { STATUS_LABELS } from "../constants";

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("el-GR");
  } catch {
    return iso;
  }
}

export default function CustomerDatabase({ entries, loading, onRefresh }) {
  // Ομαδοποίηση ανά πινακίδα
  const byPlate = {};
  for (const e of entries) {
    if (!byPlate[e.plate]) {
      byPlate[e.plate] = { plate: e.plate, count: 0, last: e };
    }
    byPlate[e.plate].count += 1;
    // κράτα την πιο πρόσφατη
    if (new Date(e.createdAt) > new Date(byPlate[e.plate].last.createdAt)) {
      byPlate[e.plate].last = e;
    }
  }
  const rows = Object.values(byPlate).sort((a, b) =>
    a.plate.localeCompare(b.plate)
  );

  return (
    <div className="card">
      <div className="list-header">
        <h2>Βάση Πελατών / Οχημάτων</h2>
        <button className="btn btn-ghost btn-sm" onClick={onRefresh}>
          ↻ Ανανέωση
        </button>
      </div>
      <p className="muted">
        ΜΙΑ γραμμή ανά πινακίδα (όχι ανά επίσκεψη) — πόσες φορές έχει έρθει
        κάθε όχημα και ποια η τελευταία του κατάσταση. Για τις επιμέρους
        επισκέψεις του, δες το tab «Ιστορικό».
      </p>

      {loading && <p className="muted">Φόρτωση…</p>}
      {!loading && rows.length === 0 && (
        <p className="muted">Δεν υπάρχουν πελάτες/οχήματα ακόμη.</p>
      )}

      <div className="table-wrap">
        {rows.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Πινακίδα</th>
                <th>Επισκέψεις</th>
                <th>Τελευταία κατάσταση</th>
                <th>Τελευταία εγγραφή</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const s = STATUS_LABELS[r.last.status] || {
                  text: r.last.status,
                };
                return (
                  <tr key={r.plate}>
                    <td className="mono">{r.plate}</td>
                    <td>{r.count}</td>
                    <td>{s.text}</td>
                    <td>{formatDate(r.last.createdAt)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
