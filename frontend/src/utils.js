// utils.js
// Βοηθητικές συναρτήσεις parsing για πλάκα και ΜΑΡΚ.

// --------------------------------------------------------------------
// Αναγνώριση ελληνικής πινακίδας από (θορυβώδες) κείμενο OCR
// --------------------------------------------------------------------
//
// Οι ελληνικές πινακίδες χρησιμοποιούν ΜΟΝΟ τα 14 γράμματα που έχουν
// λατινικό οπτικό ισοδύναμο (ώστε να διαβάζονται στο εξωτερικό):
//     Α Β Ε Ζ Η Ι Κ Μ Ν Ο Ρ Τ Υ Χ   ->   A B E Z H I K M N O P T Y X
// Το «Γ», «Δ», «Λ», «Φ», «Ψ», «Ω» κ.λπ. ΔΕΝ εμφανίζονται ποτέ.
export const PLATE_LETTERS_LATIN = "ABEZHIKMNOPTYX";
export const PLATE_LETTERS_GREEK = "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ";

const PLATE_LETTER_RE = new RegExp(
  `^[${PLATE_LETTERS_LATIN}${PLATE_LETTERS_GREEK}]+$`
);

// Η ΑΑΔΕ (vehicleRegistrationNumber) και η στήλη plate στη βάση περιμένουν
// ΛΑΤΙΝΙΚΑ γράμματα. Το OCR/ο χρήστης μπορεί να δώσει είτε ελληνικά είτε
// λατινικά (οπτικά ταυτόσημα) — χωρίς ενοποίηση σε ΜΙΑ κανονική μορφή, η
// «ΙΚΧ-1833» και η «IKX-1833» θεωρούνται ΔΙΑΦΟΡΕΤΙΚΟΙ πελάτες (βλ. unique
// constraint plate+workshop στο backend), σπάζοντας silently το matching.
const GREEK_TO_LATIN = {};
for (let i = 0; i < PLATE_LETTERS_GREEK.length; i++) {
  GREEK_TO_LATIN[PLATE_LETTERS_GREEK[i]] = PLATE_LETTERS_LATIN[i];
}

/** Μετατρέπει κάθε ελληνικό γράμμα πινακίδας στο λατινικό αντίστοιχό του. */
function toLatinLetters(str) {
  let out = "";
  for (const ch of str) out += GREEK_TO_LATIN[ch] || ch;
  return out;
}

/**
 * Κανονική μορφή πινακίδας: ΠΑΝΤΑ λατινικά γράμματα, uppercase, "XXX-9999".
 * Εφαρμόζεται σε ΚΑΘΕ πηγή (OCR, χειροκίνητη πληκτρολόγηση) πριν αποθηκευτεί
 * ή σταλεί οπουδήποτε, ώστε να υπάρχει ΜΙΑ αναπαράσταση ανά πινακίδα.
 *
 * @param {string} plate - ήδη σε μορφή "XXX-9999" (ελληνικά ή λατινικά)
 * @returns {string}
 */
export function toCanonicalPlate(plate) {
  if (!plate || typeof plate !== "string") return "";
  return toLatinLetters(plate.trim().toUpperCase());
}

/**
 * Καθαρίζει ελεύθερο χειροκίνητο input σε canonical μορφή, ΧΩΡΙΣ να απαιτεί
 * ήδη τη μορφή "XXX-9999" (ο χρήστης μπορεί να τη γράψει χωρίς παύλα, με
 * μικρά γράμματα, με κενά). Δεν επιβάλλει το σχήμα 3+3/3+4 — μόνο κανονικοποιεί
 * χαρακτήρες, ώστε ο χρήστης να διατηρεί τον έλεγχο του πεδίου διόρθωσης.
 *
 * @param {string} raw
 * @returns {string}
 */
export function normalizePlateInput(raw) {
  if (!raw || typeof raw !== "string") return "";
  const upper = toLatinLetters(raw.toUpperCase());
  // Κράτα μόνο έγκυρους χαρακτήρες πινακίδας (λατινικά γράμματα πινακίδας,
  // ψηφία, παύλα) — πέταξε τυχαία σημεία στίξης/σύμβολα από copy-paste.
  return upper.replace(new RegExp(`[^${PLATE_LETTERS_LATIN}0-9-]`, "g"), "");
}

// Συχνές συγχύσεις OCR. Τις εφαρμόζουμε ΑΝΑ ΘΕΣΗ: η μορφή της πινακίδας
// (3 γράμματα + 3-4 ψηφία) μας λέει τι περιμένουμε σε κάθε θέση, οπότε
// διορθώνουμε στοχευμένα αντί να μαντεύουμε.
//
// ΨΗΦΙΟ που βρέθηκε σε θέση ΓΡΑΜΜΑΤΟΣ -> το αντίστοιχο γράμμα πινακίδας.
const TO_LETTER = {
  0: "O",
  1: "I",
  2: "Z",
  3: "E",
  4: "A",
  7: "T",
  8: "B",
};

