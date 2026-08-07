// components/CameraCapture.jsx
// --------------------------------------------------------------------
// Κάμερα + αναγνώριση πινακίδας (pluggable recognizer — τώρα Tesseract).
// - Πλαίσιο-οδηγός (overlay) στο κέντρο: ο χρήστης ευθυγραμμίζει την πλάκα.
// - Το OCR τρέχει ΜΟΝΟ στην περιοχή του πλαισίου (crop) -> λιγότερος θόρυβος.
// - Προεπεξεργασία (grayscale/contrast/threshold) + preview τι «είδε» το OCR.
// - ΠΑΝΤΑ διαθέσιμο πεδίο χειροκίνητης διόρθωσης.
// --------------------------------------------------------------------
import { useEffect, useRef, useState } from "react";
import { getRecognizer, recognizerName } from "../services/plateRecognizer";
import { logOcrAttempt, confirmOcrMetric, getCustomerPlates } from "../services/api";
import { VEHICLE_MOVEMENT_PURPOSES } from "../constants";
import {
  normalizePlateInput,
  findClosestKnownPlate,
  PLATE_LETTERS_LATIN,
} from "../utils";
// Ελαφρύ heuristic (χωρίς OCR) για ζωντανό feedback ευθυγράμμισης — δουλεύει
// πάνω στο ίδιο pipeline denoising ανεξάρτητα από το ποιος recognizer είναι
// ενεργός (Tesseract ή μελλοντικό ALPR), γι' αυτό εισάγεται απευθείας.
import {
  assessPlateAlignment,
  MIN_SHARPNESS,
  MIN_BRIGHTNESS,
  MAX_BRIGHTNESS,
} from "../services/plateRecognizer/preprocess";

// Πόσο συχνά ελέγχουμε την ευθυγράμμιση ζωντανά (ms). Αρκετά γρήγορο ώστε να
// νιώθει «ζωντανό», αρκετά αραιό ώστε να μην επιβαρύνει παλιότερα κινητά.
const ALIGN_CHECK_MS = 350;

// Αναμενόμενος αριθμός χαρακτήρων ανά τύπο οχήματος (μηχανή: 3+3, αυτοκίνητο:
// 3+4). Ανεχόμαστε ΕΝΑ λιγότερο blob: σε μικρή ανάλυση (γρήγορο ζωντανό
// check) δύο γειτονικά γράμματα μπορεί να «κολλήσουν» οπτικά χωρίς αυτό να
// σημαίνει ότι η πλάκα δεν είναι στην πραγματικότητα ευανάγνωστη — ένα
// αυστηρό exact-match θα έμενε κόκκινο ακόμα και σε σωστή ευθυγράμμιση.
const EXPECTED_CHARS = { car: 7, moto: 6 };
function looksAligned(mode, ok, kept, sharp) {
  // sharp: ΕΠΙΠΛΕΟΝ πύλη πάνω στο ήδη υπάρχον blob-count heuristic — ένα
  // κουνημένο/θολό frame μπορεί ΤΥΧΑΙΑ να βρει αρκετά blobs (π.χ. θόρυβος
  // συμπτωματικά «μοιάζει» με χαρακτήρες) και να γίνει πράσινο ενώ στην
  // πραγματικότητα δεν είναι αναγνώσιμο. Χωρίς αυτό, το auto-scan θα
  // σκανάριζε (και θα απέτυχε ή θα διάβαζε λάθος) σε κάθε κούνημα χεριού.
  return ok && kept >= EXPECTED_CHARS[mode] - 1 && sharp;
}

// Πόσο πλάτος του πλαισίου-οδηγού πρέπει να καλύπτουν οι χαρακτήρες
// άκρη-σε-άκρη ώστε η απόσταση να θεωρείται καλή. Κάτω απ' αυτό η πλάκα
// «πνίγεται» σε φόντο (μακριά)· πάνω απ' αυτό αγγίζει τις άκρες (κοντά,
// ρίσκο να κοπεί χαρακτήρας ή να θολώσει η εστίαση).
const MIN_COVERAGE = 0.5;
const MAX_COVERAGE = 0.93;

// Πόσα συνεχόμενα «πράσινα» περάσματα χρειάζονται πριν σκανάρει μόνο του —
// ένα-δύο τυχαία frames δεν αρκούν, θέλουμε να είναι σταθερά ευθυγραμμισμένη.
const AUTO_SCAN_STABLE_TICKS = 2;

// Πλαίσιο-οδηγός ανά τύπο οχήματος. Το σχήμα του πλαισίου έχει ΤΕΡΑΣΤΙΑ
// σημασία: ό,τι περισσεύει γύρω από την πλάκα (προφυλακτήρας, βίδες,
// αυτοκόλλητα) μπαίνει στο OCR ως θόρυβος. Ένα τετραγωνισμένο πλαίσιο πάνω σε
// πλάκα αυτοκινήτου (αναλογία ~4.7:1) είναι κατά ~75% σκουπίδια.
const GUIDES = {
  car: { widthFrac: 0.82, aspect: 520 / 110, label: "Πλάκα αυτοκινήτου εδώ" },
  moto: { widthFrac: 0.46, aspect: 1.25, label: "Πλάκα μηχανής εδώ" },
};

/**
 * Το <video> προβάλλεται με `object-fit: cover` μέσα σε κουτί 4:3, οπότε αν το
 * καρέ της κάμερας έχει άλλη αναλογία (τυπικά 16:9) ΚΟΒΟΝΤΑΙ οι άκρες του.
 * Ο χρήστης ευθυγραμμίζει την πλάκα με ό,τι ΒΛΕΠΕΙ — άρα το crop πρέπει να
 * υπολογιστεί πάνω στο ορατό κομμάτι, όχι σε όλο το καρέ.
 *
 * @returns {{x:number,y:number,w:number,h:number}} το ορατό παράθυρο σε pixel βίντεο
 */
function visibleVideoRect(video, boxW, boxH) {
  const vw = video.videoWidth || 640;
  const vh = video.videoHeight || 480;
  if (!boxW || !boxH) return { x: 0, y: 0, w: vw, h: vh };

  const scale = Math.max(boxW / vw, boxH / vh); // cover = γέμισε το κουτί
  const w = Math.min(vw, boxW / scale);
  const h = Math.min(vh, boxH / scale);
  return { x: (vw - w) / 2, y: (vh - h) / 2, w, h };
}

