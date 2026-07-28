// services/plateRecognizer/index.js
// --------------------------------------------------------------------
// Pluggable αναγνώριση πλάκας — διαλέγει υλοποίηση χωρίς αλλαγή στη ροή.
//
// Επιλογή μέσω env VITE_RECOGNIZER:
//   "tesseract"         (default) -> δωρεάν, client-side
//   "plate_recognizer"            -> εξειδικευμένο ALPR API (TODO — Μέρος Β)
//
// Όλες οι υλοποιήσεις εκθέτουν:
//     recognizePlate(imageSource, onProgress?) -> Promise<{
//         plate: string|null, confidence: number|null,
//         rawText: string, processedDataUrl?: string
//     }>
// --------------------------------------------------------------------
import * as tesseractRecognizer from "./tesseractRecognizer";
import * as plateRecognizerApiRecognizer from "./plateRecognizerApiRecognizer";

const RECOGNIZER =
  (import.meta.env && import.meta.env.VITE_RECOGNIZER) || "tesseract";

export function getRecognizer() {
  switch (RECOGNIZER) {
    // Χρειάζεται PLATE_RECOGNIZER_TOKEN στο backend/.env (όχι εδώ — δες
    // plateRecognizerApiRecognizer.js). Χωρίς αυτό, το backend γυρνά 503
    // και το CameraCapture δείχνει το μήνυμα σφάλματος με οδηγία fallback.
    case "plate_recognizer":
      return plateRecognizerApiRecognizer;
    case "tesseract":
    default:
      return tesseractRecognizer;
  }
}

export const recognizerName = RECOGNIZER;
