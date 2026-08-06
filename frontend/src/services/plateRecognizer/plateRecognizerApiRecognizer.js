// services/plateRecognizer/plateRecognizerApiRecognizer.js
// --------------------------------------------------------------------
// Αναγνώριση πλάκας μέσω εξειδικευμένου ALPR (Plate Recognizer:
// https://platerecognizer.com — δωρεάν ~2500 αναγνωρίσεις/μήνα, ειδικά
// tuned για πινακίδες, ΠΟΛΥ πιο ακριβές από OCR εγγράφων σαν το Tesseract).
//
// Το API token ΔΕΝ μπαίνει ποτέ εδώ ούτε σε VITE_* env var — κάθε
// import.meta.env.VITE_* καταλήγει στο public JS bundle, ορατό σε
// οποιονδήποτε ανοίγει το site. Αντ' αυτού το frontend καλεί το δικό μας
// backend (POST /api/ocr/plate), το οποίο κρατά το token server-side και
// προωθεί στο Plate Recognizer (δες backend/app.py + backend/config.py).
//
// Ίδιο interface με τον TesseractRecognizer:
//     recognizePlate(imageSource, onProgress?) -> { plate, confidence, ... }
//
// Ενεργοποίηση: VITE_RECOGNIZER=plate_recognizer (δες index.js) + όρισε
// PLATE_RECOGNIZER_TOKEN στο backend/.env.
//
// Σημείωση: το API στέλνει την εικόνα σε εξωτερικό server (του Plate
// Recognizer) — πρόσεξε privacy/όρους πριν το ενεργοποιήσεις σε παραγωγή.
// --------------------------------------------------------------------
import { API_URL } from "../api";
import { parsePlateDetailed } from "../../utils";

/**
 * @param {HTMLCanvasElement|HTMLImageElement} imageSource - περιοχή πλάκας (με λίγο
 *   περιθώριο γύρω — το ALPR κάνει ΔΙΚΟ ΤΟΥ plate detection, οπότε ένα πολύ
 *   στενό crop σαν του Tesseract του αφαιρεί χρήσιμο context αντί να βοηθά)
 * @param {(pct:number)=>void} [onProgress] - το ALPR δεν εκθέτει ενδιάμεση πρόοδο
 */
export async function recognizePlate(imageSource, onProgress) {
  onProgress?.(10);

  const blob = await toBlob(imageSource);

  const form = new FormData();
  form.append("upload", blob, "plate.jpg");

  onProgress?.(40);

  let response;
  try {
    response = await fetch(`${API_URL}/api/ocr/plate`, {
      method: "POST",
      body: form,
    });
  } catch (networkErr) {
    throw new Error(
      `Αποτυχία σύνδεσης με το backend (${API_URL || "relative /api"}). ` +
        `Βεβαιώσου ότι το backend τρέχει. (${networkErr.message})`
    );
  }

  onProgress?.(90);

  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }

  if (!response.ok) {
    throw new Error(
      (data && data.error) || `Σφάλμα ALPR (HTTP ${response.status}).`
    );
  }

  onProgress?.(100);

  // Το Plate Recognizer επιστρέφει το κείμενο ΧΩΡΙΣ παύλα ("iky1833") — το
  // περνάμε από τον ΙΔΙΟ parser με το Tesseract path ώστε ΚΑΙ τα δύο engines
  // να παράγουν την ΙΔΙΑ μορφή ("IKY-1833", λατινικά) και ίδιο validation.
  // Χωρίς αυτό, ο Tesseract path έγραφε "IKY-1833" και το ALPR path έγραφε
  // "IKY1833" στην ΙΔΙΑ βάση/ΑΑΔΕ.
  const rawPlate = data?.plate ? String(data.plate) : "";
  const parsed = parsePlateDetailed(rawPlate);

  return {
    plate: parsed.plate,
    confidence:
      typeof data?.confidence === "number" ? Math.round(data.confidence) : null,
    rawText: rawPlate,
    warnings: parsed.warnings,
    corrected: parsed.corrected,
    // Δεν κάνουμε client-side preprocessing σε αυτό το path — το ALPR
    // δουλεύει πάνω στην αρχική εικόνα, οπότε δεν υπάρχει "OCR input" preview.
    processedDataUrl: null,
    // Εναλλακτικές αναγνώσεις του ALPR (score ανά υποψήφια πινακίδα) — το
    // backend τις υπολογίζει ήδη (δες app.py /api/ocr/plate) αλλά μέχρι τώρα
    // πετάγονταν εδώ. Χρήσιμες για μελλοντικό UI επιλογής/επιβεβαίωσης.
    candidates: Array.isArray(data?.candidates) ? data.candidates : [],
  };
}

function toBlob(source) {
  return new Promise((resolve, reject) => {
    let canvas = source;
    if (!(source instanceof HTMLCanvasElement)) {
      canvas = document.createElement("canvas");
      canvas.width = source.naturalWidth || source.videoWidth || source.width;
      canvas.height = source.naturalHeight || source.videoHeight || source.height;
      canvas.getContext("2d").drawImage(source, 0, 0);
    }
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("toBlob απέτυχε"))),
      "image/jpeg",
      0.92
    );
  });
}

export const name = "plate_recognizer";
