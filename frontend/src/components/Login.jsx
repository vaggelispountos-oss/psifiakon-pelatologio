// components/Login.jsx
// --------------------------------------------------------------------
// Οθόνη σύνδεσης / εγγραφής νέου συνεργείου (tenant). Εμφανίζεται όταν
// δεν υπάρχει έγκυρο access token.
// --------------------------------------------------------------------
import { useState } from "react";
import { login, register } from "../services/api";

export default function Login({ onAuthenticated }) {
  const [mode, setMode] = useState("login"); // login | register
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const data =
        mode === "login"
          ? await login({ email, password })
          : await register({ name, email, password });
      onAuthenticated(data.workshop);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <main className="content" style={{ maxWidth: 420, margin: "0 auto" }}>
        <div className="card">
          <h2>🔧 Ψηφιακό Πελατολόγιο</h2>
          <p className="muted">
            {mode === "login"
              ? "Σύνδεση στον λογαριασμό του συνεργείου σου."
              : "Δημιουργία λογαριασμού για το συνεργείο σου."}
          </p>

          {error && <div className="alert alert-error">{error}</div>}

          <form onSubmit={handleSubmit}>
            {mode === "register" && (
              <label className="field-label">
                Όνομα συνεργείου:
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </label>
            )}
            <label className="field-label">
              Email:
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                required
              />
            </label>
            <label className="field-label">
              Κωδικός:
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                minLength={8}
                required
              />
            </label>
            <button
              type="submit"
              className="btn btn-primary btn-block"
              disabled={busy}
            >
              {busy
                ? "..."
                : mode === "login"
                ? "Σύνδεση"
                : "Δημιουργία λογαριασμού"}
            </button>
          </form>

          <button
            type="button"
            className="btn btn-ghost btn-block"
            onClick={() => {
              setError(null);
              setMode(mode === "login" ? "register" : "login");
            }}
          >
            {mode === "login"
              ? "Δεν έχεις λογαριασμό; Δημιούργησε έναν"
              : "Έχεις ήδη λογαριασμό; Σύνδεση"}
          </button>
        </div>
      </main>
    </div>
  );
}