/**
 * Υπολογίζει το crop-rect του πλαισίου-οδηγού σε συντεταγμένες βίντεο.
 * Χρησιμοποιείται ΚΑΙ από το πραγματικό «Σκάναρε» ΚΑΙ από το ζωντανό
 * alignment-check, ώστε να βλέπουν πάντα ΑΚΡΙΒΩΣ το ίδιο παράθυρο.
 *
 * @param {number} [expand] - πολλαπλασιαστής μεγέθους γύρω από το ΚΕΝΤΡΟ του
 *   πλαισίου-οδηγού (1 = ακριβώς το πλαίσιο). Το εξειδικευμένο ALPR κάνει ΔΙΚΟ
 *   ΤΟΥ plate detection και αποδίδει καλύτερα με λίγο context γύρω από την
 *   πλάκα, σε αντίθεση με το Tesseract που θέλει το ΣΤΕΝΟ crop (λιγότερος
 *   θόρυβος για το δικό του blob-based denoising).
 */
function computeCropRect(video, frame, mode, expand = 1) {
  if (!video || !frame) return null;
  const box = frame.getBoundingClientRect();
  if (!box.width || !box.height) return null;
  const view = visibleVideoRect(video, box.width, box.height);
  const guide = GUIDES[mode];

  const guideW = guide.widthFrac * box.width * expand;
  const guideH = (guideW / expand / guide.aspect) * expand;
  const sw = Math.min(view.w, Math.max(1, Math.round((guideW / box.width) * view.w)));
  const sh = Math.min(view.h, Math.max(1, Math.round((guideH / box.height) * view.h)));
  const sx = Math.round(view.x + (view.w - sw) / 2);
  const sy = Math.round(view.y + (view.h - sh) / 2);
  return { sx, sy, sw, sh };
}

/** Παίρνει ένα crop-rect (σε συντ. βίντεο) και επιστρέφει canvas με το περιεχόμενο. */
function drawCrop(video, rect) {
  const { sx, sy, sw, sh } = rect;
  const canvas = document.createElement("canvas");
  canvas.width = sw;
  canvas.height = sh;
  canvas.getContext("2d").drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);
  return canvas;
}

// Πόσο μεγαλύτερο (γύρω από το ίδιο κέντρο) είναι το crop που στέλνουμε στο
// εξωτερικό ALPR σε σχέση με το στενό πλαίσιο-οδηγό του Tesseract.
const ALPR_CROP_EXPAND = 1.6;

// Multi-frame consensus (μόνο για Tesseract — δες σχόλιο στο captureAndRecognize
// για γιατί το ALPR εξαιρείται): μία μεμονωμένη ανάγνωση μπορεί να πέσει πάνω
// σε ένα τυχαία κακό frame (θόλωμα ανάμεσα σε δύο σταθερά καρέ, αντανάκλαση).
// Παίρνοντας 2-3 ΞΕΧΩΡΙΣΤΑ frames και απαιτώντας συμφωνία, ένα μεμονωμένο λάθος
// φιλτράρεται αντί να καταλήξει κατευθείαν στο πεδίο.
const MAX_CONSENSUS_ATTEMPTS = 3;
// Μικρή παύση ανάμεσα σε διαδοχικές λήψεις ώστε να είναι ΠΡΑΓΜΑΤΙΚΑ διαφορετικό
// frame (όχι το ίδιο καρέ βίντεο ξανά) — αρκετό για φυσικό μικροκούνημα χεριού.
const CONSENSUS_FRAME_DELAY_MS = 180;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Συνδυάζει πολλαπλές σαρώσεις (attempts) σε ΜΙΑ απόφαση:
 *   - αν ≥2 συμφωνούν ΑΚΡΙΒΩΣ στην ίδια πινακίδα -> αυτή, με το υψηλότερο
 *     confidence ανάμεσα στις συμφωνούσες
 *   - αλλιώς, αν βρέθηκε έστω μία πινακίδα -> η πιο σίγουρη μεμονωμένη,
 *     αλλά σημαδεμένη `disagreement: true` ώστε το UI να το δείξει ρητά
 *   - αν καμία σάρωση δεν βρήκε πινακίδα -> null αποτέλεσμα
 */
function resolveConsensus(attempts) {
  const found = attempts.filter((a) => a.plate);
  const counts = new Map();
  for (const a of found) counts.set(a.plate, (counts.get(a.plate) || 0) + 1);

  let majorityPlate = null;
  let majorityCount = 0;
  for (const [p, count] of counts) {
    if (count > majorityCount) {
      majorityCount = count;
      majorityPlate = p;
    }
  }

  if (majorityPlate && majorityCount >= 2) {
    const agreeing = found.filter((a) => a.plate === majorityPlate);
    const best = agreeing.reduce((a, b) => ((b.confidence || 0) > (a.confidence || 0) ? b : a));
    return {
      ...best,
      plate: majorityPlate,
      agree: majorityCount,
      total: attempts.length,
      disagreement: false,
    };
  }

  if (found.length) {
    const best = found.reduce((a, b) => ((b.confidence || 0) > (a.confidence || 0) ? b : a));
    return {
      ...best,
      agree: 1,
      total: attempts.length,
      // Πάνω από 1 ΔΙΑΦΟΡΕΤΙΚΗ πινακίδα βρέθηκε -> γνήσια ασυμφωνία, όχι απλά
      // "δεν ξαναδοκιμάσαμε" (occurs when MAX_CONSENSUS_ATTEMPTS καλύφθηκε
      // χωρίς καμία να επαναληφθεί).
      disagreement: found.length > 1,
    };
  }

  const last = attempts[attempts.length - 1] || {};
  return { ...last, plate: null, agree: 0, total: attempts.length, disagreement: false };
}

// Μορφή πινακίδας που μπορεί να επεξεργαστεί ο χαρακτήρας-ανά-χαρακτήρα editor
// παρακάτω — 3 γράμματα + 3 ή 4 ψηφία. Ό,τι δεν ταιριάζει (π.χ. ο χρήστης
// έγραψε κάτι εντελώς χειροκίνητα) γυρνά στο απλό ελεύθερο πεδίο κειμένου.
const VERIFIABLE_PLATE_RE = /^([A-Z]{3})-(\d{3,4})$/;

/**
 * Editor «ένα κουτί ανά χαρακτήρα» για τη φάση επιβεβαίωσης χαμηλής
 * βεβαιότητας — μεγάλα, ξεχωριστά πλαίσια είναι πιο εύκολο να ελεγχθούν
 * γρήγορα με μια ματιά απ' ό,τι ένα ενιαίο string, και ο περιορισμός ανά
 * θέση (γράμμα πινακίδας / ψηφίο) αποτρέπει τυπογραφικά που θα παρήγαγαν
 * μη-έγκυρη μορφή.
 */
