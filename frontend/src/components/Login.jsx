// components/Login.jsx
// --------------------------------------------------------------------
// Οθόνη σύνδεσης / εγγραφής νέου συνεργείου (tenant). Εμφανίζεται όταν
// δεν υπάρχει έγκυρο access token.
// --------------------------------------------------------------------
import { useState } from "react";
import { login, register, forgotPassword } from "../services/api";
import { BUSINESS_TYPES } from "../constants";

export default function Login({ onAuthenticated }) {
  const [mode, setMode] = useState("login"); // login | register | forgot
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [businessType, setBusinessType] = useState("");
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [forgotSent, setForgotSent] = useState(false);

  function openLegalPage(path) {
    return (e) => {
      e.preventDefault();
      window.open(path, "_blank", "noopener,noreferrer");
    };
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    if (mode === "register" && !businessType) {
      setError("Επίλεξε τι είδους επιχείρηση είσαι.");
      return;
    }
    if (mode === "register" && !termsAccepted) {
      setError("Πρέπει να αποδεχθείς τους Όρους Χρήσης και την Πολιτική Απορρήτου.");
      return;
    }
    setBusy(true);
    try {
      if (mode === "forgot") {
        await forgotPassword(email);
        setForgotSent(true);
        return;
      }
      const data =
        mode === "login"
          ? await login({ email, password })
          : await register({ name, email, password, businessType, termsAccepted });
      onAuthenticated(data.workshop, data.actor);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function switchMode(nextMode) {
    setError(null);
    setForgotSent(false);
    setMode(nextMode);
  }

  return (
    <div className="login-screen">
      <div className="login-visual">
        <svg
          className="login-visual-art"
          viewBox="0 0 600 800"
          preserveAspectRatio="xMidYMid slice"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <linearGradient id="loginGlow" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2563eb" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#2563eb" stopOpacity="0" />
            </linearGradient>
          </defs>
          <circle cx="470" cy="90" r="220" fill="url(#loginGlow)" />

          {/* Γρανάζι φόντου */}
          <g
            fill="none"
            stroke="#334155"
            strokeWidth="2"
            transform="translate(90 400)"
          >
            <circle r="130" strokeDasharray="10 14" />
          </g>

          {/* Bay γκαράζ */}
          <path
            d="M60 310 L60 460 L540 460 L540 310"
            fill="none"
            stroke="#334155"
            strokeWidth="3"
          />
          <path
            d="M60 310 L300 180 L540 310"
            fill="none"
            stroke="#334155"
            strokeWidth="3"
          />
          <line x1="140" y1="280" x2="140" y2="460" stroke="#334155" strokeWidth="2" />
          <line x1="460" y1="280" x2="460" y2="460" stroke="#334155" strokeWidth="2" />

          {/* Αμάξι */}
          <g transform="translate(150 340)">
            <path
              d="M0 90 Q0 60 40 55 L70 20 Q85 5 115 5 L215 5 Q245 5 260 25 L285 55 Q320 60 320 90 L320 110 L0 110 Z"
              fill="#1e293b"
              stroke="#2563eb"
              strokeWidth="3"
            />
            <path
              d="M95 55 L120 22 Q130 12 150 12 L205 12 Q225 12 235 26 L258 55 Z"
              fill="#0f172a"
              stroke="#2563eb"
              strokeWidth="2"
            />
            <line x1="170" y1="18" x2="170" y2="55" stroke="#2563eb" strokeWidth="2" />
            <circle cx="70" cy="112" r="26" fill="#0f172a" stroke="#94a3b8" strokeWidth="4" />
            <circle cx="70" cy="112" r="8" fill="#334155" />
            <circle cx="255" cy="112" r="26" fill="#0f172a" stroke="#94a3b8" strokeWidth="4" />
            <circle cx="255" cy="112" r="8" fill="#334155" />
            <circle cx="40" cy="70" r="5" fill="#4ade80" />
          </g>

          {/* Κλειδί */}
          <g transform="translate(400 460) rotate(-25)" fill="#64748b">
            <circle cx="0" cy="0" r="20" fill="none" stroke="#64748b" strokeWidth="8" />
            <rect x="-6" y="18" width="12" height="70" rx="4" />
            <rect x="-16" y="80" width="12" height="16" rx="2" />
            <rect x="4" y="80" width="12" height="16" rx="2" />
          </g>

          {/* Ανιχνευτής πινακίδας */}
          <g transform="translate(230 500)">
            <rect
              x="0"
              y="0"
              width="140"
              height="34"
              rx="6"
              fill="#0f172a"
              stroke="#2563eb"
              strokeWidth="2.5"
            />
            <text
              x="70"
              y="23"
              textAnchor="middle"
              fontFamily="ui-monospace, monospace"
              fontSize="16"
              fill="#93c5fd"
              letterSpacing="2"
            >
              ΑΒΥ 1234
            </text>
          </g>
        </svg>
        <div className="login-visual-caption">
          <h3>Το συνεργείο σου, ψηφιακά.</h3>
          <p>
            Αναγνώριση πινακίδας, ιστορικό πελατών και παρακολούθηση εργασιών
            σε ένα σημείο — φτιαγμένο για τον ρυθμό του συνεργείου σου.
          </p>
        </div>
      </div>

      <div className="login-form-panel">
        <div className="login-card">
          <div className="login-brand-row">
            <div className="login-brand-icon">
              <svg viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
              </svg>
            </div>
            <div>
              <div className="login-brand-name">Ψηφιακό Πελατολόγιο</div>
              <div className="login-brand-sub">για συνεργεία αυτοκινήτων</div>
            </div>
          </div>

        <div className="card">
          <p className="muted" style={{ marginTop: 0 }}>
            {mode === "login"
              ? "Σύνδεση στον λογαριασμό του συνεργείου σου."
              : mode === "register"
              ? "Δημιουργία λογαριασμού για το συνεργείο σου."
              : "Στείλε μας το email σου και θα λάβεις σύνδεσμο επαναφοράς κωδικού."}
          </p>

          {error && <div className="alert alert-error">{error}</div>}

          {mode === "forgot" && forgotSent ? (
            <div className="alert alert-info">
              Αν υπάρχει λογαριασμός με αυτό το email, στάλθηκε σύνδεσμος
              επαναφοράς κωδικού. Έλεγξε τα εισερχόμενά σου (και τα spam).
            </div>
          ) : (
          <form onSubmit={handleSubmit}>
            {mode === "register" && (
              <>
                <div className="field-label">
                  Τι είδους επιχείρηση είσαι;
                  <div className="business-type-picker">
                    {BUSINESS_TYPES.map((bt) => (
                      <button
                        key={bt.value}
                        type="button"
                        className={`business-type-card${
                          businessType === bt.value ? " is-selected" : ""
                        }`}
                        onClick={() => setBusinessType(bt.value)}
                      >
                        <span className="business-type-icon">{bt.icon}</span>
                        <span className="business-type-label">{bt.label}</span>
                        <span className="business-type-desc">{bt.description}</span>
                      </button>
                    ))}
                  </div>
                </div>
                <label className="field-label">
                  Όνομα επιχείρησης:
                  <input
                    type="text"
                    className="input"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                  />
                </label>
              </>
            )}
            <label className="field-label">
              Email:
              <input
                type="email"
                className="input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                required
              />
            </label>
            {mode !== "forgot" && (
              <label className="field-label">
                Κωδικός:
                <input
                  type="password"
                  className="input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete={
                    mode === "login" ? "current-password" : "new-password"
                  }
                  minLength={8}
                  required
                />
              </label>
            )}
            {mode === "login" && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => switchMode("forgot")}
                style={{ marginBottom: "10px" }}
              >
                Ξέχασες τον κωδικό;
              </button>
            )}
            {mode === "register" && (
              <label className="field-label" style={{ flexDirection: "row", alignItems: "center", gap: "8px" }}>
                <input
                  type="checkbox"
                  checked={termsAccepted}
                  onChange={(e) => setTermsAccepted(e.target.checked)}
                  required
                />
                <span>
                  Διάβασα και αποδέχομαι τους{" "}
                  <a href="/terms" onClick={openLegalPage("/terms")}>
                    Όρους Χρήσης
                  </a>{" "}
                  και την{" "}
                  <a href="/privacy" onClick={openLegalPage("/privacy")}>
                    Πολιτική Απορρήτου
                  </a>
                  .
                </span>
              </label>
            )}
            <button
              type="submit"
              className="btn btn-primary btn-block"
              disabled={busy}
            >
              {busy
                ? "..."
                : mode === "login"
                ? "Σύνδεση"
                : mode === "register"
                ? "Δημιουργία λογαριασμού"
                : "Αποστολή συνδέσμου επαναφοράς"}
            </button>
          </form>
          )}

          <button
            type="button"
            className="btn btn-ghost btn-block"
            onClick={() => switchMode(mode === "register" ? "login" : mode === "forgot" ? "login" : "register")}
          >
            {mode === "login"
              ? "Δεν έχεις λογαριασμό; Δημιούργησε έναν"
              : mode === "register"
              ? "Έχεις ήδη λογαριασμό; Σύνδεση"
              : "← Πίσω στη σύνδεση"}
          </button>
        </div>
        </div>
      </div>
    </div>
  );
}
