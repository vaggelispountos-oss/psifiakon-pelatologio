// components/InstallAppPrompt.jsx
// --------------------------------------------------------------------
// Σταθερό κουμπί (όχι αυτόματο popup/banner) που ο χρήστης πατάει όποτε
// θέλει για να εγκαταστήσει την εφαρμογή στην αρχική οθόνη του κινητού.
//
// - Android/Chrome: πιάνει το native `beforeinstallprompt` event και το
//   κουμπί ανοίγει το πραγματικό install dialog. Αν το event δεν έχει
//   ακόμα έρθει (ή έχει λήξει), δείχνει οδηγίες μέσω του μενού ⋮.
// - iOS Safari: ΔΕΝ υποστηρίζει beforeinstallprompt, οπότε το κουμπί
//   δείχνει πάντα γραπτές οδηγίες «Κοινοποίηση -> Προσθήκη στην Αρχική
//   Οθόνη».
// - Εξαφανίζεται μόνο αν η εφαρμογή τρέχει ήδη ως εγκατεστημένο PWA
//   (standalone) — δεν «κλείνει» μόνιμα σαν popup.
// --------------------------------------------------------------------
import { useEffect, useState } from "react";

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
  const [standalone, setStandalone] = useState(isStandalone);
  const [showSteps, setShowSteps] = useState(false);

  useEffect(() => {
    if (isIOS() || standalone) return;

    function onBeforeInstallPrompt(e) {
      e.preventDefault();
      setDeferredPrompt(e);
    }
    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt);

    function onAppInstalled() {
      setStandalone(true);
    }
    window.addEventListener("appinstalled", onAppInstalled);

    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt);
      window.removeEventListener("appinstalled", onAppInstalled);
    };
  }, [standalone]);

  async function handleInstallClick() {
    if (isIOS()) {
      setShowSteps((v) => !v);
      return;
    }
    // Το deferredPrompt μπορεί να μην έχει έρθει ακόμα, ή να έχει ήδη
    // ακυρωθεί από τον browser — τότε δείξε το χειροκίνητο μονοπάτι μέσω
    // του μενού ⋮ αντί να μην κάνουμε τίποτα.
    if (!deferredPrompt) {
      setShowSteps((v) => !v);
      return;
    }
    try {
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      setDeferredPrompt(null);
      setShowSteps(false);
    } catch {
      setShowSteps(true);
    }
  }

  if (standalone) return null;

  return (
    <div className="install-inline">
      <button
        type="button"
        className="btn btn-ghost btn-sm install-inline-btn"
        onClick={handleInstallClick}
      >
        📲 Εγκατάσταση εφαρμογής
      </button>

      {showSteps && isIOS() && (
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

      {showSteps && !isIOS() && (
        <ol className="install-prompt-steps">
          <li>
            Πάτησε το μενού <b>⋮</b> πάνω δεξιά στο Chrome.
          </li>
          <li>
            Επίλεξε <b>«Εγκατάσταση εφαρμογής»</b> (ή «Προσθήκη στην αρχική οθόνη»).
          </li>
        </ol>
      )}
    </div>
  );
}
