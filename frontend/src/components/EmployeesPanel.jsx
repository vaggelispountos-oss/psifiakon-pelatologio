// components/EmployeesPanel.jsx
// --------------------------------------------------------------------
// «Υπάλληλοι» — ο owner δημιουργεί/απενεργοποιεί/σβήνει logins για το
// προσωπικό του συνεργείου. Κάθε υπάλληλος βλέπει ΤΑ ΙΔΙΑ δεδομένα με τον
// owner (ίδιο workshop) — ο σκοπός είναι κυρίως audit trail: ΠΟΙΟΣ έκανε ΤΙ
// (δες backend models.Employee, app._log_aade / DclEntry.createdByName).
// --------------------------------------------------------------------
import { useEffect, useState } from "react";
import {
  getEmployees,
  createEmployee,
  updateEmployee,
  deleteEmployee,
} from "../services/api";

function CreateEmployeeForm({ onCreated }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      const employee = await createEmployee({ name, email, password });
      onCreated(employee);
      setName("");
      setEmail("");
      setPassword("");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="employee-create-form">
      <label className="field-label">
        Όνομα:
        <input
          type="text"
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </label>
      <label className="field-label">
        Email:
        <input
          type="email"
          className="input"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
      </label>
      <label className="field-label">
        Κωδικός (τουλάχιστον 8 χαρακτήρες):
        <input
          type="password"
          className="input"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
          minLength={8}
          required
        />
      </label>
      {error && <div className="alert alert-error">{error}</div>}
      <button type="submit" className="btn btn-sm" disabled={saving}>
        {saving ? "Δημιουργία…" : "➕ Νέος υπάλληλος"}
      </button>
    </form>
  );
}

function EmployeeRow({ employee, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resetOpen, setResetOpen] = useState(false);
  const [newPassword, setNewPassword] = useState("");

  async function toggleActive() {
    setBusy(true);
    setError("");
    try {
      const updated = await updateEmployee(employee.id, {
        isActive: !employee.isActive,
      });
      onChanged(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleResetPassword(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await updateEmployee(employee.id, { password: newPassword });
      setNewPassword("");
      setResetOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Οριστική διαγραφή του λογαριασμού «${employee.name}»;`)) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await deleteEmployee(employee.id);
      onChanged(null, employee.id);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="employee-row">
      <div className="employee-row-main">
        <div>
          <b>{employee.name}</b>{" "}
          {!employee.isActive && <span className="muted">(ανενεργός)</span>}
          <div className="muted small">{employee.email}</div>
        </div>
        <div className="employee-row-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={toggleActive}
            disabled={busy}
          >
            {employee.isActive ? "Απενεργοποίηση" : "Ενεργοποίηση"}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setResetOpen((v) => !v)}
            disabled={busy}
          >
            Reset κωδικού
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm btn-danger"
            onClick={handleDelete}
            disabled={busy}
          >
            Διαγραφή
          </button>
        </div>
      </div>
      {resetOpen && (
        <form onSubmit={handleResetPassword} className="employee-reset-form">
          <input
            type="password"
            className="input"
            placeholder="Νέος κωδικός (τουλάχιστον 8 χαρακτήρες)"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            minLength={8}
            required
          />
          <button type="submit" className="btn btn-sm" disabled={busy}>
            Αποθήκευση
          </button>
        </form>
      )}
      {error && <div className="alert alert-error">{error}</div>}
    </div>
  );
}

export default function EmployeesPanel() {
  const [employees, setEmployees] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getEmployees()
      .then(setEmployees)
      .catch((err) => setError(err.message));
  }, []);

  function handleChanged(updated, deletedId) {
    setEmployees((prev) => {
      if (!prev) return prev;
      if (deletedId != null) return prev.filter((e) => e.id !== deletedId);
      return prev.map((e) => (e.id === updated.id ? updated : e));
    });
  }

  function handleCreated(employee) {
    setEmployees((prev) => (prev ? [...prev, employee] : [employee]));
  }

  return (
    <div className="employees-panel">
      <p className="muted" style={{ marginTop: 0 }}>
        Κάθε υπάλληλος συνδέεται με το δικό του email/κωδικό και βλέπει τα
        ίδια δεδομένα με εσένα — η διαφορά είναι ότι κάθε ενέργειά του
        καταγράφεται με το όνομά του (δες π.χ. τη στήλη «Δημιουργήθηκε από»
        στις εγγραφές).
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {employees === null && !error && <p className="muted">Φόρτωση…</p>}
      {employees && employees.length === 0 && (
        <p className="muted">Δεν έχεις προσθέσει ακόμα κανέναν υπάλληλο.</p>
      )}
      {employees && employees.length > 0 && (
        <div className="employees-list">
          {employees.map((e) => (
            <EmployeeRow key={e.id} employee={e} onChanged={handleChanged} />
          ))}
        </div>
      )}
      <hr style={{ margin: "16px 0", border: "none", borderTop: "1px solid var(--border, #333)" }} />
      <CreateEmployeeForm onCreated={handleCreated} />
    </div>
  );
}