// ΓΡΑΜΜΑ που βρέθηκε σε θέση ΨΗΦΙΟΥ -> το αντίστοιχο ψηφίο.
// Σκόπιμα ΣΥΝΤΗΡΗΤΙΚΟ: κάθε επιπλέον αντιστοίχιση αυξάνει τα false positives
// (τυχαία λέξη να περάσει για πινακίδα), και ένα null είναι προτιμότερο από
// μια σιωπηλά λάθος πινακίδα — ο χρήστης έχει πάντα το πεδίο διόρθωσης.
const TO_DIGIT = {
  O: "0",
  Q: "0",
  D: "0",
  I: "1",
  L: "1",
  Z: "2",
  S: "5",
  G: "6",
  T: "7",
  B: "8",
  Ο: "0",
  Ι: "1",
  Ζ: "2",
  Σ: "5",
  Τ: "7",
  Β: "8",
};

const isLetter = (ch) => /[A-ZΑ-Ω]/.test(ch);
const isDigit = (ch) => /\d/.test(ch);

/** Εξαναγκάζει κάθε χαρακτήρα στον σωστό τύπο μέσω του χάρτη συγχύσεων. */
function coerceChars(str, map, isValid) {
  let out = "";
  for (const ch of str) out += isValid(ch) ? ch : map[ch] || ch;
  return out;
}

/** Πόσοι χαρακτήρες έμειναν ως είχαν (= πόσο «σίγουρη» είναι η υπόθεση). */
function countUnchanged(before, after) {
  let n = 0;
  for (let i = 0; i < before.length; i++) if (before[i] === after[i]) n++;
  return n;
}

/**
 * Πέρασμα 1: το OCR ξεχώρισε σωστά γράμματα από ψηφία.
 *
 * Δεχόμαστε ΜΕΓΑΛΥΤΕΡΕΣ ομάδες από το κανονικό και κόβουμε τα περισσεύματα,
 * γιατί ο θόρυβος γύρω από την πλάκα κολλάει χαρακτήρες στις άκρες των ομάδων.
 *
 * @returns {{plate: string, warnings: string[], corrected: boolean}|null}
 */
function matchSeparatedGroups(cleaned) {
  // Το \s? δέχεται το πολύ ένα κενό ώστε να μην πιάσει μακρινούς αριθμούς
  // (π.χ. το «27» του αυτοκόλλητου ΚΤΕΟ).
  const match = cleaned.match(/([A-ZΑ-Ω]{3,})\s?(\d{3,})/);
  if (!match) return null;

  const warnings = [];
  let [, letters, digits] = match;

  // >3 γράμματα -> κράτα τα 3 ΤΕΛΕΥΤΑΙΑ: η λωρίδα EU και τα αυτοκόλλητα
  // (π.χ. το «R») βρίσκονται ΑΡΙΣΤΕΡΑ της πινακίδας, άρα ο θόρυβος μπαίνει
  // στην αρχή της ομάδας.
  if (letters.length > 3) {
    const trimmed = letters.slice(-3);
    // Η περικοπή είναι επικίνδυνη: κάθε λέξη κόβεται σε «πινακίδα» (π.χ.
    // «CIVIC 2020» -> «VIC-2020»). Την επιτρέπουμε μόνο αν ό,τι μένει ανήκει
    // όντως στο αλφάβητο πινακίδας.
    if (!PLATE_LETTER_RE.test(trimmed)) return null;
    warnings.push(
      `διάβασα ${letters.length} γράμματα («${letters}») — κράτησα τα 3 τελευταία`
    );
    letters = trimmed;
  }

  // >4 ψηφία -> κράτα τα 4 ΤΕΛΕΥΤΑΙΑ. Ο διαχωριστής ανάμεσα σε γράμματα και
  // ψηφία (παύλα + βίδα στερέωσης) διαβάζεται πολύ συχνά ως ψηφίο:
  // «ΙΚΧ-1833» -> «IKX21833». Ο θόρυβος είναι δηλαδή ΜΠΡΟΣΤΑ από τα ψηφία.
  if (digits.length > 4) {
    warnings.push(
      `διάβασα ${digits.length} ψηφία («${digits}») — κράτησα τα 4 τελευταία`
    );
    digits = digits.slice(-4);
  }

  return {
    plate: `${toLatinLetters(letters)}-${digits}`,
    warnings,
    corrected: warnings.length > 0,
  };
}

