// components/HistoryLog.jsx
// Ιστορικό — χρονολογική ροή εγγραφών με τους 4 Χρόνους τους.
// Κλικ σε εγγραφή -> φόρτωση των AadeLogs (audit) από το backend.
import { useState } from "react";
import { getEntry } from "../services/api";
import { STATUS_LABELS, serviceCategoryLabel, invoiceKindLabel } from "../constants";

function fmt(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("el-GR");
  } catch {
    return iso;
  }
}

export default function HistoryLog({ entries, loading, onRefresh }) {
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailErr, setDetailErr] = useState("");

  async function toggle(id) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(id);
    setDetail(null);
    setDetailErr("");
    try {
      const d = await getEntry(id);
      setDetail(d);
    } catch (err) {
      setDetailErr(err.message);
    }
  }

  const sorted = [...entries].sort(
    (a, b) => new Date(b.createdAt) - new Date(a.createdAt)
  );

  return (
    <div className="card">
      <div className="list-header">
        <h2>Ιστορικό & Audit ΑΑΔΕ</h2>
        <button className="btn btn-ghost btn-sm" onClick={onRefresh}>
          ↻ Ανανέωση
        </button>
      </div>
      <p className="muted">
        ΟΛΕΣ οι επισκέψεις σε χρονολογική σειρά (νεότερη πρώτα). Άνοιξε μία
        για να δεις τους 4 Χρόνους της ΑΑΔΕ και τις ακριβείς κλήσεις
        (audit log) που έγιναν γι' αυτήν.
      </p>

      {loading && <p className="muted">Φόρτωση…</p>}
      {!loading && sorted.length === 0 && (
        <p className="muted">Δεν υπάρχει ιστορικό ακόμη.</p>
      )}

      <div className="history">
        {sorted.map((e) => {
          const s = STATUS_LABELS[e.status] || { text: e.status };
          return (
            <div key={e.id} className="history-item">
              <button className="history-head" onClick={() => toggle(e.id)}>
                <span className="mono">{e.plate}</span>
                <span className="muted">{s.text}</span>
                <span className="muted small">{fmt(e.createdAt)}</span>
              </button>

              {openId === e.id && (
                <div className="history-body">
                  {detailErr && (
                    <div className="alert alert-error">{detailErr}</div>
                  )}
                  {!detail && !detailErr && <p className="muted">Φόρτωση…</p>}
                  {detail && (
                    <>
                      <ul className="timeline">
                        <li>
                          <b>1ος Χρόνος:</b> idDcl {detail.idDcl || "—"} ·{" "}
                          {fmt(detail.creationDateTime)}
                        </li>
                        <li>
                          <b>2ος Χρόνος:</b>{" "}
                          {detail.providedServiceCategory
                            ? serviceCategoryLabel(detail.providedServiceCategory)
                            : "—"}
                        </li>
                        <li>
                          <b>3ος Χρόνος:</b>{" "}
                          {detail.completionDateTime
                            ? `${invoiceKindLabel(detail.invoiceKind)} · ${fmt(
                                detail.completionDateTime
                              )}`
                            : "—"}
                        </li>
                        <li>
                          <b>4ος Χρόνος:</b> ΜΑΡΚ {detail.mark || "—"}
                          {detail.correlateId
                            ? ` · correlateId ${detail.correlateId}`
                            : ""}
                        </li>
                      </ul>

                      <details className="raw-qr">
                        <summary>
                          Κλήσεις ΑΑΔΕ (audit) — {detail.logs?.length || 0}
                        </summary>
                        <ul className="log-list">
                          {(detail.logs || []).map((l) => (
                            <li key={l.id}>
                              <span className={l.success ? "ok" : "fail"}>
                                {l.success ? "✓" : "✗"}
                              </span>{" "}
                              <b>{l.method}</b> · {fmt(l.createdAt)}
                            </li>
                          ))}
                        </ul>
                      </details>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
