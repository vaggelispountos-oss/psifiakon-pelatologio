// components/OcrStats.jsx
// --------------------------------------------------------------------
// Στατιστικά αναγνώρισης πινακίδας (OCR) — πόσο καλά δουλεύει στην πράξη.
// Δεδομένα από το backend (OcrMetric): μία γραμμή ανά σάρωση, ενημερωμένη
// με το τελικό αποτέλεσμα όταν ο χρήστης πατήσει «Δημιουργία εγγραφής».
// --------------------------------------------------------------------
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { getOcrMetrics, getOcrMetricsSummary } from "../services/api";

function fmt(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("el-GR");
  } catch {
    return iso;
  }
}

function Stat({ value, label, color }) {
  return (
    <div className="counter">
      <span className="counter-num" style={color ? { color } : undefined}>
        {value}
      </span>
      <span className="counter-lbl">{label}</span>
    </div>
  );
}

export default function OcrStats() {
  const queryClient = useQueryClient();
  const [summaryQuery, recentQuery] = useQueries({
    queries: [
      { queryKey: ["ocrMetricsSummary"], queryFn: getOcrMetricsSummary, placeholderData: (p) => p },
      { queryKey: ["ocrMetrics", 30], queryFn: () => getOcrMetrics(30), placeholderData: (p) => p },
    ],
  });
  const summary = summaryQuery.data || null;
  const recent = recentQuery.data || [];
  const loading = summaryQuery.isFetching || recentQuery.isFetching;
  const error = summaryQuery.error?.message || recentQuery.error?.message || "";

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["ocrMetricsSummary"] });
    queryClient.invalidateQueries({ queryKey: ["ocrMetrics", 30] });
  }

  return (
    <div className="card">
      <div className="list-header">
        <h2>Στατιστικά OCR πινακίδας</h2>
        <button className="btn btn-ghost btn-sm" onClick={refresh}>
          ↻ Ανανέωση
        </button>
      </div>
      <p className="muted">
        Πόσο καλά δουλεύει η αναγνώριση πινακίδας στην πράξη — μία γραμμή ανά
        σάρωση («Σκάναρε»), ενημερωμένη με το τελικό αποτέλεσμα όταν πατηθεί
        «Δημιουργία εγγραφής». Χρησιμοποίησε αυτά τα νούμερα για να κρίνεις αν
        χρειάζεται αναβάθμιση στο ALPR API.
      </p>

      {loading && <p className="muted">Φόρτωση…</p>}
      {error && <div className="alert alert-error">{error}</div>}

      {summary && summary.total === 0 && (
        <p className="muted">
          Δεν υπάρχουν σαρώσεις ακόμη — σκάναρε μερικές πινακίδες και ξανάρθε
          εδώ.
        </p>
      )}

      {summary && summary.total > 0 && (
        <>
          <div className="counters">
            <Stat value={summary.total} label="Σαρώσεις" />
            <Stat
              value={`${summary.successRate ?? "—"}%`}
              label="Ποσοστό επιτυχίας"
              color={
                summary.successRate >= 70
                  ? "#4ade80"
                  : summary.successRate >= 40
                  ? "#d97706"
                  : "#f87171"
              }
            />
            <Stat value={summary.failures} label="Αποτυχίες" color="#f87171" />
          </div>

          <div className="counters">
            <Stat
              value={summary.userEdited}
              label="Χειροκίνητες διορθώσεις"
              color="#d97706"
            />
            <Stat
              value={summary.userEditedRate != null ? `${summary.userEditedRate}%` : "—"}
              label="Ποσοστό διόρθωσης"
            />
            <Stat
              value={summary.avgConfidence != null ? `${summary.avgConfidence}%` : "—"}
              label="Μέση βεβαιότητα"
            />
          </div>

          <div className="ocr-info" style={{ marginTop: 4 }}>
            <span className="muted small">
              Ανά μηχανή:{" "}
              {Object.entries(summary.byEngine)
                .map(([k, v]) => `${k} (${v})`)
                .join(" · ")}
            </span>
            <span className="muted small">
              Ανά τύπο οχήματος:{" "}
              {Object.entries(summary.byMode)
                .map(([k, v]) => `${k} (${v})`)
                .join(" · ")}
            </span>
            <span className="muted small">
              Ο parser χρειάστηκε να «μαντέψει» τη μορφή σε {summary.parserCorrected}{" "}
              σαρώσεις.
            </span>
          </div>
        </>
      )}

      {recent.length > 0 && (
        <>
          <h3 style={{ marginTop: 20 }}>Τελευταίες σαρώσεις</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Ώρα</th>
                  <th>Τύπος</th>
                  <th>Μηχανή</th>
                  <th>OCR πρότεινε</th>
                  <th>Τελικό</th>
                  <th>Βεβαιότητα</th>
                  <th>Διορθώθηκε;</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((r) => (
                  <tr key={r.id}>
                    <td className="muted small">{fmt(r.createdAt)}</td>
                    <td>{r.mode === "car" ? "🚗" : "🏍️"}</td>
                    <td className="muted small">{r.engine}</td>
                    <td className="mono">{r.ocrPlate || "—"}</td>
                    <td className="mono">{r.finalPlate || "—"}</td>
                    <td>{r.confidence != null ? `${r.confidence}%` : "—"}</td>
                    <td>
                      {!r.confirmed
                        ? "—"
                        : r.userEdited
                        ? "✏️ Ναι"
                        : "✅ Όχι"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
