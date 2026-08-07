// components/ExitForm.jsx
// 3ος Χρόνος — Ολοκλήρωση (Είδος Παραστατικού) -> entryCompletion.
// Εναλλακτικά του invoiceKind, ο χρήστης μπορεί να δηλώσει ότι ΔΕΝ εκδόθηκε
// παραστατικό (reasonNonIssueType) — π.χ. εργασία εγγύησης χωρίς χρέωση.
import { useState } from "react";
import { INVOICE_KINDS, REASON_NON_ISSUE_TYPES } from "../constants";

export default function ExitForm({ onSubmit, disabled, isRental }) {
  const [noInvoice, setNoInvoice] = useState(false);
  const [invoiceKind, setInvoiceKind] = useState("");
  const [reasonNonIssueType, setReasonNonIssueType] = useState("");
  const [amount, setAmount] = useState("");
  const [diffReturnLocation, setDiffReturnLocation] = useState(false);
  const [returnLocation, setReturnLocation] = useState("");
  const [error, setError] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (isRental && diffReturnLocation && !returnLocation.trim()) {
      setError("Συμπλήρωσε τον τόπο επιστροφής.");
      return;
    }

    // Προαιρετικό ανά ΑΑΔΕ spec — π.χ. σε Ιδιόχρηση/Δωρεάν Υπηρεσία δεν
    // υπάρχει συμφωνηθέν ποσό να δηλωθεί.
    const rentalExtra = isRental
      ? {
          amount: amount.trim() ? Number(amount) : null,
          isDiffVehReturnLocation: diffReturnLocation,
          vehicleReturnLocation: diffReturnLocation ? returnLocation.trim() : null,
        }
      : {};

    if (noInvoice) {
      if (!reasonNonIssueType) {
        setError("Επίλεξε αιτιολογία μη έκδοσης παραστατικού.");
        return;
      }
      onSubmit({ reasonNonIssueType: Number(reasonNonIssueType), ...rentalExtra });
      return;
    }

    if (!invoiceKind) {
      setError("Επίλεξε είδος παραστατικού.");
      return;
    }

    onSubmit({ invoiceKind: Number(invoiceKind), ...rentalExtra });
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>{isRental ? "2ος Χρόνος — Ολοκλήρωση Ενοικίασης" : "3ος Χρόνος — Ολοκλήρωση"}</h2>
      <p className="muted">
        {isRental
          ? "Επίλεξε είδος παραστατικού (ή «Δεν εκδίδεται παραστατικό» για Ιδιόχρηση/Δωρεάν Υπηρεσία) για να ολοκληρωθεί η ενοικίαση."
          : "Επίλεξε το είδος παραστατικού και ολοκλήρωσε την εργασία."}{" "}
        Η ΑΑΔΕ επιστρέφει την ώρα ολοκλήρωσης.
      </p>

      {isRental && (
        <>
          <label className="field-label">
            Συμφωνηθέν Ποσό (€) — προαιρετικό:
            <input
              className="input"
              type="number"
              min="0"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="π.χ. 45.00"
            />
          </label>

          <label className="field-label field-checkbox">
            <input
              type="checkbox"
              checked={diffReturnLocation}
              onChange={(e) => setDiffReturnLocation(e.target.checked)}
            />
            Διαφορετικός τόπος επιστροφής οχήματος
          </label>

          {diffReturnLocation && (
            <label className="field-label">
              Τόπος Επιστροφής:
              <input
                className="input"
                type="text"
                value={returnLocation}
                onChange={(e) => setReturnLocation(e.target.value)}
                placeholder="π.χ. Αεροδρόμιο Ηρακλείου"
              />
            </label>
          )}
        </>
      )}

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
