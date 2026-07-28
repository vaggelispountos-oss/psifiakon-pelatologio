// services/plateRecognizer/preprocess.js
// --------------------------------------------------------------------
// Προεπεξεργασία εικόνας ΠΡΙΝ το OCR (client-side, canvas — γρήγορο, δωρεάν).
//
// Βήματα:
//   1) upscale       — μεγέθυνση, βοηθά πολύ σε μικρές πλάκες
//   2) grayscale     — μία τιμή φωτεινότητας ανά pixel
//   3) contrast stretch + Otsu threshold -> κατώφλι μαύρου/άσπρου
//   4) ΔΙΠΛΗ ΠΟΛΙΚΟΤΗΤΑ — δοκιμάζουμε ΚΑΙ «σκούρα γράμματα σε ανοιχτό φόντο»
//      ΚΑΙ το αντίστροφο, και κρατάμε όποια δίνει καθαρότερα character blobs
//   5) ΑΦΑΙΡΕΣΗ ΘΟΡΥΒΟΥ — κρατάμε μόνο τα «μελανώματα» που μοιάζουν με
//      χαρακτήρες πινακίδας και πετάμε βίδες, αυτοκόλλητα, πλαίσιο, λωρίδα EU
//   6) τελικό crop στους χαρακτήρες + λευκό περιθώριο
//
// Το (4) υπήρχε αρχικά ΜΟΝΟ ως «σκούρο = χαρακτήρας», που δούλευε μόνο σε
// καθαρές, καλοφωτισμένες πλάκες με μαύρα γράμματα. Αντηλιά, σκιά ή νυχτερινό
// φλας μπορούν να αναστρέψουν οπτικά την αντίθεση (η πλάκα «λάμπει» γύρω από
// τα γράμματα) — τότε η μία πολικότητα βγάζει καθαρούς χαρακτήρες και η άλλη
// θόρυβο. Δοκιμάζοντας και τις δύο, διαλέγουμε αντικειμενικά (μέσω του ίδιου
// φίλτρου θορύβου του βήματος 5) όποια δίνει πιο «πινακιδο-ειδή» αποτέλεσμα.
// --------------------------------------------------------------------

const FG = 0; // μαύρο = χαρακτήρας
const BG = 255; // άσπρο = φόντο

/**
 * @param {HTMLCanvasElement|HTMLImageElement} source - η (ήδη cropped) εικόνα πλάκας
 * @param {{targetWidth?: number, denoise?: boolean, padding?: number}} opts
 * @returns {HTMLCanvasElement} νέο canvas ασπρόμαυρο (binarized), έτοιμο για OCR
 */
export function preprocessForOcr(
  source,
  { targetWidth = 1000, denoise = true, padding = 24 } = {}
) {
  const { gray, w, h, threshold } = grayscaleAndThreshold(source, targetWidth);

  const darkOnLight = toBinary(gray, w, h, threshold, /* invert */ false);
  const lightOnDark = toBinary(gray, w, h, threshold, /* invert */ true);

  let best;
  if (denoise) {
    const a = keepCharacterBlobs(darkOnLight);
    const b = keepCharacterBlobs(lightOnDark);
    best = pickPolarity(a, b).bin;
  } else {
    best = darkOnLight;
  }
  return toCanvas(best, contentBox(best), padding);
}

/**
 * Ελαφρύ, ΓΡΗΓΟΡΟ πέρασμα (χωρίς OCR) που εκτιμά αν το frame της κάμερας
 * δείχνει καθαρά μια πινακίδα — για ζωντανό οπτικό feedback (πράσινο/κόκκινο
 * πλαίσιο) ενώ ο χρήστης ευθυγραμμίζει, ΠΡΙΝ πατήσει «Σκάναρε». Ίδιο pipeline
 * με preprocessForOcr (διπλή πολικότητα + αφαίρεση θορύβου) αλλά σε πολύ
 * μικρότερη ανάλυση και ΧΩΡΙΣ να φτιάξει το τελικό canvas.
 *
 * @returns {{ok: boolean, kept: number}} kept = πόσα «character blobs» βρέθηκαν
 */
