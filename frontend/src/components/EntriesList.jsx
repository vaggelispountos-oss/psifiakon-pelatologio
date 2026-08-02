// components/EntriesList.jsx
// --------------------------------------------------------------------
// ΚΕΝΤΡΙΚΟ σημείο εργασίας: όλα τα οχήματα, ομαδοποιημένα ανά στάδιο.
// Κάθε όχημα είναι ΑΝΕΞΑΡΤΗΤΟ (δικό του idDcl + status) — κάθε ενέργεια
// αναφέρεται ρητά στο entry_id του. Δεν υπάρχει «τρέχον όχημα» global state.
// --------------------------------------------------------------------
import { useMemo, useState } from "react";
import { STATUS_LABELS, STATUS_LABELS_RENTAL } from "../constants";
import { reconcileEntry } from "../services/api";

// Επόμενο βήμα ανά status. Ενοικιάσεις δεν έχουν 2ο Χρόνο — από "open" πάνε
// κατευθείαν σε Ολοκλήρωση.
const NEXT_ACTION = {
  open: { label: "Πρόσθεσε εργασία", stage: "service" },
  in_progress: { label: "Ολοκλήρωση", stage: "exit" },
  completed: { label: "Σκάναρε ΜΑΡΚ", stage: "correlate" },
};
const NEXT_ACTION_RENTAL = {
  ...NEXT_ACTION,
  open: { label: "Ολοκλήρωση", stage: "exit" },
};

// Φίλτρα σταδίων
const FILTERS = [
  { id: "all", label: "Όλα" },
  { id: "open", label: "Ανοιχτά" },
  { id: "in_progress", label: "Σε εξέλιξη" },
  { id: "completed", label: "Προς ΜΑΡΚ" },
  { id: "correlated", label: "Ολοκληρωμένα" },
];

function StatusBadge({ status, isRental }) {
  const labels = isRental ? STATUS_LABELS_RENTAL : STATUS_LABELS;
  const s = labels[status] || { text: status, color: "#6b7280" };
  return (
    <span className="badge" style={{ backgroundColor: s.color }}>
      {s.text}
    </span>
  );
}

export default function EntriesList({
  entries,
  loading,
  onAct,
  onRefresh,
  onNewVehicle,
  isRental,
}) {
  const nextActionMap = isRental ? NEXT_ACTION_RENTAL : NEXT_ACTION;
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [recon, setRecon] = useState({}); // {entryId: {loading, result}}

  // Μετρητές ανά στάδιο
  const counts = useMemo(() => {
    const c = { open: 0, in_progress: 0, completed: 0, correlated: 0, cancelled: 0 };
    for (const e of entries) if (e.status in c) c[e.status] += 1;
    return c;
  }, [entries]);

  const filtered = useMemo(() => {
    const q = search.trim().toUpperCase();
    return entries.filter((e) => {
      if (filter !== "all" && e.status !== filter) return false;
      if (q && !e.plate.toUpperCase().includes(q)) return false;
      return true;
    });
  }, [entries, filter, search]);

  async function handleReconcile(entry) {
    setRecon((r) => ({ ...r, [entry.id]: { loading: true } }));
    try {
      const result = await reconcileEntry(entry.id);
      setRecon((r) => ({ ...r, [entry.id]: { loading: false, result } }));
      if (result.updated && result.updated.length > 0) onRefresh();
    } catch (err) {
      setRecon((r) => ({
        ...r,
        [entry.id]: { loading: false, result: { ok: false, reason: err.message } },
      }));
    }
  }

  function reconLine(entry) {
    const st = recon[entry.id];
    if (!st) return null;
    if (st.loading) return <span className="muted small">Έλεγχος ΑΑΔΕ…</span>;
    const r = st.result;
    if (r.mock) return <span className="muted small">ℹ️ {r.message}</span>;
    if (!r.ok) return <span className="conn-fail small">❌ {r.reason}</span>;
    const matched = r.matches && r.matches.idDcl;
    return (
      <span className="conn-ok small">
        ✅ Ταιριάζει με ΑΑΔΕ{matched ? "" : " (μερικώς)"}
        {r.updated && r.updated.length > 0
          ? ` · ενημερώθηκαν: ${r.updated.join(", ")}`
          : ""}
      </span>
    );
  }

  return (
    <div className="card">
      <div className="list-header">
        <h2>Εγγραφές — Ενεργές εργασίες</h2>
        <button className="btn btn-ghost btn-sm" onClick={onRefresh}>
          ↻ Ανανέωση
        </button>
      </div>
      <p className="muted">
        Ό,τι χρειάζεται δράση ΤΩΡΑ — μία γραμμή ανά επίσκεψη οχήματος, με
        κουμπί για το επόμενο βήμα. (Για ιστορικό ή στατιστικά ανά πελάτη,
        δες τα tabs «Πελάτες» και «Ιστορικό».)
      </p>

      {onNewVehicle && (
        <button className="btn btn-primary btn-block" onClick={onNewVehicle}>
          ＋ Νέο όχημα (νέος πελάτης)
        </button>
      )}

      {/* Μετρητές εκκρεμοτήτων */}
      <div className="counters">
        <div className="counter">
          <span className="counter-num">{counts.open}</span>
          <span className="counter-lbl">Ανοιχτά</span>
        </div>
        <div className="counter">
          <span className="counter-num">{counts.in_progress}</span>
          <span className="counter-lbl">Σε εξέλιξη</span>
        </div>
        <div className="counter">
          <span className="counter-num">{counts.completed}</span>
          <span className="counter-lbl">Προς ΜΑΡΚ</span>
        </div>
      </div>

      {/* Αναζήτηση ανά πλάκα */}
      <input
        className="input"
        type="text"
        placeholder="🔍 Αναζήτηση πλάκας…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {/* Φίλτρα σταδίων */}
      <div className="filters">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            className={`chip ${filter === f.id ? "chip-active" : ""}`}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && <p className="muted">Φόρτωση…</p>}
      {!loading && filtered.length === 0 && (
        <p className="muted">Δεν υπάρχουν εγγραφές σε αυτό το φίλτρο.</p>
      )}

      <div className="entries">
        {filtered.map((e) => {
          const next = nextActionMap[e.status];
          return (
            <div key={e.id} className="entry-row">
              <div className="entry-main">
                <div className="entry-plate">{e.plate}</div>
                <div className="entry-meta">
                  <StatusBadge status={e.status} isRental={isRental} />
                  <span className="mono">{e.idDcl || "—"}</span>
                </div>
                <div className="entry-recon">{reconLine(e)}</div>
              </div>
              <div className="entry-actions">
                {next && (
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => onAct(e, next.stage)}
                  >
                    {next.label}
                  </button>
                )}
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => handleReconcile(e)}
                  disabled={recon[e.id]?.loading}
                >
                  Έλεγχος με ΑΑΔΕ
                </button>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => onAct(e, "details")}
                >
                  Λεπτομέρειες
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
