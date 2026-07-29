// components/SettingsPanel.jsx
// --------------------------------------------------------------------
// Οθόνη «Ρυθμίσεις ΑΑΔΕ» — χειροκίνητη εισαγωγή credentials.
// Το Subscription Key ΔΕΝ φορτώνεται ποτέ ολόκληρο (ασφάλεια): αν υπάρχει,
// δείχνουμε placeholder και το αφήνουμε κενό ώστε να μην αλλάξει.
// --------------------------------------------------------------------
import { useEffect, useState } from "react";
import { getSettings, updateSettings, testConnection } from "../services/api";
import Accordion from "./Accordion";
import HelpKnowledgeBase from "./HelpKnowledgeBase";
import ContactSupport from "./ContactSupport";

export default function SettingsPanel({ onSaved }) {
  const [username, setUsername] = useState("");
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [branch, setBranch] = useState("0");
  const [vat, setVat] = useState("");

  const [status, setStatus] = useState(null); // {has_key, masked_key}
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // {ok, message/reason}

  async function load() {
    setLoading(true);
    setError("");
    try {
      const s = await getSettings();
      setStatus(s);
      setUsername(s.aade_username || "");
      setBranch(String(s.branch ?? 0));
      setVat(s.entity_vat_number || "");
      setKey(""); // ποτέ δεν φορτώνουμε το key
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleSave(e) {
    e.preventDefault();
    setError("");
    setOk("");
    setSaving(true);
    try {
      const s = await updateSettings({
        aade_username: username.trim(),
        // Αν κενό, το backend κρατά το υπάρχον key
        aade_subscription_key: key,
        branch: Number(branch),
        entity_vat_number: vat.trim(),
      });
      setStatus(s);
      setKey("");
      setOk("Οι ρυθμίσεις αποθηκεύτηκαν.");
      if (onSaved) onSaved(s);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTestResult(null);
    setTesting(true);
    try {
      const res = await testConnection();
      setTestResult(res);
    } catch (err) {
      setTestResult({ ok: false, reason: err.message });
    } finally {
      setTesting(false);
    }
  }

  const hasKey = status?.has_key;

  return (
    <div className="settings-form">
      <div className="alert alert-info">
        <b>Πώς βρίσκω τους κωδικούς:</b> Σύνδεση στο myDATA με τους κωδικούς
        TAXISnet → «Εγγραφή στο myDATA REST API» → δημιουργείς <b>Όνομα Χρήστη</b>{" "}
        και λαμβάνεις το <b>Subscription Key</b>. Αυτά μπαίνουν στα headers κάθε
        κλήσης προς την ΑΑΔΕ.
      </div>

      {loading ? (
        <p className="muted">Φόρτωση…</p>
      ) : (
        <>
          {/* Κατάσταση κλειδιού */}
          {hasKey ? (
            <div className="alert alert-info">
              ✅ Οι κωδικοί έχουν οριστεί. Αποθηκευμένο key:{" "}
              <span className="mono">{status.masked_key}</span>
            </div>
          ) : (
            <div className="alert alert-error">
              ⚠️ Δεν έχουν οριστεί κωδικοί. Η δημιουργία εγγραφών είναι
              απενεργοποιημένη μέχρι να τους συμπληρώσεις.
            </div>
          )}

          {/* Έλεγχος σύνδεσης */}
          <div className="test-conn">
            <button
              type="button"
              className="btn btn-sm"
              onClick={handleTest}
              disabled={testing || !hasKey}
            >
              {testing ? "Έλεγχος…" : "🔌 Έλεγχος σύνδεσης"}
            </button>
            {!hasKey && (
              <span className="muted small">όρισε πρώτα κωδικούς</span>
            )}
            {testing && <span className="spinner" aria-label="φόρτωση" />}
            {testResult &&
              (testResult.ok ? (
                <span className="conn-ok">
                  ✅ {testResult.message || "Σύνδεση επιτυχής"}
                </span>
              ) : (
                <span className="conn-fail">
                  ❌ {testResult.reason || "Αποτυχία σύνδεσης"}
                </span>
              ))}
          </div>

          <form onSubmit={handleSave}>
            <label className="field-label">
              Όνομα Χρήστη (aade-user-id):
              <input
                className="input"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="π.χ. mydata_user"
              />
            </label>

            <label className="field-label">
              Subscription Key:
              <div className="key-row">
                <input
                  className="input"
                  type={showKey ? "text" : "password"}
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  placeholder={
                    hasKey
                      ? "(αποθηκευμένο — άφησέ το κενό για να μην αλλάξει)"
                      : "Επικόλλησε το Subscription Key"
                  }
                  autoComplete="off"
                />
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowKey((v) => !v)}
                >
                  {showKey ? "Απόκρυψη" : "Εμφάνιση"}
                </button>
              </div>
            </label>

            <label className="field-label">
              Αριθμός Εγκατάστασης (branch):
              <input
                className="input"
                type="number"
                min="0"
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
              />
            </label>

            <label className="field-label">
              ΑΦΜ Υπόχρεης Οντότητας (προαιρετικό):
              <input
                className="input"
                type="text"
                inputMode="numeric"
                value={vat}
                onChange={(e) => setVat(e.target.value)}
                placeholder="9 ψηφία"
              />
              <span className="muted small">
                Συμπληρώστε μόνο αν διαβιβάζετε ως λογιστής για λογαριασμό πελάτη.
              </span>
            </label>

            {error && <div className="alert alert-error">{error}</div>}
            {ok && <div className="alert alert-info">{ok}</div>}

            <button className="btn btn-primary btn-block" disabled={saving}>
              {saving ? "Αποθήκευση…" : "Αποθήκευση"}
            </button>
          </form>
        </>
      )}
    </div>
  );
}

// Accordion με ΟΛΗ την οθόνη Ρυθμίσεων — μόνο μία ενότητα ανοιχτή τη φορά
// ώστε να μην πιάνουν πολύ χώρο οι κάρτες. Σειρά (ζητήθηκε ρητά):
// Οδηγός Σφαλμάτων πάνω-πάνω, Ρυθμίσεις ΑΑΔΕ κάτω-κάτω.
export function SettingsAccordion({ onSaved }) {
  return (
    <Accordion
      defaultOpen="kb"
      sections={[
        { id: "kb", title: "Οδηγός Σφαλμάτων — Τι κάνω αν δω…", render: () => <HelpKnowledgeBase /> },
        { id: "contact", title: "Επικοινωνία", render: () => <ContactSupport /> },
        { id: "aade", title: "Ρυθμίσεις ΑΑΔΕ", render: () => <SettingsPanel onSaved={onSaved} /> },
      ]}
    />
  );
}