function PlateVerifyEditor({ plate, onChange }) {
  const match = VERIFIABLE_PLATE_RE.exec(plate || "");
  if (!match) return null;
  const [, letters, digits] = match;

  function setChar(isLetters, index, raw) {
    const ch = raw.slice(-1).toUpperCase();
    if (isLetters) {
      if (ch && !PLATE_LETTERS_LATIN.includes(ch)) return;
      const next = letters.slice(0, index) + (ch || letters[index]) + letters.slice(index + 1);
      onChange(`${next}-${digits}`);
    } else {
      if (ch && !/[0-9]/.test(ch)) return;
      const next = digits.slice(0, index) + (ch || digits[index]) + digits.slice(index + 1);
      onChange(`${letters}-${next}`);
    }
  }

  return (
    <div className="plate-verify-editor">
      {letters.split("").map((c, i) => (
        <input
          key={`l${i}`}
          className="plate-char-input"
          value={c}
          maxLength={1}
          onChange={(e) => setChar(true, i, e.target.value)}
        />
      ))}
      <span className="plate-char-dash">-</span>
      {digits.split("").map((c, i) => (
        <input
          key={`d${i}`}
          className="plate-char-input"
          value={c}
          maxLength={1}
          inputMode="numeric"
          onChange={(e) => setChar(false, i, e.target.value)}
        />
      ))}
    </div>
  );
}