export function assessPlateAlignment(source, { targetWidth = 450 } = {}) {
  const { gray, w, h, threshold } = grayscaleAndThreshold(source, targetWidth);
  const darkOnLight = toBinary(gray, w, h, threshold, false);
  const lightOnDark = toBinary(gray, w, h, threshold, true);
  const best = pickPolarity(keepCharacterBlobs(darkOnLight), keepCharacterBlobs(lightOnDark));
  return { ok: best.ok, kept: best.kept };
}

// Μια ελληνική πινακίδα έχει 6 (μηχανή) ή 7 (αυτοκίνητο) χαρακτήρες.
const EXPECTED_CHAR_COUNTS = [6, 7];

/**
 * Διαλέγει ανάμεσα στα δύο αποτελέσματα αφαίρεσης θορύβου (μία ανά πολικότητα).
 *
 * ΠΡΟΣΟΧΗ: όταν η αφαίρεση θορύβου αποτυγχάνει να βρει έγκυρα character blobs,
 * το keepCharacterBlobs() κάνει fallback στο ΑΚΑΤΕΡΓΑΣΤΟ binary (bin.ok=false) —
 * που στη ΛΑΘΟΣ πολικότητα είναι συχνά ένα συμπαγές ορθογώνιο (όλη η πλάκα).
 * Αυτό έχει ΠΕΡΙΣΣΟΤΕΡΑ μαύρα pixel από τους πραγματικούς χαρακτήρες, οπότε
 * ΔΕΝ πρέπει ποτέ να κερδίζει έναντι ενός επιτυχημένου αποτελέσματος — value
 * μεγέθους θα το προτιμούσε λανθασμένα. Προτεραιότητα λοιπόν:
 *   1) επιτυχημένη αφαίρεση θορύβου (ok=true) έναντι αποτυχημένης
 *   2) πλήθος blobs πιο κοντά στο αναμενόμενο (6 ή 7 χαρακτήρες)
 */
function pickPolarity(a, b) {
  if (a.ok !== b.ok) return a.ok ? a : b;
  if (!a.ok) return a; // καμία δεν βρήκε καθαρούς χαρακτήρες· ισοπαλία, κράτα την πρώτη

  const distA = Math.min(...EXPECTED_CHAR_COUNTS.map((n) => Math.abs(n - a.kept)));
  const distB = Math.min(...EXPECTED_CHAR_COUNTS.map((n) => Math.abs(n - b.kept)));
  return distA <= distB ? a : b;
}

// --------------------------------------------------------------------
// 1-3) Upscale + grayscale + contrast stretch + Otsu
// --------------------------------------------------------------------
/** @returns {{gray: Uint8ClampedArray, w: number, h: number, threshold: number}} */
function grayscaleAndThreshold(source, targetWidth) {
  const sw = source.width || source.videoWidth;
  const sh = source.height || source.videoHeight;

  const scale = sw > 0 ? targetWidth / sw : 1;
  const w = Math.max(1, Math.round(sw * scale));
  const h = Math.max(1, Math.round(sh * scale));

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(source, 0, 0, w, h);

  const d = ctx.getImageData(0, 0, w, h).data;
  const n = w * h;

  // Grayscale + εύρεση min/max φωτεινότητας
  const gray = new Uint8ClampedArray(n);
  let min = 255;
  let max = 0;
  for (let i = 0, p = 0; i < d.length; i += 4, p++) {
    const g = (d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114) | 0;
    gray[p] = g;
    if (g < min) min = g;
    if (g > max) max = g;
  }

  // Contrast stretch (normalization) στο [0,255]
  const range = Math.max(1, max - min);
  for (let p = 0; p < n; p++) {
    gray[p] = (((gray[p] - min) * 255) / range) | 0;
  }

  // Otsu threshold — αυτόματο κατώφλι ανάμεσα στις δύο κύριες φωτεινότητες
  const hist = new Array(256).fill(0);
  for (let p = 0; p < n; p++) hist[gray[p]]++;
  let sum = 0;
  for (let t = 0; t < 256; t++) sum += t * hist[t];
  let sumB = 0;
  let wB = 0;
  let maxVar = -1;
  let threshold = 128;
  for (let t = 0; t < 256; t++) {
    wB += hist[t];
    if (wB === 0) continue;
    const wF = n - wB;
    if (wF === 0) break;
    sumB += t * hist[t];
    const mB = sumB / wB;
    const mF = (sum - sumB) / wF;
    const between = wB * wF * (mB - mF) * (mB - mF);
    if (between > maxVar) {
      maxVar = between;
      threshold = t;
    }
  }

  return { gray, w, h, threshold };
}

