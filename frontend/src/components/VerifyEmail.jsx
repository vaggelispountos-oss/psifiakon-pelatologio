// components/VerifyEmail.jsx
// --------------------------------------------------------------------
// Standalone σελίδα /verify-email?token=... — προσβάσιμη ΧΩΡΙΣ σύνδεση
// (δες App.jsx). Ο σύνδεσμος έρχεται από το email που στέλνει το backend
// στο POST /api/auth/register (δες auth.py: _send_verification_email).
// Αν ο χρήστης είναι ήδη συνδεδεμένος στη συσκευή αυτή (συνηθισμένο — η
// εγγραφή κάνει αυτόματο login), ενημερώνουμε ΚΑΙ το cached workshop ώστε
// να εξαφανιστεί αμέσως το μπάνερ επιβεβαίωσης χωρίς re-login.
// --------------------------------------------------------------------
import { useEffect, useState } from "react";
import { verifyEmail, getStoredWorkshop, setStoredWorkshop } from "../services/api";

function goHome() {
  window.history.pushState({}, "", "/");
  window.location.assign("/");
}

export default function VerifyEmail() {
  const token = new URLSearchParams(window.location.search).get("token") || "";
  const [status, setStatus] = useState(token ? "checking" : "missing"); // checking|ok|error|missing
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    verifyEmail(token)
      .then((data) => {
        const stored = getStoredWorkshop();
        if (stored) setStoredWorkshop({ ...stored, emailVerified: true });
        setStatus("ok");
      })
      .catch((err) => {
        setError(err.message);
        setStatus("error");
      });
  }, [token]);

  return (
    <div className="login-form-panel" style={{ minHeight: "100vh", overflowY: "auto" }}>
      <div className="login-card" style={{ maxWidth: 480, margin: "32px auto", width: "100%" }}>
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Επιβεβαίωση email</h2>

          {status === "missing" && (
            <div className="alert alert-error">
              Λείπει ο σύνδεσμος επιβεβαίωσης. Έλεγξε το email σου ή ζήτησε νέο
              από τις Ρυθμίσεις.
            </div>
          )}
          {status === "checking" && <p className="muted">Έλεγχος…</p>}
          {status === "ok" && (
            <div className="alert alert-info">
              ✅ Το email σου επιβεβαιώθηκε. Μπορείς να συνεχίσεις κανονικά.
            </div>
          )}
          {status === "error" && <div className="alert alert-error">{error}</div>}

          <button type="button" className="btn btn-primary btn-block" onClick={goHome}>
            Συνέχεια
          </button>
        </div>
      </div>
    </div>
  );
}
