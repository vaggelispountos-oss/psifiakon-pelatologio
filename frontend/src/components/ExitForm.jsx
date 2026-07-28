// components/ExitForm.jsx
// 3ος Χρόνος — Ολοκλήρωση (Είδος Παραστατικού) -> entryCompletion.
// Εναλλακτικά του invoiceKind, ο χρήστης μπορεί να δηλώσει ότι ΔΕΝ εκδόθηκε
// παραστατικό (reasonNonIssueType) — π.χ. εργασία εγγύησης χωρίς χρέωση.
import { useState } from "react";
import { INVOICE_KINDS, REASON_NON_ISSUE_TYPES } from "../constants";

export default function ExitForm({ onSubmit, disabled }) {
  const [noInvoice, setNoInvoice] = useState(false);
  const [invoiceKind, setInvoiceKind] = useState("");
  const [reasonNonIssueType, setReasonNonIssueType] = useState("");
  const [error, setError] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (noInvoice) {
      if (!reasonNonIssueType) {
        setError("Επίλεξε αιτιολογία μη έκδοσης παραστατικού.");
        return;
      }
      onSubmit({ reasonNonIssueType: Number(reasonNonIssueType) });
      return;
    }

    if (!invoiceKind) {
      setError("Επίλεξε είδος παραστατικού.");
      return;
    }

    onSubmit({ invoiceKind: Number(invoiceKind) });
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>3ος Χρόνος — Ολοκλήρωση</h2>
      <p className="muted">
        Επίλεξε το είδος παραστατικού και ολοκλήρωσε την εργασία. Η ΑΑΔΕ
        επιστρέφει την ώρα ολοκλήρωσης.
      </p>

      <label className="field-label field-checkbox">
        <input
          type="checkbox"
          checked={noInvoice}
          onChange={(e) => {
            setNoInvoice(e.target.checked);
            setError("");
          }}
        />
        Δεν εκδίδεται παραστατικό
      </label>

      {noInvoice ? (
        <label className="field-label">
          Αιτιολογία Μη Έκδοσης:
          <select
            className="input"
            value={reasonNonIssueType}
            onChange={(e) => setReasonNonIssueType(e.target.value)}
          >
            <option value="">— Επίλεξε —</option>
            {REASON_NON_ISSUE_TYPES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.value} — {r.label}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <label className="field-label">
          Είδος Παραστατικού:
          <select
            className="input"
            value={invoiceKind}
            onChange={(e) => setInvoiceKind(e.target.value)}
          >
            <option value="">— Επίλεξε —</option>
            {INVOICE_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.value} — {k.label}
              </option>
            ))}
          </select>
        </label>
      )}

      {error && <div className="alert alert-error">{error}</div>}

      <button className="btn btn-primary btn-block" disabled={disabled}>
        Ολοκλήρωση (UpdateClient / entryCompletion)
      </button>
    </form>
  );
}