/**
 * Εφαρμόζει το κατώφλι στις δύο πιθανές πολικότητες.
 *   invert=false -> ό,τι είναι ΠΙΟ ΣΚΟΥΡΟ από το κατώφλι γίνεται χαρακτήρας
 *   invert=true  -> ό,τι είναι ΠΙΟ ΦΩΤΕΙΝΟ από το κατώφλι γίνεται χαρακτήρας
 */
function toBinary(gray, w, h, threshold, invert) {
  const n = w * h;
  const data = new Uint8Array(n);
  for (let p = 0; p < n; p++) {
    const isDark = gray[p] < threshold;
    data[p] = isDark !== invert ? FG : BG;
  }
  return { data, w, h };
}

// --------------------------------------------------------------------
// 4) Αφαίρεση θορύβου — connected component analysis
// --------------------------------------------------------------------
/**
 * Βρίσκει όλα τα συνεκτικά μαύρα «μελανώματα» (blobs) και κρατά μόνο όσα
 * μοιάζουν με χαρακτήρες πινακίδας. Πετάει:
 *   - ψίχουλα και βίδες στερέωσης    (πολύ μικρά)
 *   - το πλαίσιο και τη σκιά         (πολύ ψηλά / πολύ φαρδιά)
 *   - αυτοκόλλητα, λωρίδα EU, «500»  (ύψος πολύ διαφορετικό από τα υπόλοιπα)
 *
 * @returns {{bin: {data,w,h}, ok: boolean, kept: number}}
 *   ok=false όταν το φιλτράρισμα κατέληξε σε λιγότερα από 3 blobs — κάτι
 *   πήγε στραβά (π.χ. λάθος πολικότητα, οι χαρακτήρες ενώθηκαν με το
 *   πλαίσιο). Σε αυτή την περίπτωση `bin` είναι η ΑΚΑΤΕΡΓΑΣΤΗ εικόνα, γιατί
 *   μια κακή αφαίρεση θορύβου είναι χειρότερη από καθόλου — αλλά ο caller
 *   ΠΡΕΠΕΙ να ελέγχει το `ok` πριν συγκρίνει αποτελέσματα (δες pickPolarity),
 *   αλλιώς ένα αποτυχημένο, συμπαγές blob μπερδεύεται για «πλούσιο περιεχόμενο».
 */