/**
 * Καθαρίζει/κανονικοποιεί κείμενο OCR σε πιθανή ελληνική πινακίδα και
 * επιστρέφει ΚΑΙ τις επιφυλάξεις της ανάλυσης, ώστε το UI να μπορεί να
 * προειδοποιήσει τον χρήστη αντί να του σερβίρει σιωπηλά μια εικασία.
 *
 * Μορφή: 3 γράμματα + 3 ψηφία (ΜΗΧΑΝΗ, π.χ. ΟΤΜ-776)
 *        ή 3 γράμματα + 4 ψηφία (ΑΥΤΟΚΙΝΗΤΟ, π.χ. ΑΒΓ-1234)
 *
 * @returns {{plate: string|null, warnings: string[], corrected: boolean}}
 */
export function parsePlateDetailed(ocrText) {
  const empty = { plate: null, warnings: [], corrected: false };
  if (!ocrText || typeof ocrText !== "string") return empty;

  // Uppercase· κάθε μη-αλφαριθμητικό (και οι αλλαγές γραμμής των διπλών
  // πλακών μηχανής) γίνεται ΚΕΝΟ — τα κενά τα ΚΡΑΤΑΜΕ ως όρια ομάδων,
  // ώστε να μη «κολλήσουμε» ψηφία από διπλανά αυτοκόλλητα (π.χ. το «27» ΚΤΕΟ).
  const cleaned = ocrText
    .toUpperCase()
    .replace(/[^A-ZΑ-Ω0-9]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    // Αγνόησε το EU country band «GR» (είναι πάντα ξεχωριστό token)
    .replace(/\bGR\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!cleaned) return empty;

  // ---- Πέρασμα 1: το OCR ξεχώρισε σωστά γράμματα από ψηφία ----
  const direct = matchSeparatedGroups(cleaned);
  if (direct) return direct;

  // ---- Πέρασμα 2: ο διαχωρισμός γραμμάτων/ψηφίων ΑΠΕΤΥΧΕ ----
  // Τυπική περίπτωση: το «Ι» διαβάστηκε «1» ή το «Ο» διαβάστηκε «0», οπότε η
  // ομάδα γραμμάτων έγινε πολύ κοντή για να ταιριάξει παραπάνω. Δοκιμάζουμε
  // κάθε παράθυρο 7 (αυτοκίνητο) και 6 (μηχανή) χαρακτήρων, εξαναγκάζοντας τη
  // μορφή, και κρατάμε αυτό που χρειάστηκε τις ΛΙΓΟΤΕΡΕΣ διορθώσεις.
  const flat = cleaned.replace(/\s/g, "");
  let best = null;

  for (const len of [7, 6]) {
    const digitCount = len - 3;
    const digitRe = new RegExp(`^\\d{${digitCount}}$`);

    for (let i = 0; i + len <= flat.length; i++) {
      const win = flat.slice(i, i + len);
      const rawLetters = win.slice(0, 3);
      const rawDigits = win.slice(3);
      const letters = coerceChars(rawLetters, TO_LETTER, isLetter);
      const digits = coerceChars(rawDigits, TO_DIGIT, isDigit);

      // Σε αυτό το «χαλαρό» πέρασμα απαιτούμε τα γράμματα να ανήκουν όντως στο
      // αλφάβητο πινακίδας, αλλιώς περνάνε για πινακίδες τυχαίες λέξεις.
      if (letters.length !== 3 || !PLATE_LETTER_RE.test(letters)) continue;
      if (!digitRe.test(digits)) continue;

      const score =
        countUnchanged(rawLetters, letters) + countUnchanged(rawDigits, digits);
      if (!best || score > best.score) {
        best = { score, letters, digits, raw: win };
      }
    }
  }

  if (!best) return empty;

  return {
    plate: `${toLatinLetters(best.letters)}-${best.digits}`,
    warnings: [
      `το OCR δεν ξεχώρισε γράμματα/ψηφία («${best.raw}») — υπέθεσα τη μορφή`,
    ],
    corrected: true,
  };
}

/**
 * Ψάχνει στις ΓΝΩΣΤΕΣ πινακίδες (πελάτες του συνεργείου) για μία που διαφέρει
 * ΑΚΡΙΒΩΣ 1 χαρακτήρα από αυτή που διάβασε το OCR — π.χ. «IKX-1833» (OCR) vs
 * «IKX-1533» (γνωστός πελάτης). Δεν είναι OCR correction μέσω κανόνων (όπως
 * το TO_LETTER/TO_DIGIT πιο πάνω) αλλά αξιοποίηση δεδομένων: αν ο πελάτης
 * έχει ξαναέρθει, η ΠΙΟ ΠΙΘΑΝΗ εξήγηση μιας μικρής απόκλισης είναι λάθος
 * ανάγνωση, όχι νέο όχημα με σχεδόν ίδια πινακίδα.
 *
 * Επιστρέφει null αν:
 *   - η πινακίδα ΗΔΗ ταιριάζει ακριβώς με γνωστή (καμία διόρθωση χρειάζεται)
 *   - καμία γνωστή πινακίδα δεν είναι αρκετά κοντά
 *   - ΠΑΝΩ ΑΠΟ ΜΙΑ γνωστές πινακίδες είναι εξίσου κοντά (ασαφές -> δεν
 *     μαντεύουμε, ο χρήστης έχει το πεδίο διόρθωσης)
 *
 * @param {string} plate - πινακίδα σε μορφή "XXX-999" (π.χ. αποτέλεσμα OCR)
 * @param {Array<{plate: string}>} knownPlates
 * @param {{maxDistance?: number}} [opts]
 * @returns {{plate: string}|null} το αντικείμενο από το knownPlates που ταιριάζει
 */
export function findClosestKnownPlate(plate, knownPlates, { maxDistance = 1 } = {}) {
  const target = toCanonicalPlate(plate).replace(/-/g, "");
  if (!target || !Array.isArray(knownPlates) || !knownPlates.length) return null;

  let best = null;
  let bestDist = Infinity;
  let ambiguous = false;

  for (const known of knownPlates) {
    const candidate = toCanonicalPlate(known.plate || "").replace(/-/g, "");
    if (!candidate || candidate.length !== target.length) continue;
    if (candidate === target) return null; // ήδη γνωστή, ακριβής — καμία πρόταση

    let dist = 0;
    for (let i = 0; i < candidate.length; i++) {
      if (candidate[i] !== target[i]) dist++;
    }

    if (dist < bestDist) {
      bestDist = dist;
      best = known;
      ambiguous = false;
    } else if (dist === bestDist) {
      ambiguous = true;
    }
  }

  if (best && !ambiguous && bestDist > 0 && bestDist <= maxDistance) return best;
  return null;
}

/**
 * Απλή μορφή της parsePlateDetailed (μόνο η πινακίδα).
 *
 * @returns {string|null} την πινακίδα σε μορφή "ABG-1234" ή null αν δεν βρεθεί.
 */
export function parsePlate(ocrText) {
  return parsePlateDetailed(ocrText).plate;
}

/**
 * Εξάγει τον ΜΑΡΚ από το περιεχόμενο ενός QR απόδειξης.
 *
 * Η μορφή διαφέρει ανά ΦΗΜ / πάροχο. Το QR μπορεί να περιέχει:
 *   - σκέτο ΜΑΡΚ (μεγάλος αριθμός)
 *   - URL με query parameters (π.χ. ?mark=... ή ?MARK=...)
 *   - δομημένο κείμενο (key=value, ή χωρισμένο με ; ή |)
 *
 * Στρατηγική:
 *   1. Αν είναι URL, κοίτα πρώτα σε γνωστά query params (mark, aade, uid...).
 *   2. Αλλιώς ψάξε για μεγάλη ακολουθία ψηφίων (ο ΜΑΡΚ είναι μεγάλος αριθμός).
 *   3. Αν δεν βρεθεί τίποτα, επίστρεψε null.
 *
 * @param {string} qrText
 * @returns {string|null}
 */
export function parseMark(qrText) {
  if (!qrText || typeof qrText !== "string") return null;
  const text = qrText.trim();

  // Πιθανά ονόματα παραμέτρων/κλειδιών που κρατούν τον ΜΑΡΚ
  const MARK_KEYS = ["mark", "markid", "aade", "aademark", "uid", "m"];

  // --- 1) URL; ---
  if (/^https?:\/\//i.test(text)) {
    try {
      const url = new URL(text);
      // 1a) γνωστά query params
      for (const [key, val] of url.searchParams.entries()) {
        if (MARK_KEYS.includes(key.toLowerCase()) && /^\d{8,}$/.test(val)) {
          return val;
        }
      }
      // 1b) οποιοδήποτε query param που είναι μεγάλος αριθμός
      for (const [, val] of url.searchParams.entries()) {
        const m = val.match(/\d{8,}/);
        if (m) return m[0];
      }
      // 1c) ψάξε στο path
      const pathMatch = url.pathname.match(/\d{8,}/);
      if (pathMatch) return pathMatch[0];
    } catch {
      // αγνόησε — θα πέσουμε στο generic search παρακάτω
    }
  }

  // --- 2) key=value δομημένο κείμενο (mark=...) ---
  const kvMatch = text.match(/(?:mark|aade|uid)\s*[=:]\s*(\d{8,})/i);
  if (kvMatch) return kvMatch[1];

  // --- 3) Γενικό: βρες τη ΜΕΓΑΛΥΤΕΡΗ ακολουθία ψηφίων ---
  const allNumbers = text.match(/\d{8,}/g);
  if (allNumbers && allNumbers.length > 0) {
    return allNumbers.sort((a, b) => b.length - a.length)[0];
  }

  return null;
}
