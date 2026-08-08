// components/ErrorBoundary.jsx
// --------------------------------------------------------------------
// Πιάνει σφάλματα render/lifecycle των παιδιών του και δείχνει μήνυμα αντί
// για ΛΕΥΚΗ ΣΕΛΙΔΑ — που είναι η default συμπεριφορά του React 18: ένα
// σφάλμα σε render ξεριζώνει ΟΛΟΚΛΗΡΟ το δέντρο, όχι μόνο το component που
// έσκασε.
//
// Class component κατ' ανάγκη: δεν υπάρχει hook αντίστοιχο του
// componentDidCatch (React 18).
//
// ⚠️ ΤΙ ΔΕΝ ΠΙΑΝΕΙ: σφάλματα σε event handlers και σε async κώδικα (π.χ. το
// .catch() ενός fetch). Αυτά τα χειρίζεται ήδη το try/catch + toast στο
// App.jsx — μη νομίσεις ότι αυτό εδώ τα καλύπτει.
// --------------------------------------------------------------------
import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Το Sentry (backend, SENTRY_DSN) πιάνει ΜΟΝΟ σφάλματα του Flask — για
    // το frontend δεν υπάρχει αντίστοιχο, οπότε αυτό είναι ό,τι έχουμε:
    // τουλάχιστον να μείνει στην κονσόλα με το component stack, ώστε να
    // βγάζει νόημα ένα screenshot από πελάτη.
    console.error("ErrorBoundary:", error, info?.componentStack);
  }

  handleReset = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    const { title, fullPage } = this.props;

    return (
      <div className="card error-boundary">
        <h2>⚠️ {title || "Κάτι πήγε στραβά"}</h2>
        <p className="muted">
          {fullPage
            ? "Η εφαρμογή συνάντησε απρόσμενο σφάλμα. Τα δεδομένα σου ΔΕΝ έχουν χαθεί — είναι αποθηκευμένα στον διακομιστή."
            : "Αυτό το τμήμα δεν μπόρεσε να φορτώσει. Η υπόλοιπη εφαρμογή λειτουργεί κανονικά."}
        </p>

        <div className="btn-row">
          {fullPage ? (
            // Reset χωρίς reload θα ξανάχτιζε το ίδιο δέντρο πάνω σε ό,τι
            // κατάσταση το έσκασε — σε app-level σφάλμα το reload είναι το
            // μόνο αξιόπιστο.
            <button
              className="btn btn-primary"
              onClick={() => window.location.reload()}
            >
              🔄 Επαναφόρτωση
            </button>
          ) : (
            <button className="btn btn-primary" onClick={this.handleReset}>
              Δοκίμασε ξανά
            </button>
          )}
        </div>

        {/* Πίσω από <details>: χρήσιμο μόνο αν το στείλει ο χρήστης στην
            υποστήριξη, και ένα stack trace στη μέση της οθόνης τρομάζει. */}
        <details className="error-boundary-details">
          <summary>Τεχνικές λεπτομέρειες</summary>
          <pre className="mono">{String(error?.message || error)}</pre>
        </details>
      </div>
    );
  }
}
