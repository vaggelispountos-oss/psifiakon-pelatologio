// components/HistoryLog.jsx
// Ιστορικό — χρονολογική ροή εγγραφών με τους 4 Χρόνους τους.
// Κλικ σε εγγραφή -> φόρτωση των AadeLogs (audit) από το backend.
import { useState } from "react";
import { getEntry, resendEntry } from "../services/api";
import { STATUS_LABELS, serviceCategoryLabel, invoiceKindLabel } from "../constants";

function fmt(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("el-GR");
  } catch {
    return iso;
  }
}

const PENDING_LABELS = {
  entry: "1ος Χρόνος (δημιουργία) δεν έχει επιβεβαιωθεί από την ΑΑΔΕ",
  service: "2ος Χρόνος (υπηρεσία) δεν έχει επιβεβαιωθεί από την ΑΑΔΕ",
  exit: "3ος Χρόνος (ολοκλήρωση) δεν έχει επιβεβαιωθεί από την ΑΑΔΕ",
  correlate: "4ος Χρόνος (ΜΑΡΚ) δεν έχει επιβεβαιωθεί από την ΑΑΔΕ",
};

function StepMark({ ok }) {
  return (
    <span className={ok ? "ok" : "muted"} title={ok ? "Επιβεβαιωμένο από ΑΑΔΕ" : "Εκκρεμεί"}>
      {ok ? "✓" : "⏳"}
    </span>
  );
}

export default function HistoryLog({ entries, loading, onRefresh }) {
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailErr, setDetailErr] = useState("");
  const [resending, setResending] = useState(false);
  const [resendErr, setResendErr] = useState("");

  async function toggle(id) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(id);
    setDetail(null);
    setDetailErr("");
    setResendErr("");
    try {
      const d = await getEntry(id);
      setDetail(d);
    } catch (err) {
      setDetailErr(err.message);
    }
  }

  async function handleResend(id) {
    setResending(true);
    setResendErr("");
    try {
      const updated = await resendEntry(id);
      setDetail((prev) => (prev ? { ...prev, ...updated } : updated));
      onRefresh();
    } catch (err) {
      setResendErr(err.message);
    } finally {
      setResending(false);
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
                {e.pendingAction && (
                  <span className="badge badge-warn" title={PENDING_LABELS[e.pendingAction]}>
                    ⏳ Εκκρεμεί επιβεβαίωση
                  </span>
                )}
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
                      {detail.pendingAction && (
                        <div className="alert alert-warn">
                          <p>⏳ {PENDING_LABELS[detail.pendingAction]}. Η εγγραφή
                            είναι αποθηκευμένη τοπικά — πάτησε «Επαναποστολή»
                            για να ξαναδοκιμάσεις (π.χ. αν έπεσε το internet).</p>
                          {resendErr && <p className="alert-error">{resendErr}</p>}
                          <button
                            className="btn btn-primary btn-sm"
                            disabled={resending}
                            onClick={() => handleResend(detail.id)}
                          >
                            {resending ? "Αποστολή…" : "↻ Επαναποστολή"}
                          </button>
                        </div>
                      )}

                      <ul className="timeline">
                        <li>
                          <StepMark ok={!!detail.idDcl} />{" "}
                          <b>1ος Χρόνος:</b> idDcl {detail.idDcl || "—"} ·{" "}
                          {fmt(detail.creationDateTime)}
                        </li>
                        <li>
                          <StepMark
                            ok={
                              !!detail.providedServiceCategory &&
                              detail.pendingAction !== "service"
                            }
                          />{" "}
                          <b>2ος Χρόνος:</b>{" "}
                          {detail.providedServiceCategory
                            ? serviceCategoryLabel(detail.providedServiceCategory)
                            : "—"}
                        </li>
                        <li>
                          <StepMark ok={!!detail.completionDateTime} />{" "}
                          <b>3ος Χρόνος:</b>{" "}
                          {detail.completionDateTime
                            ? `${invoiceKindLabel(detail.invoiceKind)} · ${fmt(
                                detail.completionDateTime
                              )}`
                            : "—"}
                        </li>
                        <li>
                          <StepMark ok={!!detail.correlateId} />{" "}
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
