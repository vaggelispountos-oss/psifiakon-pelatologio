// components/InstallAppPrompt.jsx
// --------------------------------------------------------------------
// Banner που καθοδηγεί τον χρήστη να «κατεβάσει» (εγκαταστήσει) την
// εφαρμογή από τον browser στην αρχική οθόνη του κινητού.
//
// - Android/Chrome: πιάνει το native `beforeinstallprompt` event και
//   δείχνει κουμπί που ανοίγει το πραγματικό install dialog.
// - iOS Safari: ΔΕΝ υποστηρίζει beforeinstallprompt, οπότε δείχνουμε
//   γραπτές οδηγίες «Κοινοποίηση -> Προσθήκη στην Αρχική Οθόνη».
// - Κρύβεται αυτόματα αν η εφαρμογή τρέχει ήδη ως PWA (standalone) ή
//   αν ο χρήστης το έχει κλείσει.
// --------------------------------------------------------------------
import { useEffect, useState } from "react";

const DISMISS_KEY = "dcl_install_prompt_dismissed";

function isStandalone() {
  return (
    window.matchMedia?.("(display-mode: standalone)")?.matches ||
    window.navigator.standalone === true // Safari iOS
  );
}

function isIOS() {
  return /iphone|ipad|ipod/i.test(window.navigator.userAgent);
}

export default function InstallAppPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [visible, setVisible] = useState(false);
  const [showIosSteps, setShowIosSteps] = useState(false);

  useEffect(() => {
    if (isStandalone() || localStorage.getItem(DISMISS_KEY) === "1") return;

    if (isIOS()) {
      setVisible(true);
      return;
    }

    function onBeforeInstallPrompt(e) {
      e.preventDefault();
      setDeferredPrompt(e);
      setVisible(true);
    }
    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt);
    return () =>
      window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt);
  }, []);

  function dismiss() {
    setVisible(false);
    setShowIosSteps(false);
    localStorage.setItem(DISMISS_KEY, "1");
  }

  async function handleInstallClick() {
    if (isIOS()) {
      setShowIosSteps((v) => !v);
      return;
    }
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    setDeferredPrompt(null);
    setVisible(false);
  }

  if (!visible) return null;

  return (
    <div className="install-prompt">
      <div className="install-prompt-row">
        <span className="install-prompt-icon">📲</span>
        <div className="install-prompt-text">
          <b>Εγκατάσταση εφαρμογής στο κινητό</b>
          <span className="muted">
            Πρόσβαση σαν κανονική εφαρμογή, χωρίς browser γύρω-γύρω.
          </span>
        </div>
        <button className="btn btn-primary btn-sm" onClick={handleInstallClick}>
          Εγκατάσταση
        </button>
        <button className="btn btn-ghost btn-sm" onClick={dismiss} aria-label="Κλείσιμο">
          ✕
        </button>
      </div>

      {showIosSteps && (
        <ol className="install-prompt-steps">
          <li>
            Πάτησε το εικονίδιο <b>Κοινοποίηση</b> (τετράγωνο με βέλος προς τα πάνω) στη
            γραμμή του Safari.
          </li>
          <li>
            Επίλεξε <b>«Προσθήκη στην Αρχική Οθόνη»</b> (Add to Home Screen).
          </li>
          <li>Πάτησε <b>«Προσθήκη»</b> πάνω δεξιά.</li>
        </ol>
      )}
    </div>
  );
}
