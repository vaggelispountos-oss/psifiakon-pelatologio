// components/AccountPrivacy.jsx
// --------------------------------------------------------------------
// «Ο λογαριασμός & τα δεδομένα μου» — αυτοεξυπηρέτηση GDPR: εξαγωγή όλων
// των δεδομένων του workshop (portability) και οριστική διαγραφή λογαριασμού
// (erasure). Δες backend: GET /api/account/export, DELETE /api/account.
// --------------------------------------------------------------------
import { useState } from "react";
import {
  exportAccountData,
  deleteAccount,
  changePassword,
  changeBusinessType,
} from "../services/api";

function openLegalPage(path) {
  return (e) => {
    e.preventDefault();
    window.open(path, "_blank", "noopener,noreferrer");
  };
}

function ChangePasswordForm() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setOk("");
    setSaving(true);
    try {
      await changePassword(currentPassword, newPassword);
      setOk("Ο κωδικός άλλαξε.");
      setCurrentPassword("");
      setNewPassword("");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="alert alert-info">
      <b>Αλλαγή κωδικού.</b>
      <form onSubmit={handleSubmit} style={{ marginTop: "10px" }}>
        <label className="field-label">
          Τρέχων κωδικός:
          <input
            type="password"
            className="input"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <label className="field-label">
          Νέος κωδικός (τουλάχιστον 8 χαρακτήρες):
          <input
            type="password"
            className="input"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            autoComplete="new-password"
            minLength={8}
            required
          />
        </label>
        {error && <div className="alert alert-error">{error}</div>}
        {ok && <div className="alert alert-info">{ok}</div>}
        <button type="submit" className="btn btn-sm" disabled={saving}>
          {saving ? "Αποθήκευση…" : "Αλλαγή κωδικού"}
        </button>
      </form>
    </div>
  );
}

function BusinessTypeForm({ workshop, onWorkshopUpdated }) {
  const [businessType, setBusinessType] = useState(workshop?.businessType || "garage");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setOk("");
    if (businessType === (workshop?.businessType || "garage")) return;
    setSaving(true);
    try {
      const updated = await changeBusinessType(businessType);
      if (onWorkshopUpdated) onWorkshopUpdated(updated);
      setOk("Ο τύπος επιχείρησης άλλαξε.");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="alert alert-info">
      <b>Τύπος επιχείρησης.</b> Καθορίζει ποια ροή/πεδία ΑΑΔΕ χρησιμοποιούνται
      για ΝΕΕΣ εγγραφές — δεν αλλάζει ήδη υπάρχουσες εγγραφές.
      <form onSubmit={handleSubmit} style={{ marginTop: "10px" }}>
        <label className="field-label">
          <select
            className="input"
            value={businessType}
            onChange={(e) => setBusinessType(e.target.value)}
          >
            <option value="garage">🔧 Συνεργείο Αυτοκινήτων</option>
            <option value="rental">🚗 Ενοικίαση Οχημάτων</option>
          </select>
        </label>
        {error && <div className="alert alert-error">{error}</div>}
        {ok && <div className="alert alert-info">{ok}</div>}
        <button
          type="submit"
          className="btn btn-sm"
          disabled={saving || businessType === (workshop?.businessType || "garage")}
        >
          {saving ? "Αποθήκευση…" : "Αλλαγή τύπου"}
        </button>
      </form>
    </div>
  );
}

export default function AccountPrivacy({ onLogout, workshop, onWorkshopUpdated }) {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  async function handleExport() {
    setExporting(true);
    setExportError("");
    try {
      const data = await exportAccountData();
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `dedomena-logariasmou-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err.message);
    } finally {
      setExporting(false);
    }
  }

  async function handleDelete(e) {
    e.preventDefault();
    setDeleteError("");
    if (confirmText.trim().toUpperCase() !== "ΔΙΑΓΡΑΦΗ") {
      setDeleteError('Πληκτρολόγησε ακριβώς "ΔΙΑΓΡΑΦΗ" για επιβεβαίωση.');
      return;
    }
    setDeleting(true);
    try {
      await deleteAccount(password);
      onLogout();
    } catch (err) {
      setDeleteError(err.message);
      setDeleting(false);
    }
  }

  return (
    <div className="account-privacy">
      <p className="muted" style={{ marginTop: 0 }}>
        Διάβασε τους{" "}
        <a href="/terms" onClick={openLegalPage("/terms")}>
          Όρους Χρήσης
        </a>{" "}
        και την{" "}
        <a href="/privacy" onClick={openLegalPage("/privacy")}>
          Πολιτική Απορρήτου
        </a>
        .
      </p>

      <ChangePasswordForm />
      <BusinessTypeForm workshop={workshop} onWorkshopUpdated={onWorkshopUpdated} />

      <div className="alert alert-info">
        <b>Εξαγωγή δεδομένων.</b> Κατέβασε αντίγραφο όλων των δεδομένων του
        λογαριασμού σου (στοιχεία επιχείρησης, πελάτες, εγγραφές
        πελατολογίου) σε μορφή JSON.
        <div style={{ marginTop: "10px" }}>
          <button
            type="button"
            className="btn btn-sm"
            onClick={handleExport}
            disabled={exporting}
          >
            {exporting ? "Εξαγωγή…" : "⬇️ Εξαγωγή δεδομένων"}
          </button>
        </div>
        {exportError && <div className="alert alert-error" style={{ marginTop: "8px" }}>{exportError}</div>}
      </div>

      <div className="alert alert-error">
        <b>Διαγραφή λογαριασμού.</b> Οριστική διαγραφή του λογαριασμού και
        ΟΛΩΝ των δεδομένων σου (πελάτες, εγγραφές πελατολογίου, ρυθμίσεις).
        Δεν αναστρέφεται.

        {!confirmOpen ? (
          <div style={{ marginTop: "10px" }}>
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => setConfirmOpen(true)}
            >
              Διαγραφή λογαριασμού
            </button>
          </div>
        ) : (
          <form onSubmit={handleDelete} style={{ marginTop: "10px" }}>
            <label className="field-label">
              Κωδικός πρόσβασης:
              <input
                type="password"
                className="input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <label className="field-label">
              Πληκτρολόγησε «ΔΙΑΓΡΑΦΗ» για επιβεβαίωση:
              <input
                type="text"
                className="input"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                required
              />
            </label>
            {deleteError && <div className="alert alert-error">{deleteError}</div>}
            <div style={{ display: "flex", gap: "8px" }}>
              <button
                type="submit"
                className="btn btn-sm btn-danger"
                disabled={deleting}
              >
                {deleting ? "Διαγραφή…" : "Οριστική διαγραφή"}
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => {
                  setConfirmOpen(false);
                  setPassword("");
                  setConfirmText("");
                  setDeleteError("");
                }}
                disabled={deleting}
              >
                Ακύρωση
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