export default function CameraCapture({ onConfirm, disabled, isRental }) {
  const videoRef = useRef(null);
  const frameRef = useRef(null);
  const streamRef = useRef(null);

  const [mode, setMode] = useState("car");
  // Ενοικιάσεις — υποχρεωτικά/προαιρετικά πεδία του 1ου Χρόνου (rental useCase)
  const [movementPurpose, setMovementPurpose] = useState("");
  const [diffPickupLocation, setDiffPickupLocation] = useState(false);
  const [pickupLocation, setPickupLocation] = useState("");
  const [cameraOn, setCameraOn] = useState(false);
  const [ocrRunning, setOcrRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [plate, setPlate] = useState("");
  const [error, setError] = useState("");
  const [confidence, setConfidence] = useState(null);
  const [rawText, setRawText] = useState("");
  const [warnings, setWarnings] = useState([]);
  // Ποιο engine ΠΡΑΓΜΑΤΙΚΑ απάντησε στην τελευταία σάρωση (μετά από τυχόν
  // fallback ALPR -> Tesseract) — βλ. services/plateRecognizer/index.js.
  const [engineUsed, setEngineUsed] = useState(null);
  const [engineFallback, setEngineFallback] = useState(false);
  // Multi-frame consensus (μόνο Tesseract, δες captureAndRecognize): πόσες
  // από τις σαρώσεις συμφώνησαν, και αν υπήρξε γνήσια ασυμφωνία.
  const [consensusAgree, setConsensusAgree] = useState(null);
  const [consensusTotal, setConsensusTotal] = useState(null);
  const [disagreement, setDisagreement] = useState(false);
  // Εικόνα ΑΚΡΙΒΩΣ όπως στάλθηκε για αναγνώριση — σε αντίθεση με το `preview`
  // (μόνο Tesseract, ΜΕΤΑ την προεπεξεργασία), αυτή υπάρχει ΠΑΝΤΑ, ώστε η
  // οθόνη επιβεβαίωσης να έχει πάντα εικόνα ελέγχου ανεξαρτήτως engine.
  const [rawCropPreview, setRawCropPreview] = useState(null);
  // Explicit επιβεβαίωση του χρήστη όταν η ανάγνωση ΔΕΝ είναι αρκετά σίγουρη
  // (δες needsVerification) — το κουμπί δημιουργίας μένει κλειδωμένο μέχρι
  // τότε, ώστε μια αβέβαιη ανάγνωση να μην περάσει σιωπηλά χωρίς έλεγχο.
  const [verified, setVerified] = useState(false);
  const [preview, setPreview] = useState(null); // dataURL προεπεξεργασμένης εικόνας
  const [aligned, setAligned] = useState(false); // ζωντανό feedback πλαισίου
  const [flashSupported, setFlashSupported] = useState(false);
  const [flashOn, setFlashOn] = useState(false);
  // Κατεύθυνση διόρθωσης απόστασης ("closer" | "back" | null) — ζωντανό hint
  // πάνω στο πλαίσιο-οδηγό, βασισμένο στο πόσο χώρο καλύπτουν οι χαρακτήρες.
  const [distanceHint, setDistanceHint] = useState(null);
  // Πόσα συνεχόμενα «πράσινα» περάσματα έχουμε δει — για auto-scan σταθερότητας.
  const stableAlignedTicksRef = useRef(0);
  // true ΜΟΛΙΣ βρεθεί έστω ΜΙΑ φορά πινακίδα (αυτόματα ή χειροκίνητα) —
  // ΚΛΕΙΔΩΝΕΙ το auto-scan μέχρι να κλείσει/ξανανοίξει η κάμερα. Χωρίς αυτό,
  // αν ο χρήστης μετακινήσει την κάμερα ΑΛΛΟΥ αφού βρει ήδη σωστά την πλάκα
  // (π.χ. για να δείξει κάτι άλλο, ή απλά τρέμει το χέρι), κάθε νέα τυχαία
  // ευθυγράμμιση θα ξανασκανάριζε και θα ΧΑΛΟΥΣΕ το ήδη σωστό πεδίο.
  const scanLockedRef = useRef(false);
  // id της ΤΕΛΕΥΤΑΙΑΣ σάρωσης στο backend (OcrMetric) — για να ενημερώσουμε
  // αν τελικά ο χρήστης το διόρθωσε χειροκίνητα, όταν πατήσει «Δημιουργία».
  const lastMetricIdRef = useRef(null);
  // Γνωστές πινακίδες (πελάτες αυτού του συνεργείου) — φορτώνονται μία φορά
  // στο άνοιγμα της κάμερας, ΟΧΙ σε state (δεν χρειάζεται re-render, μόνο
  // ανάγνωση μέσα στο captureAndRecognize). Best-effort: αν αποτύχει η
  // φόρτωση, απλά δεν προτείνεται καμία διόρθωση — καμία επίπτωση στη ροή.
  const knownPlatesRef = useRef([]);
  // Πρόταση διόρθωσης βάσει γνωστής πινακίδας ("μήπως εννοείς...") — δες
  // findClosestKnownPlate στο utils.js.
  const [plateSuggestion, setPlateSuggestion] = useState(null);
  // Όταν η πινακίδα ταιριάζει στη μορφή ΧΧΧ-999(9), το κύριο πεδίο δείχνεται
  // ως κουτάκια-ανά-χαρακτήρα (πιο εύκολο να ελεγχθεί με μια ματιά). Ο
  // χρήστης μπορεί να περάσει σε ελεύθερο πεδίο κειμένου όποτε θέλει (π.χ.
  // μη τυπική πινακίδα) — αυτό το flag θυμάται ρητή επιλογή του χρήστη.
  const [manualPlateEdit, setManualPlateEdit] = useState(false);
  // Οθόνη «σάρωση» (κάμερα) vs «έλεγχος» (πεδίο + επιβεβαίωση + CTA) — ΡΗΤΟ
  // state αντί για παράγωγο από `!!plate`, ώστε το να αδειάσει κανείς το
  // πεδίο πινακίδας στην οθόνη ελέγχου να ΜΗΝ πετάξει πίσω στην κάμερα.
  const [reviewMode, setReviewMode] = useState(false);

  useEffect(() => {
    return () => stopCamera();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Ζωντανό «κόκκινο/πράσινο» πλαίσιο: κάθε ALIGN_CHECK_MS τρέχει το ΕΛΑΦΡΥ
  // heuristic (χωρίς Tesseract) πάνω στο ίδιο crop που θα έπαιρνε το
  // «Σκάναρε», ώστε ο χρήστης να δει ΠΡΙΝ πατήσει αν κάτι είναι στραβά
  // (π.χ. πολύ κοντά -> θόλωμα -> δεν βρίσκονται καθαροί χαρακτήρες).
  useEffect(() => {
    if (!cameraOn) {
      setAligned(false);
      setDistanceHint(null);
      stableAlignedTicksRef.current = 0;
      scanLockedRef.current = false;
      return;
    }
    let cancelled = false;
    let busy = false;

    const id = setInterval(() => {
      if (busy || ocrRunning) return;
      const video = videoRef.current;
      if (!video || video.readyState < 2) return;

      const rect = computeCropRect(video, frameRef.current, mode);
      if (!rect) return;

      busy = true;
      try {
        const { sx, sy, sw, sh } = rect;
        const canvas = document.createElement("canvas");
        canvas.width = sw;
        canvas.height = sh;
        canvas.getContext("2d").drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);
        const { ok, kept, coverage, touchesEdge, sharpness, brightness } =
          assessPlateAlignment(canvas);
        const tooDark = brightness < MIN_BRIGHTNESS;
        const tooBright = brightness > MAX_BRIGHTNESS;
        const isSharp = sharpness >= MIN_SHARPNESS;
        const isAligned = looksAligned(mode, ok, kept, isSharp && !tooDark && !tooBright);
        if (cancelled) return;

        setAligned(isAligned);
        // Hint — μόνο όταν έχουμε αξιόπιστο σήμα (κάποιοι χαρακτήρες
        // εντοπίστηκαν) αλλά ΔΕΝ είναι ακόμα ευθυγραμμισμένη. Προτεραιότητα:
        //   1) touchesEdge -> πολύ κοντά, ό,τι κι αν λέει η coverage
        //   2) έκθεση (σκοτάδι/αντηλιά-φλας) -> αυτό ΕΞΗΓΕΙ γιατί δεν βρίσκει
        //      καθαρούς χαρακτήρες, πιο χρήσιμο feedback από «κράτα σταθερά»
        //   3) θόλωμα -> κράτα σταθερά / εστίασε
        //   4) coverage -> απόσταση
        if (!isAligned && ok) {
          if (touchesEdge) setDistanceHint("back");
          else if (tooDark) setDistanceHint("dark");
          else if (tooBright) setDistanceHint("bright");
          else if (!isSharp) setDistanceHint("blur");
          else if (coverage < MIN_COVERAGE) setDistanceHint("closer");
          else if (coverage > MAX_COVERAGE) setDistanceHint("back");
          else setDistanceHint(null);
        } else {
          setDistanceHint(null);
        }

        // Auto-scan: μόλις μείνει σταθερά ευθυγραμμισμένη για λίγα tick,
        // σκανάρει μόνη της — ο χρήστης δεν χρειάζεται να ξαναπατήσει τίποτα.
        // ΔΕΝ ξανασκανάρει αν είναι ήδη κλειδωμένο (βρέθηκε πινακίδα νωρίτερα
        // σε αυτή τη συνεδρία κάμερας) — αλλιώς μια τυχαία ευθυγράμμιση ενώ ο
        // χρήστης κουνάει την κάμερα αλλού θα χαλούσε το ήδη σωστό πεδίο.
        if (isAligned) {
          stableAlignedTicksRef.current += 1;
          if (
            stableAlignedTicksRef.current >= AUTO_SCAN_STABLE_TICKS &&
            !scanLockedRef.current
          ) {
            captureAndRecognize();
          }
        } else {
          stableAlignedTicksRef.current = 0;
        }
      } finally {
        busy = false;
      }
    }, ALIGN_CHECK_MS);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [cameraOn, mode, ocrRunning]);

  async function startCamera() {
    setError("");
    try {
      // Ζητάμε ΥΨΗΛΗ ανάλυση ρητά — χωρίς αυτό πολλά κινητά δίνουν default
      // 640x480, οπότε το crop του πλαισίου-οδηγού (~80% πλάτους πάνω σε μια
      // πινακίδα μακριά) καταλήγει μόλις μερικές εκατοντάδες px πλάτος πριν
      // το OCR — δεν υπάρχει αρκετή πληροφορία για σωστή αναγνώριση όσο καλό
      // κι αν είναι το preprocessing μετά. "ideal" ώστε να μην αποτύχει η
      // κάμερα αν η συσκευή δεν υποστηρίζει τόσο μεγάλη ανάλυση.
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setCameraOn(true);

      // Φόρτωσε τις γνωστές πινακίδες (fire-and-forget) για το «μήπως εννοείς»
      // πρόταση διόρθωσης παρακάτω — δεν μπλοκάρει το άνοιγμα της κάμερας.
      getCustomerPlates()
        .then((customers) => {
          knownPlatesRef.current = customers || [];
        })
        .catch(() => {
          knownPlatesRef.current = [];
        });

      // Φλας (torch) — υποστηρίζεται μόνο σε μερικά Android/Chrome, ΟΧΙ σε
      // iOS Safari. Ελέγχουμε τις δυνατότητες του track πριν δείξουμε το
      // κουμπί, ώστε να μην εμφανίζεται κάτι που δεν κάνει τίποτα.
      const [track] = stream.getVideoTracks();
      const capabilities = track?.getCapabilities?.();
      setFlashSupported(!!capabilities?.torch);
      setFlashOn(false);

      // Συνεχής αυτόματη εστίαση — αν δεν οριστεί ρητά, κάποιες κάμερες
      // κλειδώνουν την εστίαση στο πρώτο frame (συχνά μακρινό/θολό background
      // πριν ο χρήστης φέρει την πλάκα στο πλαίσιο). Best-effort: αγνόησε αν
      // η συσκευή δεν το υποστηρίζει (π.χ. iOS Safari δεν εκθέτει focusMode).
      if (capabilities?.focusMode?.includes("continuous")) {
        try {
          await track.applyConstraints({
            advanced: [{ focusMode: "continuous" }],
          });
        } catch {
          // αγνόησε — απλή βελτίωση, όχι κρίσιμη λειτουργία
        }
      }
    } catch (err) {
      setError(
        "Δεν ήταν δυνατή η πρόσβαση στην κάμερα. Έλεγξε τα δικαιώματα. " +
          `(${err.message})`
      );
    }
  }

  function stopCamera() {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setCameraOn(false);
    setFlashSupported(false);
    setFlashOn(false);
  }

  async function toggleFlash() {
    const [track] = streamRef.current?.getVideoTracks() || [];
    if (!track) return;
    const next = !flashOn;
    try {
      await track.applyConstraints({ advanced: [{ torch: next }] });
      setFlashOn(next);
    } catch (err) {
      setError("Δεν ήταν δυνατή η ενεργοποίηση του φλας. (" + err.message + ")");
    }
  }

  async function captureAndRecognize() {
    setError("");
    const video = videoRef.current;
    const frame = frameRef.current;
    if (!video || !frame) return;

    // Crop ΤΗΝ περιοχή του πλαισίου-οδηγού, μεταφρασμένη από τις συντεταγμένες
    // της οθόνης σε συντεταγμένες του καρέ της κάμερας. Στενό crop για το
    // Tesseract· ελαφρώς φαρδύτερο για το εξειδικευμένο ALPR (κάνει δικό του
    // plate detection, βλ. computeCropRect). Καλείται ΞΑΝΑ σε κάθε consensus
    // attempt ώστε να πιάνει ΠΡΑΓΜΑΤΙΚΑ διαφορετικό frame, όχι το ίδιο ξανά.
    function captureFrames() {
      const rect = computeCropRect(video, frame, mode);
      if (!rect) return null;
      const wideRect = computeCropRect(video, frame, mode, ALPR_CROP_EXPAND);
      const crop = drawCrop(video, rect);
      const wideCrop = wideRect ? drawCrop(video, wideRect) : crop;
      return { crop, wideCrop };
    }

    let frames = captureFrames();
    if (!frames) return;

    setOcrRunning(true);
    setProgress(0);
    setConfidence(null);
    setRawText("");
    setWarnings([]);
    setEngineFallback(false);
    setConsensusAgree(null);
    setConsensusTotal(null);
    setDisagreement(false);
    setPreview(null);
    setRawCropPreview(null);
    setPlateSuggestion(null);
    setVerified(false);
    try {
      const recognizer = getRecognizer();
      const attempts = [];

      const firstResult = await recognizer.recognizePlate(
        frames.crop,
        (pct) => setProgress(Math.round(pct / MAX_CONSENSUS_ATTEMPTS)),
        { mode, wideImageSource: frames.wideCrop }
      );
      attempts.push(firstResult);

      // Multi-frame consensus ΜΟΝΟ όταν καταλήξαμε σε Tesseract (forced ή
      // fallback από αποτυχημένο ALPR) — είναι το λιγότερο αξιόπιστο engine
      // και επωφελείται πραγματικά από πολλαπλές ανεξάρτητες λήψεις. Το ALPR
      // κάνει ήδη δικό του robust plate detection ανά κλήση ΚΑΙ κάθε κλήση
      // κοστίζει δίκτυο/quota (~2500 δωρεάν/μήνα) — τριπλασιάζοντάς τες θα
      // τριπλασίαζε αδίκως το κόστος για οριακό όφελος.
      if (firstResult.engineUsed !== "plate_recognizer") {
        for (let i = 1; i < MAX_CONSENSUS_ATTEMPTS; i++) {
          const agreeing = attempts.filter(
            (a) => a.plate && a.plate === attempts[attempts.length - 1].plate
          );
          if (attempts[attempts.length - 1].plate && agreeing.length >= 2) break;

          await sleep(CONSENSUS_FRAME_DELAY_MS);
          frames = captureFrames() || frames;
          const result = await recognizer.recognizePlate(
            frames.crop,
            (pct) =>
              setProgress(Math.round(((i + pct / 100) / MAX_CONSENSUS_ATTEMPTS) * 100)),
            { mode, wideImageSource: frames.wideCrop }
          );
          attempts.push(result);
        }
      }
      setProgress(100);

      const consensus = resolveConsensus(attempts);

      if (typeof consensus.confidence === "number") setConfidence(consensus.confidence);
      setRawText(consensus.rawText || "");
      setWarnings(consensus.warnings || []);
      setEngineUsed(consensus.engineUsed || recognizerName);
      setEngineFallback(attempts.some((a) => a.engineFallback));
      setConsensusAgree(consensus.agree);
      setConsensusTotal(consensus.total);
      setDisagreement(!!consensus.disagreement);
      if (consensus.processedDataUrl) setPreview(consensus.processedDataUrl);
      setRawCropPreview(frames.crop.toDataURL("image/jpeg", 0.85));

      // Καταγραφή ΚΑΘΕ σάρωσης (fire-and-forget) — ποτέ δεν πρέπει να
      // μπλοκάρει ή να χαλάσει τη ροή αν το backend δεν απαντήσει. Η μηχανή
      // καταγράφεται ΩΣ ΠΡΑΓΜΑΤΙΚΑ χρησιμοποιήθηκε (μετά από τυχόν fallback),
      // όχι η στατική ρύθμιση — αλλιώς οι μετρικές "tesseract" θα αναμιγνύονταν
      // κρυφά με σαρώσεις που στην πραγματικότητα έκανε το ALPR.
      lastMetricIdRef.current = null;
      logOcrAttempt({
        mode,
        engine: consensus.engineUsed || recognizerName,
        ocrPlate: consensus.plate || null,
        confidence: typeof consensus.confidence === "number" ? consensus.confidence : null,
        warningsCount: (consensus.warnings || []).length,
        parserCorrected: !!consensus.corrected,
      })
        .then((m) => {
          lastMetricIdRef.current = m.id;
        })
        .catch(() => {});

      if (consensus.plate) {
        setPlate(consensus.plate);
        setManualPlateEdit(false);
        // Κλείδωσε το auto-scan — βρέθηκε πινακίδα, μην την ξαναπειράξεις αν
        // η κάμερα μετακινηθεί αλλού. Ο χρήστης μπορεί πάντα να πατήσει
        // «↺ Νέα σάρωση» για να ξαναδοκιμάσει.
        scanLockedRef.current = true;
        // Βρέθηκε πινακίδα -> περνάμε στην οθόνη ελέγχου. Η κάμερα δεν
        // χρειάζεται πια να τρέχει ζωντανά (μπαταρία, λυχνία κάμερας) — το
        // «↺ Νέα σάρωση» την ξανανοίγει όποτε χρειαστεί.
        stopCamera();
        setReviewMode(true);

        // «Μήπως εννοείς...»: αν η ανάγνωση διαφέρει 1 χαρακτήρα από γνωστό
        // πελάτη, είναι πολύ πιο πιθανό να είναι λάθος ανάγνωση παρά νέο
        // όχημα με σχεδόν ίδια πινακίδα — πρότεινε τη διόρθωση, μην την
        // επιβάλλεις (ο χρήστης αποφασίζει).
        const match = findClosestKnownPlate(consensus.plate, knownPlatesRef.current);
        setPlateSuggestion(match);
      } else {
        setPlate("");
        setError(
          "Δεν αναγνωρίστηκε πινακίδα. Ευθυγράμμισε την πλάκα στο πλαίσιο και " +
            "ξαναδοκίμασε, ή πληκτρολόγησέ την χειροκίνητα."
        );
      }
    } catch (err) {
      setError(
        "Σφάλμα OCR: " +
          err.message +
          " — δοκίμασε ξανά τη λήψη ή πληκτρολόγησε την πινακίδα χειροκίνητα."
      );
    } finally {
      setOcrRunning(false);
    }
  }

  function acceptPlateSuggestion() {
    if (!plateSuggestion) return;
    setPlate(plateSuggestion.plate);
    setManualPlateEdit(false);
    setPlateSuggestion(null);
    // Η αποδοχή ΕΙΝΑΙ η επιβεβαίωση — ο χρήστης μόλις επέλεξε ρητά μια
    // συγκεκριμένη, γνωστή πινακίδα αντί της αβέβαιης ανάγνωσης OCR.
    setVerified(true);
  }

  function dismissPlateSuggestion() {
    setPlateSuggestion(null);
  }

  /** Κάθε χειροκίνητη επεξεργασία (ελεύθερο πεδίο Ή verify-editor) ακυρώνει
   * τυχόν προηγούμενη επιβεβαίωση — μια νέα τιμή χρειάζεται νέο έλεγχο. */
  function handlePlateEdit(value) {
    setPlate(normalizePlateInput(value));
    setPlateSuggestion(null);
    setVerified(false);
  }

  function handleConfirm() {
    const value = normalizePlateInput(plate);
    if (!value) {
      setError("Συμπλήρωσε πινακίδα πριν τη δημιουργία εγγραφής.");
      return;
    }
    if (needsVerification && !verified) {
      setError("Επιβεβαίωσε ότι η πινακίδα είναι σωστή πριν συνεχίσεις.");
      return;
    }
    if (isRental && !movementPurpose) {
      setError("Επίλεξε Σκοπό Κίνησης Οχήματος.");
      return;
    }
    if (isRental && diffPickupLocation && !pickupLocation.trim()) {
      setError("Συμπλήρωσε τον τόπο παραλαβής.");
      return;
    }
    // Αν είχε προηγηθεί σάρωση, ενημέρωσε τη μετρική με το ΤΕΛΙΚΟ κείμενο,
    // ώστε το backend να υπολογίσει αν χρειάστηκε χειροκίνητη διόρθωση.
    if (lastMetricIdRef.current) {
      confirmOcrMetric(lastMetricIdRef.current, value).catch(() => {});
    }
    stopCamera();
    const extra = isRental
      ? {
          vehicleMovementPurpose: Number(movementPurpose),
          isDiffVehPickupLocation: diffPickupLocation,
          vehiclePickupLocation: diffPickupLocation ? pickupLocation.trim() : null,
        }
      : {};
    onConfirm(value, extra);
  }

  // Καθαρίζει ΟΛΟ το αποτέλεσμα της προηγούμενης σάρωσης και ξανανοίγει την
  // κάμερα — επιστροφή στην οθόνη σάρωσης από την οθόνη ελέγχου.
  function handleRetry() {
    setPlate("");
    setError("");
    setConfidence(null);
    setRawText("");
    setWarnings([]);
    setEngineFallback(false);
    setConsensusAgree(null);
    setConsensusTotal(null);
    setDisagreement(false);
    setPreview(null);
    setRawCropPreview(null);
    setPlateSuggestion(null);
    setVerified(false);
    setReviewMode(false);
    scanLockedRef.current = false;
    stableAlignedTicksRef.current = 0;
    startCamera();
  }

  // «Πληκτρολόγησε χειροκίνητα» από την οθόνη σάρωσης — η κάμερα ΔΕΝ
  // χρειάζεται πια να τρέχει, ο χρήστης πάει κατευθείαν στο πεδίο πινακίδας.
  function handleManualEntry() {
    stopCamera();
    setError("");
    setReviewMode(true);
  }

  // Η ανάγνωση χρειάζεται ΡΗΤΗ επιβεβαίωση πριν προχωρήσει η δημιουργία
  // εγγραφής: είτε ο parser μάντεψε κάτι (warnings), είτε οι σαρώσεις
  // διαφώνησαν μεταξύ τους, είτε το confidence είναι χαμηλό. Χωρίς σάρωση
  // (χειροκίνητη πληκτρολόγηση από την αρχή) δεν ισχύει καμία από τις
  // παραπάνω συνθήκες, οπότε δεν μπλοκάρει καθόλου.
  const needsVerification =
    !!plate && (disagreement || warnings.length > 0 || (confidence !== null && confidence < 70));

  // 100% βεβαιότητα, καμία επιφύλαξη parser, ΚΑΙ καμία ασυμφωνία -> σίγουρη
  // ανάγνωση, όχι απλά "αρκετά καλή". Τότε αξίζει να καθοδηγήσουμε ρητά τον
  // χρήστη στο επόμενο βήμα αντί να τον αφήσουμε να ψάχνει τι κάνει.
  const isPerfect =
    confidence === 100 && warnings.length === 0 && !disagreement && !!plate;

  return (
    <div className="card">
      <h2>{isRental ? "Παραλαβή οχήματος" : "Είσοδος οχήματος"}</h2>

      {!reviewMode ? (
        <>
          <p className="muted">
            Διάλεξε τύπο οχήματος και ευθυγράμμισε την πλάκα μέσα στο
            πλαίσιο· θα γίνει ΠΡΑΣΙΝΟ όταν φαίνεται καθαρά και σκανάρει μόνη
            της, ή πάτα «Σκάναρε» χειροκίνητα όποτε θες.
          </p>

          <div className="mode-toggle">
            {Object.keys(GUIDES).map((key) => (
              <button
                key={key}
                type="button"
                className={`mode-btn${mode === key ? " is-active" : ""}`}
                onClick={() => setMode(key)}
                disabled={ocrRunning}
              >
                {key === "car" ? "🚗 Αυτοκίνητο" : "🏍️ Μηχανή"}
              </button>
            ))}
          </div>

          <div className="camera-frame" ref={frameRef}>
            <video ref={videoRef} playsInline muted className="camera-video" />
            {!cameraOn && <div className="camera-placeholder">Κάμερα κλειστή</div>}
            {cameraOn && flashSupported && (
              <button
                type="button"
                className={`flash-toggle${flashOn ? " is-on" : ""}`}
                onClick={toggleFlash}
              >
                {flashOn ? "🔦 Φλας ON" : "🔦 Φλας"}
              </button>
            )}
            {cameraOn && (
              <span
                className={`plate-status-pill${aligned ? " is-aligned" : ""}${
                  distanceHint ? " is-hint" : ""
                }`}
              >
                {aligned
                  ? "✓ Έτοιμο"
                  : distanceHint === "closer"
                  ? "🔎 Λίγο πιο μπροστά"
                  : distanceHint === "back"
                  ? "↔️ Λίγο πιο πίσω"
                  : distanceHint === "blur"
                  ? "🫳 Κράτα σταθερά"
                  : distanceHint === "dark"
                  ? "🔦 Χρειάζεται φως"
                  : distanceHint === "bright"
                  ? "😎 Μείωσε αντηλιά/φλας"
                  : GUIDES[mode].label}
              </span>
            )}
            {cameraOn && (
              <div
                className={`plate-guide${aligned ? " is-aligned" : ""}`}
                style={{
                  width: `${GUIDES[mode].widthFrac * 100}%`,
                  aspectRatio: `${GUIDES[mode].aspect}`,
                }}
              />
            )}
          </div>

          <div className="btn-row btn-row-end">
            {!cameraOn ? (
              <button
                className="btn btn-primary btn-lg"
                onClick={startCamera}
                disabled={disabled}
              >
                📷 Άνοιγμα κάμερας
              </button>
            ) : (
              <>
                <button className="btn btn-ghost" onClick={stopCamera}>
                  Κλείσιμο
                </button>
                <button
                  className="btn btn-primary btn-lg"
                  onClick={captureAndRecognize}
                  disabled={ocrRunning}
                >
                  {ocrRunning ? `Αναγνώριση… ${progress}%` : "🔍 Σκάναρε πινακίδα"}
                </button>
              </>
            )}
          </div>

          {error && <div className="alert alert-error">{error}</div>}

          <button
            type="button"
            className="link-btn"
            onClick={handleManualEntry}
            disabled={disabled}
          >
            ✏️ Πληκτρολόγησε την πινακίδα χειροκίνητα
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            className="link-btn"
            onClick={handleRetry}
            disabled={ocrRunning}
          >
            ↺ Νέα σάρωση
          </button>

          {/* «Μήπως εννοείς...» — η ανάγνωση διαφέρει 1 χαρακτήρα από γνωστό
              πελάτη αυτού του συνεργείου. Ο χρήστης αποφασίζει, δεν επιβάλλεται. */}
          {plateSuggestion && (
            <div className="alert alert-info plate-suggestion">
              🔎 Μήπως εννοείς <b>{plateSuggestion.plate}</b>
              {plateSuggestion.name ? ` — ${plateSuggestion.name}` : ""}; Το OCR
              διάβασε «{plate}».
              <div className="btn-row">
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  onClick={acceptPlateSuggestion}
                >
                  Ναι, χρησιμοποίησε αυτή
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  onClick={dismissPlateSuggestion}
                >
                  Όχι, κράτα «{plate}»
                </button>
              </div>
            </div>
          )}

          {/* Ενιαία κάρτα αποτελέσματος σάρωσης — φωτογραφία + βεβαιότητα +
              μηχανή + τυχόν επιφυλάξεις ΟΛΑ μαζί, ΜΙΑ φορά. Απουσιάζει τελείως
              όταν η οθόνη ελέγχου ήρθε από «Πληκτρολόγησε χειροκίνητα» (δεν
              υπάρχει σάρωση/φωτογραφία να δειχτεί). */}
          {confidence !== null && (
            <div
              className="scan-result"
              style={{
                borderLeftColor:
                  confidence >= 80 ? "#4ade80" : confidence >= 50 ? "#d97706" : "#f87171",
              }}
            >
              <div className="scan-result-row">
                {(preview || rawCropPreview) && (
                  <img
                    className="scan-result-thumb"
                    src={preview || rawCropPreview}
                    alt="Λήψη πινακίδας"
                  />
                )}
                <div className="scan-result-info">
                  <span
                    className="ocr-conf"
                    style={{
                      color:
                        confidence >= 80
                          ? "#4ade80"
                          : confidence >= 50
                          ? "#d97706"
                          : "#f87171",
                    }}
                  >
                    {confidence}% βεβαιότητα
                  </span>
                  <span className="ocr-status-engine">
                    {engineUsed === "plate_recognizer" ? "ALPR" : "tesseract"}
                    {consensusTotal > 1 &&
                      (disagreement
                        ? ` · ⚠️ διαφωνία (${consensusTotal} δοκιμές)`
                        : ` · ✓ ${consensusAgree}/${consensusTotal} λήψεις`)}
                  </span>
                </div>
              </div>
              {engineFallback && (
                <div className="scan-result-note">
                  ⚠️ Το ALPR δεν ήταν διαθέσιμο — χρησιμοποιήθηκε το εναλλακτικό
                  tesseract (λιγότερο ακριβές).
                </div>
              )}
              {warnings.length > 0 && (
                <div className="scan-result-note">
                  ⚠️ Η πινακίδα δεν διαβάστηκε καθαρά: {warnings.join(" · ")}
                </div>
              )}
            </div>
          )}

          {/* Κύριο πεδίο πινακίδας: κουτάκια-ανά-χαρακτήρα όταν η τιμή ταιριάζει
              στη μορφή ΧΧΧ-999 ή ΧΧΧ-9999 (πιο εύκολο να ελεγχθεί με μια ματιά),
              αλλιώς απλό πεδίο κειμένου (π.χ. άδειο, ή μη τυπική πινακίδα). Το
              μήκος των ψηφίων προσαρμόζεται μόνο του — 3 ή 4, ό,τι διαβάστηκε. */}
          {!manualPlateEdit && VERIFIABLE_PLATE_RE.test(plate) ? (
            <div className="plate-field">
              <div className="plate-field-head">
                <span className="plate-field-label">ΠΙΝΑΚΙΔΑ</span>
                <button
                  type="button"
                  className="plate-field-mode-btn"
                  onClick={() => setManualPlateEdit(true)}
                >
                  ✏️ Ελεύθερη επεξεργασία
                </button>
              </div>
              <PlateVerifyEditor plate={plate} onChange={handlePlateEdit} />
            </div>
          ) : (
            <label className="field-label">
              Πινακίδα:
              <input
                className="input plate-input"
                type="text"
                value={plate}
                placeholder="π.χ. OTM-776 ή ABH-1234"
                onChange={(e) => handlePlateEdit(e.target.value)}
                autoFocus={reviewMode && !plate}
              />
              {VERIFIABLE_PLATE_RE.test(plate) && (
                <button
                  type="button"
                  className="plate-field-mode-btn plate-field-mode-btn-inline"
                  onClick={() => setManualPlateEdit(false)}
                >
                  🔢 Ανά χαρακτήρα
                </button>
              )}
            </label>
          )}

          {/* Οθόνη επιβεβαίωσης — εμφανίζεται ΜΟΝΟ όταν η ανάγνωση δεν είναι
              αρκετά σίγουρη (επιφυλάξεις parser, χαμηλό confidence, ή διαφωνία
              ανάμεσα σε πολλαπλές σαρώσεις). Το κουμπί δημιουργίας μένει
              κλειδωμένο μέχρι ο χρήστης να το επιβεβαιώσει ρητά — μια παθητική
              προειδοποίηση συχνά προσπερνιέται όταν ο χρήστης βιάζεται. Τα
              κουτάκια-ανά-χαρακτήρα είναι ήδη ορατά παραπάνω (κύριο πεδίο), και
              η φωτογραφία ελέγχου είναι ήδη στην κάρτα αποτελέσματος από πάνω —
              εδώ μένει μόνο το μήνυμα + το checkbox επιβεβαίωσης. */}
          {needsVerification && (
            <div className="plate-verify">
              <div className="alert alert-error">
                ⚠️{" "}
                {disagreement
                  ? "Οι λήψεις διαφώνησαν μεταξύ τους"
                  : warnings.length > 0
                  ? "Η πινακίδα δεν διαβάστηκε καθαρά"
                  : "Χαμηλή βεβαιότητα OCR"}{" "}
                — έλεγξε προσεκτικά κάθε χαρακτήρα πριν συνεχίσεις.
              </div>
              <label className="field-label field-checkbox">
                <input
                  type="checkbox"
                  checked={verified}
                  onChange={(e) => setVerified(e.target.checked)}
                />
                ✅ Το επιβεβαιώνω — η πινακίδα παραπάνω είναι σωστή
              </label>
            </div>
          )}

          {isRental && (
            <details className="rental-section" open>
              <summary className="rental-section-summary">🚚 Στοιχεία ενοικίασης</summary>
              <label className="field-label">
                Σκοπός Κίνησης Οχήματος:
                <select
                  className="input"
                  value={movementPurpose}
                  onChange={(e) => setMovementPurpose(e.target.value)}
                >
                  <option value="">— Επίλεξε —</option>
                  {VEHICLE_MOVEMENT_PURPOSES.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.value} — {p.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field-label field-checkbox">
                <input
                  type="checkbox"
                  checked={diffPickupLocation}
                  onChange={(e) => setDiffPickupLocation(e.target.checked)}
                />
                Διαφορετικός τόπος παραλαβής οχήματος
              </label>

              {diffPickupLocation && (
                <label className="field-label">
                  Τόπος Παραλαβής:
                  <input
                    className="input"
                    type="text"
                    value={pickupLocation}
                    onChange={(e) => setPickupLocation(e.target.value)}
                    placeholder="π.χ. Αεροδρόμιο Ηρακλείου"
                  />
                </label>
              )}
            </details>
          )}

          {error && <div className="alert alert-error">{error}</div>}

          {/* 100% σίγουρη ανάγνωση, χωρίς επιφυλάξεις -> καθοδήγησε καθαρά τον
              χρήστη στο επόμενο βήμα αντί να τον αφήσουμε να αναρωτιέται τι
              κάνει μετά. */}
          {isPerfect && (
            <div className="scan-success-hint">
              <span className="scan-success-check">✓ Άψογη ανάγνωση!</span>
              <span className="scan-success-arrow">⌄</span>
            </div>
          )}

          <div className="sticky-cta">
            <button
              className={`btn btn-block${isPerfect ? " btn-success" : " btn-primary"}`}
              onClick={handleConfirm}
              disabled={disabled || ocrRunning || (needsVerification && !verified)}
            >
              {needsVerification && !verified
                ? "🔒 Επιβεβαίωσε την πινακίδα παραπάνω"
                : isPerfect
                ? "✓ Δημιουργία εγγραφής"
                : "➕ Δημιουργία εγγραφής"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