function keepCharacterBlobs(bin) {
  const { data, w, h } = bin;
  const n = w * h;
  const labels = new Int32Array(n).fill(-1);
  const stack = new Int32Array(n);
  const blobs = [];

  for (let start = 0; start < n; start++) {
    if (data[start] !== FG || labels[start] !== -1) continue;

    const id = blobs.length;
    let sp = 0;
    stack[sp++] = start;
    labels[start] = id;

    let minX = w;
    let maxX = -1;
    let minY = h;
    let maxY = -1;
    let count = 0;

    // Flood fill (4-connectivity), iterative ώστε να μη σκάει το stack.
    // Κάθε pixel μπαίνει στη στοίβα ΜΙΑ φορά (σημαδεύεται κατά την ώθηση),
    // άρα το stack χωράει σίγουρα.
    while (sp > 0) {
      const p = stack[--sp];
      const x = p % w;
      const y = (p / w) | 0;
      count++;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;

      if (x > 0 && data[p - 1] === FG && labels[p - 1] === -1) {
        labels[p - 1] = id;
        stack[sp++] = p - 1;
      }
      if (x < w - 1 && data[p + 1] === FG && labels[p + 1] === -1) {
        labels[p + 1] = id;
        stack[sp++] = p + 1;
      }
      if (y > 0 && data[p - w] === FG && labels[p - w] === -1) {
        labels[p - w] = id;
        stack[sp++] = p - w;
      }
      if (y < h - 1 && data[p + w] === FG && labels[p + w] === -1) {
        labels[p + w] = id;
        stack[sp++] = p + w;
      }
    }

    blobs.push({ id, count, w: maxX - minX + 1, h: maxY - minY + 1 });
  }

  // Πρώτο φιλτράρισμα: μέγεθος/σχήμα σε σχέση με το καρέ
  const candidates = blobs.filter(
    (b) =>
      b.count >= 30 && // ψίχουλα / θόρυβος του threshold
      b.h >= 0.18 * h && // βίδες, τελείες, μικρά αυτοκόλλητα («R»)
      b.h <= 0.95 * h && // πλαίσιο / σκιά που πιάνει όλο το ύψος
      b.w <= 0.45 * w // οριζόντιες γραμμές πλαισίου
  );
  if (candidates.length < 3) return { bin, ok: false, kept: 0 };

  // Δεύτερο φιλτράρισμα: οι χαρακτήρες μιας πινακίδας έχουν ΙΔΙΟ ύψος.
  // Ό,τι απέχει πολύ από το διάμεσο ύψος δεν είναι χαρακτήρας πινακίδας.
  // (Ισχύει και για δίσειρες πλάκες μηχανής — οι δύο σειρές έχουν ίδιο ύψος.)
  const heights = candidates.map((b) => b.h).sort((a, b) => a - b);
  const median = heights[heights.length >> 1];

  const keep = new Uint8Array(blobs.length);
  let kept = 0;
  for (const b of candidates) {
    if (b.h >= 0.6 * median && b.h <= 1.7 * median) {
      keep[b.id] = 1;
      kept++;
    }
  }
  if (kept < 3) return { bin, ok: false, kept: 0 };

  const out = new Uint8Array(n).fill(BG);
  for (let p = 0; p < n; p++) {
    if (data[p] === FG && keep[labels[p]]) out[p] = FG;
  }
  return { bin: { data: out, w, h }, ok: true, kept };
}

// --------------------------------------------------------------------
// 5) Τελικό crop + περιθώριο
// --------------------------------------------------------------------
/** Bounding box όλων των μαύρων pixel (ό,τι έμεινε μετά το καθάρισμα). */
function contentBox({ data, w, h }) {
  let minX = w;
  let maxX = -1;
  let minY = h;
  let maxY = -1;
  for (let p = 0, y = 0; y < h; y++) {
    for (let x = 0; x < w; x++, p++) {
      if (data[p] !== FG) continue;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
  }
  if (maxX < 0) return { x: 0, y: 0, w, h }; // εντελώς λευκή εικόνα
  return { x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1 };
}

/** Γράφει το box σε νέο canvas με λευκό περιθώριο (το Tesseract το θέλει). */
function toCanvas(bin, box, padding) {
  const canvas = document.createElement("canvas");
  canvas.width = box.w + padding * 2;
  canvas.height = box.h + padding * 2;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });

  const img = ctx.createImageData(canvas.width, canvas.height);
  const out = img.data;
  out.fill(255); // λευκό φόντο + alpha

  for (let y = 0; y < box.h; y++) {
    const srcRow = (box.y + y) * bin.w + box.x;
    const dstRow = (y + padding) * canvas.width + padding;
    for (let x = 0; x < box.w; x++) {
      if (bin.data[srcRow + x] !== FG) continue;
      const i = (dstRow + x) * 4;
      out[i] = out[i + 1] = out[i + 2] = 0;
    }
  }

  ctx.putImageData(img, 0, 0);
  return canvas;
}
