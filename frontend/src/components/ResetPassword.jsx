// components/ResetPassword.jsx
// --------------------------------------------------------------------
// Standalone σελίδα /reset-password?token=... — προσβάσιμη ΧΩΡΙΣ σύνδεση
// (δες App.jsx). Ο σύνδεσμος έρχεται από το email που στέλνει το backend
// στο POST /api/auth/forgot-password (δες Login.jsx για το "Ξέχασες τον
// κωδικό;" mode που το ξεκινάει).
// --------------------------------------------------------------------
import { useState } from "react";
import { resetPassword } from "../services/api";

function goHome() {
  window.history.pushState({}, "", "/");
  window.location.assign("/");
}

export default function ResetPassword() {
  const token = new URLSearchParams(window.location.search).get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("Οι κωδικοί δεν ταιριάζουν.");
      return;
    }
    setBusy(true);
    try {
      await resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-form-panel" style={{ minHeight: "100vh", overflowY: "auto" }}>
      <div className="login-card" style={{ maxWidth: 480, margin: "32px auto", width: "100%" }}>
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Νέος κωδικός</h2>

          {!token ? (
            <div className="alert alert-error">
              Λείπει ο σύνδεσμος επαναφοράς. Ζήτησε νέον από την οθόνη σύνδεσης.
            </div>
          ) : done ? (
            <>
              <div className="alert alert-info">
                Ο κωδικός άλλαξε. Μπορείς να συνδεθείς με τον νέο κωδικό.
              </div>
              <button type="button" className="btn btn-primary btn-block" onClick={goHome}>
                Σύνδεση
              </button>
            </>
          ) : (
            <form onSubmit={handleSubmit}>
              <label className="field-label">
                Νέος κωδικός:
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
              <label className="field-label">
                Επιβεβαίωση κωδικού:
                <input
                  type="password"
                  className="input"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="new-password"
                  minLength={8}
                  required
                />
              </label>
              {error && <div className="alert alert-error">{error}</div>}
              <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
                {busy ? "..." : "Αλλαγή κωδικού"}
              </button>
            </form>
          )}

          <button type="button" className="btn btn-ghost btn-block" onClick={goHome}>
            ← Πίσω στη σύνδεση
          </button>
        </div>
      </div>
    </div>
  );
}
