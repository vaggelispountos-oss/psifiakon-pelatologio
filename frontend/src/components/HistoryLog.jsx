// components/HistoryLog.jsx
// Ιστορικό — χρονολογική ροή εγγραφών με τους 4 Χρόνους τους.
// Κλικ σε εγγραφή -> φόρτωση των AadeLogs (audit) από το backend.
import { useState } from "react";
import { getEntry, resendEntry, verifyEntry } from "../services/api";
import {
  STATUS_LABELS,
  STATUS_LABELS_RENTAL,
  serviceCategoryLabel,
  invoiceKindLabel,
} from "../constants";

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
  // Μήνυμα αποτελέσματος από επαναποστολή/έλεγχο — σημαντικό να φαίνεται,
  // γιατί το «δεν στάλθηκε ξανά, υπήρχε ήδη» είναι ΔΙΑΦΟΡΕΤΙΚΟ αποτέλεσμα
  // από το «στάλθηκε», και ο χρήστης πρέπει να ξέρει ποιο από τα δύο έγινε.
  const [actionMsg, setActionMsg] = useState("");

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
    setActionMsg("");
    try {
      const d = await getEntry(id);
      setDetail(d);
    } catch (err) {
      setDetailErr(err.message);
    }
  }

  /** Κοινή εκτέλεση για «Επαναποστολή» και «Έλεγχος στην ΑΑΔΕ» — ίδιος
   *  χειρισμός κατάστασης/σφάλματος, διαφορετική κλήση. */
  async function runAction(id, fn, messageKey) {
    setResending(true);
    setResendErr("");
    setActionMsg("");
    try {
      const updated = await fn(id);
      setDetail((prev) => (prev ? { ...prev, ...updated } : updated));
      setActionMsg(updated[messageKey] || "");
      onRefresh();
    } catch (err) {
      setResendErr(err.message);
    } finally {
      setResending(false);
    }
  }

  const handleResend = (id) => runAction(id, resendEntry, "resendMessage");
  const handleVerify = (id) => runAction(id, verifyEntry, "verificationMessage");

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
          const labels = e.clientServiceType === 1 ? STATUS_LABELS_RENTAL : STATUS_LABELS;
          const s = labels[e.status] || { text: e.status };
          return (
            <div key={e.id} className="history-item">
              <button className="history-head" onClick={() => toggle(e.id)}>
                <span className="mono">{e.plate}</span>
                <span className="muted">{s.text}</span>
                {/* Η άγνωστη έκβαση δείχνεται ΞΕΧΩΡΙΣΤΑ (και όταν δεν υπάρχει
                    pendingAction, π.χ. αποτυχημένη ακύρωση): απαιτεί άλλη
                    ενέργεια από τον χρήστη — έλεγχο, όχι επαναποστολή. */}
                {e.aadeState === "indeterminate" ? (
                  <span
                    className="badge badge-warn"
                    title="Η ΑΑΔΕ δεν απάντησε — μπορεί να έχει ήδη καταχωρηθεί. Άνοιξε την εγγραφή για έλεγχο."
                  >
                    ⚠️ Χρειάζεται έλεγχος
                  </span>
                ) : (
                  e.pendingAction && (
                    <span className="badge badge-warn" title={PENDING_LABELS[e.pendingAction]}>
                      ⏳ Εκκρεμεί επιβεβαίωση
                    </span>
                  )
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
                      {/* Άγνωστη έκβαση: η ΑΑΔΕ ΜΠΟΡΕΙ να έχει ήδη
                          καταχωρήσει. Η επαναποστολή είναι μπλοκαρισμένη στο
                          backend (409) — η μόνη σωστή ενέργεια είναι ο
                          έλεγχος, αλλιώς κινδυνεύει διπλή εγγραφή. */}
                      {detail.aadeState === "indeterminate" && (
                        <div className="alert alert-warn">
                          <p>
                            ⚠️ Η αποστολή ({PENDING_LABELS[detail.pendingAction] ||
                              "τελευταίος Χρόνος"}) δεν πήρε σαφή απάντηση από
                            την ΑΑΔΕ. Η εγγραφή <b>μπορεί να έχει ήδη
                            καταχωρηθεί</b> — μην ξαναστείλεις πριν γίνει
                            έλεγχος, γιατί θα δημιουργηθεί διπλή εγγραφή.
                          </p>
                          {resendErr && <p className="alert-error">{resendErr}</p>}
                          {actionMsg && <p className="ok">{actionMsg}</p>}
                          <button
                            className="btn btn-primary btn-sm"
                            disabled={resending}
                            onClick={() => handleVerify(detail.id)}
                          >
                            {resending ? "Έλεγχος…" : "🔍 Έλεγχος στην ΑΑΔΕ"}
                          </button>
                        </div>
                      )}

                      {detail.pendingAction && detail.aadeState !== "indeterminate" && (
                        <div className="alert alert-warn">
                          <p>⏳ {PENDING_LABELS[detail.pendingAction]}. Η εγγραφή
                            είναι αποθηκευμένη τοπικά — πάτησε «Επαναποστολή»
                            για να ξαναδοκιμάσεις (π.χ. αν έπεσε το internet).
                            Γίνεται πρώτα έλεγχος στην ΑΑΔΕ, ώστε να μη
                            σταλεί κάτι που έχει ήδη καταχωρηθεί.</p>
                          {resendErr && <p className="alert-error">{resendErr}</p>}
                          {actionMsg && <p className="ok">{actionMsg}</p>}
                          <button
                            className="btn btn-primary btn-sm"
                            disabled={resending}
                            onClick={() => handleResend(detail.id)}
                          >
                            {resending ? "Αποστολή…" : "↻ Επαναποστολή"}
                          </button>
                        </div>
                      )}

                      {detail.clientServiceType === 1 ? (
                        // Ενοικιάσεις — 3 Χρόνοι (χωρίς κατηγορία υπηρεσίας)
                        <ul className="timeline">
                          <li>
                            <StepMark ok={!!detail.idDcl} />{" "}
                            <b>1ος Χρόνος:</b> idDcl {detail.idDcl || "—"} ·{" "}
                            {fmt(detail.creationDateTime)}
                            {detail.vehiclePickupLocation
                              ? ` · παραλαβή: ${detail.vehiclePickupLocation}`
                              : ""}
                          </li>
                          <li>
                            <StepMark ok={!!detail.completionDateTime} />{" "}
                            <b>2ος Χρόνος (Ολοκλήρωση):</b>{" "}
                            {detail.completionDateTime
                              ? `${invoiceKindLabel(detail.invoiceKind)} · ${
                                  detail.amount != null ? `${detail.amount}€ · ` : ""
                                }${fmt(detail.completionDateTime)}`
                              : "—"}
                            {detail.vehicleReturnLocation
                              ? ` · επιστροφή: ${detail.vehicleReturnLocation}`
                              : ""}
                          </li>
                          <li>
                            <StepMark ok={!!detail.correlateId} />{" "}
                            <b>3ος Χρόνος:</b> ΜΑΡΚ {detail.mark || "—"}
                            {detail.correlateId
                              ? ` · correlateId ${detail.correlateId}`
                              : ""}
                          </li>
                        </ul>
                      ) : (
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
                      )}

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
