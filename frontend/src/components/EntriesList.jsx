// components/EntriesList.jsx
// --------------------------------------------------------------------
// ΚΕΝΤΡΙΚΟ σημείο εργασίας: όλα τα οχήματα, ομαδοποιημένα ανά στάδιο.
// Κάθε όχημα είναι ΑΝΕΞΑΡΤΗΤΟ (δικό του idDcl + status) — κάθε ενέργεια
// αναφέρεται ρητά στο entry_id του. Δεν υπάρχει «τρέχον όχημα» global state.
// --------------------------------------------------------------------
import { useEffect, useMemo, useRef, useState } from "react";
import { STATUS_LABELS, STATUS_LABELS_RENTAL } from "../constants";
import { reconcileEntry, importFromAade } from "../services/api";

// Καταστάσεις που η ΑΑΔΕ θεωρεί ήδη οριστικές — δεν χρειάζεται να τις
// ξαναρωτάμε σε κάθε άνοιγμα του tab.
const AUTOSYNC_SKIP_STATUSES = new Set(["cancelled", "correlated"]);

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

// Ελληνικά labels για το τι άλλαξε στο "Έλεγχος με ΑΑΔΕ" (reconcile)
const RECON_FIELD_LABELS = {
  creationDateTime: "ώρα δημιουργίας",
  completionDateTime: "ώρα ολοκλήρωσης",
  providedServiceCategory: "κατηγορία υπηρεσίας",
  providedServiceCategoryOther: "περιγραφή κατηγορίας",
  invoiceKind: "είδος παραστατικού",
  status: "κατάσταση",
  mark: "ΜΑΡΚ",
  correlateId: "συσχέτιση",
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
  const [autoSyncing, setAutoSyncing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);

  // Μετρητές ανά στάδιο
  const counts = useMemo(() => {
    const c = { open: 0, in_progress: 0, completed: 0, correlated: 0, cancelled: 0 };
    for (const e of entries) if (e.status in c) c[e.status] += 1;
    return c;
  }, [entries]);

  // Ενοικιάσεις που καθυστερούν να επιστραφούν (δηλώθηκαν για Χ μέρες, έχουν
  // περάσει, το όχημα είναι ακόμη "open").
  const overdue = useMemo(
    () => entries.filter((e) => e.isOverdue),
    [entries]
  );

  const filtered = useMemo(() => {
    const q = search.trim().toUpperCase();
    return entries.filter((e) => {
      if (filter !== "all" && e.status !== filter) return false;
      if (q && !e.plate.toUpperCase().includes(q)) return false;
      return true;
    });
  }, [entries, filter, search]);

  // Κάνει reconcile ΕΝΑ entry· επιστρέφει true αν άλλαξε κάτι τοπικά.
  // Δεν καλεί onRefresh() μόνο του — το auto-sync το κάνει ΜΙΑ φορά στο
  // τέλος για όλα, ώστε να μη γίνονται πολλαπλά ταυτόχρονα refresh.
  async function doReconcile(entry) {
    setRecon((r) => ({ ...r, [entry.id]: { loading: true } }));
    try {
      const result = await reconcileEntry(entry.id);
      setRecon((r) => ({ ...r, [entry.id]: { loading: false, result } }));
      return !!(result.updated && result.updated.length > 0);
    } catch (err) {
      setRecon((r) => ({
        ...r,
        [entry.id]: { loading: false, result: { ok: false, reason: err.message } },
      }));
      return false;
    }
  }

  async function handleReconcile(entry) {
    const changed = await doReconcile(entry);
    if (changed) onRefresh();
  }

  // Αυτόματος συγχρονισμός ΜΙΑ φορά κάθε φορά που ανοίγει το tab
  // «Εγγραφές» — πιάνει αλλαγές που έγιναν αλλού (π.χ. απευθείας στο
  // back-office της ΑΑΔΕ ή από λογισμικό λογιστή) χωρίς να χρειάζεται
  // χειροκίνητο «Έλεγχος με ΑΑΔΕ» ανά εγγραφή.
  const autoSyncedRef = useRef(false);
  useEffect(() => {
    if (autoSyncedRef.current || loading) return;
    if (!entries || entries.length === 0) return;
    autoSyncedRef.current = true;

    const toSync = entries.filter(
      (e) => e.idDcl && !AUTOSYNC_SKIP_STATUSES.has(e.status)
    );
    if (toSync.length === 0) return;

    setAutoSyncing(true);
    Promise.all(toSync.map(doReconcile))
      .then((results) => {
        if (results.some(Boolean)) onRefresh();
      })
      .finally(() => setAutoSyncing(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries, loading]);

  // Εισαγωγή εγγραφών που υπάρχουν στην ΑΑΔΕ αλλά όχι ακόμα τοπικά (π.χ.
  // καταχωρήθηκαν απευθείας στο back-office της ΑΑΔΕ, ή πριν συνδεθεί η
  // εφαρμογή). Χειροκίνητο — δεν τρέχει αυτόματα, γιατί μπορεί να διαβάσει
  // πολλές σελίδες δεδομένων από την ΑΑΔΕ.
  async function handleImport() {
    if (
      !window.confirm(
        "Εισαγωγή εγγραφών από την ΑΑΔΕ; Θα δημιουργηθούν τοπικά αντίγραφα " +
          "για όσες εγγραφές υπάρχουν στο Ψηφιακό Πελατολόγιο αλλά λείπουν " +
          "από αυτή τη λίστα. Μπορεί να πάρει λίγα δευτερόλεπτα."
      )
    ) {
      return;
    }
    setImporting(true);
    setImportResult(null);
    try {
      const result = await importFromAade();
      setImportResult(result);
      if (result.imported > 0) onRefresh();
    } catch (err) {
      setImportResult({ ok: false, reason: err.message });
    } finally {
      setImporting(false);
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
    const updatedLabels = (r.updated || []).map((f) => RECON_FIELD_LABELS[f] || f);
    return (
      <span className="conn-ok small">
        ✅ Ταιριάζει με ΑΑΔΕ{matched ? "" : " (μερικώς)"}
        {updatedLabels.length > 0
          ? ` · ενημερώθηκε από ΑΑΔΕ: ${updatedLabels.join(", ")}`
          : ""}
      </span>
    );
  }

  return (
    <div className="card">
      <div className="list-header">
        <h2>Εγγραφές — Ενεργές εργασίες</h2>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="btn btn-ghost btn-sm"
            onClick={handleImport}
            disabled={importing}
          >
            {importing ? "Εισαγωγή…" : "⬇️ Εισαγωγή από ΑΑΔΕ"}
          </button>
          <button className="btn btn-ghost btn-sm" onClick={onRefresh}>
            ↻ Ανανέωση
          </button>
        </div>
      </div>
      <p className="muted">
        Ό,τι χρειάζεται δράση ΤΩΡΑ — μία γραμμή ανά επίσκεψη οχήματος, με
        κουμπί για το επόμενο βήμα. (Για ιστορικό ή στατιστικά ανά πελάτη,
        δες τα tabs «Πελάτες» και «Ιστορικό».) Το «Εισαγωγή από ΑΑΔΕ» φέρνει
        εγγραφές που υπάρχουν στο Ψηφιακό Πελατολόγιο αλλά όχι ακόμα εδώ.
      </p>

      {overdue.length > 0 && (
        <div className="alert alert-warn">
          ⏰ {overdue.length} {overdue.length === 1 ? "ενοικίαση καθυστερεί" : "ενοικιάσεις καθυστερούν"} να επιστραφούν:{" "}
          {overdue
            .map(
              (e) =>
                `${e.plate} (${e.overdueDays} ${e.overdueDays === 1 ? "μέρα" : "μέρες"})`
            )
            .join(", ")}
        </div>
      )}

      {importResult && (
        <div
          className={`alert ${
            importResult.ok === false ? "alert-error" : "alert-info"
          }`}
        >
          {importResult.mock
            ? `ℹ️ ${importResult.message}`
            : importResult.ok === false
            ? `❌ ${importResult.reason}`
            : `✅ Εισήχθησαν ${importResult.imported} νέες εγγραφές (παραλείφθηκαν ${importResult.skipped} που υπήρχαν ήδη).`}
        </div>
      )}

      {autoSyncing && (
        <div className="alert alert-info small">
          <span className="spinner" aria-label="συγχρονισμός" /> Συγχρονισμός
          με ΑΑΔΕ… (πιάνει αλλαγές που έγιναν από αλλού, π.χ. λογιστικό
          λογισμικό ή απευθείας στην ΑΑΔΕ)
        </div>
      )}

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
                  {e.isOverdue && (
                    <span className="badge badge-warn">
                      ⏰ Καθυστερεί {e.overdueDays}{" "}
                      {e.overdueDays === 1 ? "μέρα" : "μέρες"}
                    </span>
                  )}
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
