// services/plateRecognizer/index.js
// --------------------------------------------------------------------
// Pluggable αναγνώριση πλάκας.
//
// Default συμπεριφορά ΤΩΡΑ: "auto" -> δοκίμασε πρώτα το εξειδικευμένο ALPR
// (Plate Recognizer, δες plateRecognizerApiRecognizer.js) και μόνο αν
// αποτύχει (λείπει token, δεν υπάρχει δίκτυο, σφάλμα API) κάνε ΣΙΩΠΗΛΟ
// fallback στο δωρεάν client-side Tesseract — έτσι ο χρήστης έχει πάντα το
// καλύτερο δυνατό αποτέλεσμα χωρίς να χρειάζεται να ξέρει ποιο engine τρέχει.
//
// Ο χρήστης μπορεί να το αλλάξει από τις Ρυθμίσεις (privacy: το ALPR στέλνει
// την εικόνα σε εξωτερικό server) — αποθηκεύεται τοπικά (runtime, όχι
// build-time env) ώστε να αλλάζει χωρίς rebuild:
//   localStorage["ocrEngine"] = "auto" (default) | "tesseract"
//
// Όλες οι υλοποιήσεις εκθέτουν:
//     recognizePlate(imageSource, onProgress?, opts?) -> Promise<{
//         plate: string|null, confidence: number|null,
//         rawText: string, warnings: string[], corrected: boolean,
//         processedDataUrl?: string, candidates?: Array
//     }>
// --------------------------------------------------------------------
import * as tesseractRecognizer from "./tesseractRecognizer";
import * as plateRecognizerApiRecognizer from "./plateRecognizerApiRecognizer";

const STORAGE_KEY = "ocrEngine";

// Advanced/self-hosted override: VITE_RECOGNIZER=tesseract απενεργοποιεί
// ΕΝΤΕΛΩΣ το ALPR path στο build (π.χ. deployment χωρίς PLATE_RECOGNIZER_TOKEN
// και χωρίς πρόσβαση σε εξωτερικό δίκτυο). Χωρίς αυτό, default είναι "auto".
const BUILD_FORCED = (import.meta.env && import.meta.env.VITE_RECOGNIZER) || null;

/** @returns {"auto"|"tesseract"} η τρέχουσα προτίμηση engine (runtime, ανά συσκευή). */
export function getOcrEnginePreference() {
  if (BUILD_FORCED === "tesseract") return "tesseract";
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "tesseract" ? "tesseract" : "auto";
  } catch {
    return "auto"; // localStorage απενεργοποιημένο (private mode κ.λπ.)
  }
}

/** @param {"auto"|"tesseract"} pref */
export function setOcrEnginePreference(pref) {
  try {
    localStorage.setItem(STORAGE_KEY, pref === "tesseract" ? "tesseract" : "auto");
  } catch {
    // αγνόησε — απλά δεν θα επιμείνει η προτίμηση σε αυτή τη συσκευή
  }
}

/**
 * @returns {{recognizePlate: Function}} recognizer με ΙΔΙΟ interface με τα
 * επιμέρους recognizers, αλλά που κάνει ΚΑΙ το fallback logic. Το
 * αποτέλεσμα περιλαμβάνει `engineUsed` (ποιο engine ΠΡΑΓΜΑΤΙΚΑ απάντησε) και
 * `engineFallback` (true αν το ALPR απέτυχε και έγινε fallback σε tesseract),
 * ώστε το UI/οι μετρικές να δείχνουν την ΠΡΑΓΜΑΤΙΚΟΤΗΤΑ, όχι τη ρύθμιση.
 */
export function getRecognizer() {
  const pref = getOcrEnginePreference();

  if (pref === "tesseract") {
    return {
      async recognizePlate(imageSource, onProgress, opts) {
        const result = await tesseractRecognizer.recognizePlate(
          imageSource,
          onProgress,
          opts
        );
        return { ...result, engineUsed: "tesseract", engineFallback: false };
      },
    };
  }

  return {
    async recognizePlate(imageSource, onProgress, opts) {
      try {
        const result = await plateRecognizerApiRecognizer.recognizePlate(
          imageSource,
          onProgress,
          opts
        );
        return { ...result, engineUsed: "plate_recognizer", engineFallback: false };
      } catch (alprErr) {
        // Fallback ΣΙΩΠΗΛΟ ως προς τη ροή (ο χρήστης δεν χρειάζεται να κάνει
        // τίποτα) αλλά ΟΧΙ κρυφό — το engineFallback φτάνει στο UI ώστε να
        // φαίνεται ότι χρησιμοποιήθηκε το λιγότερο ακριβές engine.
        const result = await tesseractRecognizer.recognizePlate(
          imageSource,
          onProgress,
          opts
        );
        return {
          ...result,
          engineUsed: "tesseract",
          engineFallback: true,
          fallbackReason: alprErr.message,
        };
      }
    },
  };
}

// Παλιό, στατικό όνομα — διατηρείται για συμβατότητα όπου δεν χρειάζεται το
// ΠΡΑΓΜΑΤΙΚΟ engine ανά σάρωση (π.χ. πριν τρέξει κάτι). Για το engine που
// ΟΝΤΩΣ χρησιμοποιήθηκε σε μια σάρωση, δες το `engineUsed` του αποτελέσματος.
export const recognizerName = getOcrEnginePreference() === "tesseract"
  ? "tesseract"
  : "auto";
