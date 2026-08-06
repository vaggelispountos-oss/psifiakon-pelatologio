// components/SettingsPanel.jsx
// --------------------------------------------------------------------
// Οθόνη «Ρυθμίσεις ΑΑΔΕ» — χειροκίνητη εισαγωγή credentials.
// Το Subscription Key ΔΕΝ φορτώνεται ποτέ ολόκληρο (ασφάλεια): αν υπάρχει,
// δείχνουμε placeholder και το αφήνουμε κενό ώστε να μην αλλάξει.
// --------------------------------------------------------------------
import { useEffect, useState } from "react";
import {
  getSettings,
  updateSettings,
  testConnection,
  setAadeLiveMode,
} from "../services/api";
import {
  getOcrEnginePreference,
  setOcrEnginePreference,
} from "../services/plateRecognizer";
import Accordion from "./Accordion";
import HelpKnowledgeBase from "./HelpKnowledgeBase";
import ContactSupport from "./ContactSupport";
import InstallAppPrompt from "./InstallAppPrompt";
import AccountPrivacy from "./AccountPrivacy";

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

  const [switchingLive, setSwitchingLive] = useState(false);

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

  async function handleGoLive() {
    if (
      !window.confirm(
        "Ενεργοποίηση πραγματικής σύνδεσης με την ΑΑΔΕ;\n\n" +
          "Από εδώ και πέρα κάθε νέα εγγραφή θα καταχωρείται ΠΡΑΓΜΑΤΙΚΑ στο " +
          "Ψηφιακό Πελατολόγιο (myDATA) — δεν θα είναι πλέον δοκιμαστική."
      )
    ) {
      return;
    }
    setSwitchingLive(true);
    setError("");
    setOk("");
    try {
      const s = await setAadeLiveMode(true);
      setStatus(s);
      setOk("Η πραγματική σύνδεση με την ΑΑΔΕ ενεργοποιήθηκε.");
    } catch (err) {
      setError(err.message);
    } finally {
      setSwitchingLive(false);
    }
  }

  async function handleGoMock() {
    if (
      !window.confirm(
        "Επιστροφή σε δοκιμαστική λειτουργία (mock); Οι νέες εγγραφές δεν θα " +
          "στέλνονται πλέον πραγματικά στην ΑΑΔΕ."
      )
    ) {
      return;
    }
    setSwitchingLive(true);
    setError("");
    setOk("");
    try {
      const s = await setAadeLiveMode(false);
      setStatus(s);
      setOk("Επιστροφή σε δοκιμαστική λειτουργία (mock).");
    } catch (err) {
      setError(err.message);
    } finally {
      setSwitchingLive(false);
    }
  }

  const hasKey = status?.has_key;
  const isLive = status?.force_real_aade;

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

          {/* Live/Mock switch */}
          <div className="alert alert-info">
            {isLive ? (
              <>
                🟢 <b>Live</b> — οι εγγραφές στέλνονται πραγματικά στην ΑΑΔΕ
                (Ψηφιακό Πελατολόγιο).
              </>
            ) : (
              <>
                🧪 <b>Δοκιμαστική λειτουργία (mock)</b> — οι εγγραφές ΔΕΝ
                στέλνονται στην ΑΑΔΕ, δεν θα τις δεις στο myDATA.
              </>
            )}
          </div>
          <div className="test-conn">
            {isLive ? (
              <button
                type="button"
                className="btn btn-sm"
                onClick={handleGoMock}
                disabled={switchingLive}
              >
                {switchingLive ? "…" : "↩️ Επιστροφή σε δοκιμαστική λειτουργία"}
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleGoLive}
                disabled={switchingLive || !hasKey}
              >
                {switchingLive ? "…" : "🚀 Ενεργοποίηση πραγματικής ΑΑΔΕ (live)"}
              </button>
            )}
            {!hasKey && (
              <span className="muted small">όρισε πρώτα κωδικούς</span>
            )}
          </div>

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

// Ρύθμιση engine αναγνώρισης πινακίδας. Τοπική (ανά συσκευή, localStorage)
// γιατί είναι θέμα δικτύου/απορρήτου της ΣΥΓΚΕΚΡΙΜΕΝΗΣ συσκευής/χρήστη, όχι
// tenant-wide πολιτική — δες services/plateRecognizer/index.js.
function OcrEngineSettings() {
  const [pref, setPref] = useState(getOcrEnginePreference());

  function choose(next) {
    setOcrEnginePreference(next);
    setPref(next);
  }

  return (
    <div className="settings-form">
      <div className="alert alert-info">
        Το <b>ALPR</b> (Plate Recognizer) είναι εξειδικευμένο σε πινακίδες και
        ΠΟΛΥ πιο ακριβές από το δωρεάν Tesseract — αλλά στέλνει την εικόνα της
        πινακίδας σε εξωτερικό server. Στη λειτουργία «Αυτόματο», αν το ALPR
        δεν είναι διαθέσιμο (χωρίς δίκτυο, όριο χρήσης) γίνεται αυτόματη
        επιστροφή στο Tesseract (τοπικά, χωρίς αποστολή εικόνας πουθενά).
      </div>

      <label className="field-label field-checkbox">
        <input
          type="radio"
          name="ocr-engine"
          checked={pref === "auto"}
          onChange={() => choose("auto")}
        />
        Αυτόματο — ALPR πρώτα, Tesseract αν χρειαστεί (προτεινόμενο)
      </label>
      <label className="field-label field-checkbox">
        <input
          type="radio"
          name="ocr-engine"
          checked={pref === "tesseract"}
          onChange={() => choose("tesseract")}
        />
        Μόνο Tesseract — καμία εικόνα δεν στέλνεται εκτός συσκευής (λιγότερο
        ακριβές)
      </label>
    </div>
  );
}

// Accordion με ΟΛΗ την οθόνη Ρυθμίσεων — μόνο μία ενότητα ανοιχτή τη φορά
// ώστε να μην πιάνουν πολύ χώρο οι κάρτες. Σειρά (ζητήθηκε ρητά):
// Οδηγός Σφαλμάτων πάνω-πάνω, Ρυθμίσεις ΑΑΔΕ κάτω-κάτω.
export function SettingsAccordion({ onSaved, onLogout, workshop, onWorkshopUpdated }) {
  return (
    <Accordion
      defaultOpen="kb"
      sections={[
        { id: "kb", title: "Οδηγός Σφαλμάτων — Τι κάνω αν δω…", render: () => <HelpKnowledgeBase /> },
        { id: "contact", title: "Επικοινωνία", render: () => <ContactSupport /> },
        {
          id: "privacy",
          title: "Ο λογαριασμός & τα δεδομένα μου",
          render: () => (
            <AccountPrivacy
              onLogout={onLogout}
              workshop={workshop}
              onWorkshopUpdated={onWorkshopUpdated}
            />
          ),
        },
        {
          id: "install",
          title: "Εγκατάσταση στο κινητό",
          render: () => (
            <div>
              <p className="muted" style={{ marginTop: 0 }}>
                Πρόσθεσε την εφαρμογή στην αρχική οθόνη του κινητού σου για
                πρόσβαση σαν κανονική εφαρμογή.
              </p>
              <InstallAppPrompt />
            </div>
          ),
        },
        {
          id: "ocr",
          title: "Αναγνώριση Πινακίδας (OCR)",
          render: () => <OcrEngineSettings />,
        },
        { id: "aade", title: "Ρυθμίσεις ΑΑΔΕ", render: () => <SettingsPanel onSaved={onSaved} /> },
      ]}
    />
  );
}
