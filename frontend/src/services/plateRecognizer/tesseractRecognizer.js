// services/plateRecognizer/tesseractRecognizer.js
// --------------------------------------------------------------------
// Υλοποίηση αναγνώρισης πλάκας με Tesseract.js (δωρεάν, client-side).
//
// ⚠️ ΟΡΙΑ: το Tesseract είναι OCR ΕΓΓΡΑΦΩΝ — εκπαιδευμένο σε γραμματοσειρές
// κειμένου, όχι στη γραμματοσειρά πινακίδας, και δεν έχει καμία γνώση της
// μορφής «3 γράμματα + 4 ψηφία». Ακόμα και τέλεια ρυθμισμένο πιάνει ρεαλιστικά
// ~70% σε πραγματικές συνθήκες. Για παραγωγή χρειάζεται εξειδικευμένο ALPR
// (δες plateRecognizerApiRecognizer.js).
//
// Τι κάνουμε εδώ για να πάρουμε ό,τι δίνει:
//   - whitelist ΜΟΝΟ στους χαρακτήρες που υπάρχουν σε ελληνική πινακίδα
//   - δύο περάσματα (μονή γραμμή / μπλοκ) και κρατάμε το καλύτερο
//   - πραγματικό confidence από τα words (το data.confidence είναι 0 στη v5)
//
// Interface (κοινό με τυχόν μελλοντικό ALPR API):
//     recognizePlate(imageSource, onProgress?, opts?) -> Promise<{
//         plate, confidence, rawText, warnings, corrected, processedDataUrl
//     }>
// --------------------------------------------------------------------
import Tesseract from "tesseract.js";
import { parsePlateDetailed, PLATE_LETTERS_LATIN } from "../../utils";
import { preprocessForOcr } from "./preprocess";

// Οι ελληνικές πλάκες χρησιμοποιούν ΜΟΝΟ τα 14 λατινικά-όμοια κεφαλαία:
// Α Β Ε Ζ Η Ι Κ Μ Ν Ο Ρ Τ Υ Χ -> A B E Z H I K M N O P T Y X (+ ψηφία).
// Κόβοντας τα υπόλοιπα 12 γράμματα (C D F G J L Q R S U V W) γλιτώνουμε τις
// πιο συχνές λάθος αναγνώσεις — π.χ. το «R» των αυτοκόλλητων στο πλαίσιο.
const WHITELIST = PLATE_LETTERS_LATIN + "0123456789";

// PSM (page segmentation mode) — τι σχήμα κειμένου να περιμένει:
//   7 = ΜΙΑ γραμμή κειμένου  -> πλάκα αυτοκινήτου
//   6 = ενιαίο μπλοκ         -> ΔΙΣΕΙΡΗ πλάκα μηχανής (γράμματα πάνω, ψηφία κάτω)
// Τρέχουμε και τα δύο και κρατάμε το καλύτερο· η σειρά ορίζεται από το mode,
// ώστε σε ισοπαλία να κερδίζει το πιθανότερο για τον τύπο οχήματος.
const PASS_CAR = { psm: "7", label: "μονή γραμμή" };
const PASS_MOTO = { psm: "6", label: "μπλοκ" };

let workerPromise = null;
let progressHandler = null;

async function getWorker() {
  if (!workerPromise) {
    workerPromise = Tesseract.createWorker("eng", 1, {
      logger: (m) => {
        if (m.status === "recognizing text" && progressHandler) {
          progressHandler(m.progress);
        }
      },
    });
  }
  return workerPromise;
}

/**
 * Μέσο confidence από τα words. Στο tesseract.js v5 το `data.confidence`
 * δεν συμπληρώνεται σε αυτό το path (βγαίνει σταθερά 0) — η πραγματική τιμή
 * είναι ανά λέξη, είτε στο `data.words` είτε φωλιασμένη μέσα στα blocks.
 */
function meanConfidence(data) {
  const scores = collectWords(data)
    .map((word) => word.confidence)
    .filter((c) => typeof c === "number" && c > 0);
  if (scores.length) {
    return Math.round(scores.reduce((a, b) => a + b, 0) / scores.length);
  }
  if (typeof data.confidence === "number" && data.confidence > 0) {
    return Math.round(data.confidence);
  }
  return null;
}

function collectWords(data) {
  if (Array.isArray(data.words) && data.words.length) return data.words;
  const words = [];
  for (const block of data.blocks || []) {
    for (const para of block.paragraphs || []) {
      for (const line of para.lines || []) {
        words.push(...(line.words || []));
      }
    }
  }
  return words;
}

/** Προτεραιότητα: βρήκε πινακίδα > δεν χρειάστηκε μπάλωμα > ψηλό confidence. */
function scoreOf(c) {
  return (
    (c.plate ? 1000 : 0) +
    (c.plate && !c.corrected ? 500 : 0) +
    (c.confidence || 0)
  );
}

/**
 * @param {HTMLCanvasElement|HTMLImageElement} imageSource - (ήδη cropped) περιοχή πλάκας
 * @param {(pct:number)=>void} [onProgress]
 * @param {{mode?: "car"|"moto"}} [opts]
 */
export async function recognizePlate(imageSource, onProgress, opts = {}) {
  const { mode = "car" } = opts;

  // 1) Προεπεξεργασία (binarize + αφαίρεση θορύβου + crop στους χαρακτήρες)
  const processed = preprocessForOcr(imageSource, { targetWidth: 1000 });

  // 2) OCR — δύο περάσματα πάνω στην ΙΔΙΑ καθαρή εικόνα
  const worker = await getWorker();
  const passes =
    mode === "moto" ? [PASS_MOTO, PASS_CAR] : [PASS_CAR, PASS_MOTO];
  const candidates = [];

  try {
    for (let i = 0; i < passes.length; i++) {
      const pass = passes[i];
      // Το progress κάθε περάσματος καταλαμβάνει το δικό του κομμάτι της μπάρας
      progressHandler = onProgress
        ? (p) => onProgress(Math.round(((i + p) / passes.length) * 100))
        : null;

      await worker.setParameters({
        tessedit_char_whitelist: WHITELIST,
        tessedit_pageseg_mode: pass.psm,
        // Δηλώνουμε ρητά DPI: η εικόνα μας είναι συνθετική (upscaled crop) και
        // η αυτόματη εκτίμηση του Tesseract βγάζει παράλογες τιμές.
        user_defined_dpi: "300",
      });

      const { data } = await worker.recognize(processed);
      const rawText = (data.text || "").trim();
      candidates.push({
        pass,
        rawText,
        confidence: meanConfidence(data),
        ...parsePlateDetailed(rawText),
      });
    }
  } finally {
    progressHandler = null;
  }

  // 3) Κράτα το καλύτερο πέρασμα
  const best = candidates.reduce((a, b) => (scoreOf(b) > scoreOf(a) ? b : a));

  return {
    plate: best.plate,
    confidence: best.confidence,
    rawText: best.rawText,
    warnings: best.warnings,
    corrected: best.corrected,
    processedDataUrl: processed.toDataURL("image/png"),
  };
}

export const name = "tesseract";
