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
import { logOcrAttempt, confirmOcrMetric, getCustomers } from "../services/api";
import { VEHICLE_MOVEMENT_PURPOSES } from "../constants";
import { normalizePlateInput, findClosestKnownPlate } from "../utils";
// Ελαφρύ heuristic (χωρίς OCR) για ζωντανό feedback ευθυγράμμισης — δουλεύει
// πάνω στο ίδιο pipeline denoising ανεξάρτητα από το ποιος recognizer είναι
// ενεργός (Tesseract ή μελλοντικό ALPR), γι' αυτό εισάγεται απευθείας.
import { assessPlateAlignment } from "../services/plateRecognizer/preprocess";

// Πόσο συχνά ελέγχουμε την ευθυγράμμιση ζωντανά (ms). Αρκετά γρήγορο ώστε να
// νιώθει «ζωντανό», αρκετά αραιό ώστε να μην επιβαρύνει παλιότερα κινητά.
const ALIGN_CHECK_MS = 350;

// Αναμενόμενος αριθμός χαρακτήρων ανά τύπο οχήματος (μηχανή: 3+3, αυτοκίνητο:
// 3+4). Ανεχόμαστε ΕΝΑ λιγότερο blob: σε μικρή ανάλυση (γρήγορο ζωντανό
// check) δύο γειτονικά γράμματα μπορεί να «κολλήσουν» οπτικά χωρίς αυτό να
// σημαίνει ότι η πλάκα δεν είναι στην πραγματικότητα ευανάγνωστη — ένα
// αυστηρό exact-match θα έμενε κόκκινο ακόμα και σε σωστή ευθυγράμμιση.
const EXPECTED_CHARS = { car: 7, moto: 6 };
function looksAligned(mode, ok, kept) {
  return ok && kept >= EXPECTED_CHARS[mode] - 1;
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
        const { ok, kept, coverage, touchesEdge } = assessPlateAlignment(canvas);
        const isAligned = looksAligned(mode, ok, kept);
        if (cancelled) return;

        setAligned(isAligned);
        // Hint κατεύθυνσης απόστασης — μόνο όταν έχουμε αξιόπιστο σήμα
        // (κάποιοι χαρακτήρες εντοπίστηκαν) αλλά ΔΕΝ είναι ακόμα ευθυγραμμισμένη·
        // αλλιώς μπορεί να είναι θέμα θαμπάδας/φωτισμού, όχι απόστασης.
        // ΠΡΟΤΕΡΑΙΟΤΗΤΑ στο touchesEdge: αν κάποιος χαρακτήρας αγγίζει την
        // άκρη του πλαισίου, η πινακίδα ήδη ξεφεύγει από το κάδρο — είναι
        // ΠΟΛΥ κοντά, ό,τι κι αν λέει η coverage των ορατών χαρακτήρων
        // (λίγοι, στριμωγμένοι χαρακτήρες μπορεί να δείχνουν ψευδώς «μακριά»).
        if (!isAligned && ok) {
          if (touchesEdge) setDistanceHint("back");
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
      getCustomers()
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
    // plate detection, βλ. computeCropRect).
    const rect = computeCropRect(video, frame, mode);
    if (!rect) return;
    const wideRect = computeCropRect(video, frame, mode, ALPR_CROP_EXPAND);

    const crop = drawCrop(video, rect);
    const wideCrop = wideRect ? drawCrop(video, wideRect) : crop;

    setOcrRunning(true);
    setProgress(0);
    setConfidence(null);
    setRawText("");
    setWarnings([]);
    setEngineFallback(false);
    setPreview(null);
    setPlateSuggestion(null);
    try {
      const recognizer = getRecognizer();
      const result = await recognizer.recognizePlate(
        crop,
        (pct) => setProgress(pct),
        { mode, wideImageSource: wideCrop }
      );

      if (typeof result.confidence === "number") setConfidence(result.confidence);
      setRawText(result.rawText || "");
      setWarnings(result.warnings || []);
      setEngineUsed(result.engineUsed || recognizerName);
      setEngineFallback(!!result.engineFallback);
      if (result.processedDataUrl) setPreview(result.processedDataUrl);

      // Καταγραφή ΚΑΘΕ σάρωσης (fire-and-forget) — ποτέ δεν πρέπει να
      // μπλοκάρει ή να χαλάσει τη ροή αν το backend δεν απαντήσει. Η μηχανή
      // καταγράφεται ΩΣ ΠΡΑΓΜΑΤΙΚΑ χρησιμοποιήθηκε (μετά από τυχόν fallback),
      // όχι η στατική ρύθμιση — αλλιώς οι μετρικές "tesseract" θα αναμιγνύονταν
      // κρυφά με σαρώσεις που στην πραγματικότητα έκανε το ALPR.
      lastMetricIdRef.current = null;
      logOcrAttempt({
        mode,
        engine: result.engineUsed || recognizerName,
        ocrPlate: result.plate || null,
        confidence: typeof result.confidence === "number" ? result.confidence : null,
        warningsCount: (result.warnings || []).length,
        parserCorrected: !!result.corrected,
      })
        .then((m) => {
          lastMetricIdRef.current = m.id;
        })
        .catch(() => {});

      if (result.plate) {
        setPlate(result.plate);
        // Κλείδωσε το auto-scan — βρέθηκε πινακίδα, μην την ξαναπειράξεις αν
        // η κάμερα μετακινηθεί αλλού. Ο χρήστης μπορεί πάντα να πατήσει
        // χειροκίνητα «Σκάναρε» για να ξαναδοκιμάσει.
        scanLockedRef.current = true;

        // «Μήπως εννοείς...»: αν η ανάγνωση διαφέρει 1 χαρακτήρα από γνωστό
        // πελάτη, είναι πολύ πιο πιθανό να είναι λάθος ανάγνωση παρά νέο
        // όχημα με σχεδόν ίδια πινακίδα — πρότεινε τη διόρθωση, μην την
        // επιβάλλεις (ο χρήστης αποφασίζει).
        const match = findClosestKnownPlate(result.plate, knownPlatesRef.current);
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
    setPlateSuggestion(null);
  }

  function dismissPlateSuggestion() {
    setPlateSuggestion(null);
  }

  function handleConfirm() {
    const value = normalizePlateInput(plate);
    if (!value) {
      setError("Συμπλήρωσε πινακίδα πριν τη δημιουργία εγγραφής.");
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

  // 100% βεβαιότητα ΚΑΙ καμία επιφύλαξη parser -> σίγουρη ανάγνωση, όχι απλά
  // "αρκετά καλή". Τότε αξίζει να καθοδηγήσουμε ρητά τον χρήστη στο επόμενο
  // βήμα αντί να τον αφήσουμε να ψάχνει τι κάνει.
  const isPerfect = confidence === 100 && warnings.length === 0 && !!plate;

  return (
    <div className="card">
      <h2>1ος Χρόνος — {isRental ? "Παραλαβή οχήματος" : "Είσοδος οχήματος"}</h2>
      <p className="muted">
        Διάλεξε τύπο οχήματος και ευθυγράμμισε την πλάκα μέσα στο πλαίσιο· θα
        γίνει ΠΡΑΣΙΝΟ όταν φαίνεται καθαρά και σκανάρει μόνη της. Ακολούθησε
        τις οδηγίες απόστασης αν εμφανιστούν, ή πάτα «Σκάναρε» χειροκίνητα
        όποτε θες.
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
          <div
            className={`plate-guide${aligned ? " is-aligned" : ""}`}
            style={{
              width: `${GUIDES[mode].widthFrac * 100}%`,
              aspectRatio: `${GUIDES[mode].aspect}`,
            }}
          >
            <span
              className={`plate-guide-label${
                distanceHint ? " plate-guide-label-hint" : ""
              }`}
            >
              {aligned
                ? "✓ Έτοιμο"
                : distanceHint === "closer"
                ? "🔎 Λίγο πιο μπροστά"
                : distanceHint === "back"
                ? "↔️ Λίγο πιο πίσω"
                : GUIDES[mode].label}
            </span>
          </div>
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

      <label className="field-label">
        Πινακίδα (μπορείς να τη διορθώσεις):
        <input
          className="input"
          type="text"
          value={plate}
          placeholder="π.χ. OTM-776 ή ABH-1234"
          onChange={(e) => {
            setPlate(normalizePlateInput(e.target.value));
            setPlateSuggestion(null);
          }}
        />
      </label>

      {isRental && (
        <>
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
        </>
      )}

      {/* Βεβαιότητα OCR */}
      {confidence !== null && (
        <div className="ocr-info">
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
            Βεβαιότητα OCR: {confidence}%
            {confidence < 50 ? " — χαμηλή, έλεγξε/διόρθωσε" : ""}
          </span>
          {rawText && <span className="muted small">Διάβασε: «{rawText}»</span>}
          <span className="muted small">
            Μηχανή: {engineUsed === "plate_recognizer" ? "ALPR" : "tesseract"}
          </span>
        </div>
      )}

      {/* Fallback ΑΛΠΡ -> Tesseract: ο χρήστης πρέπει να ξέρει ότι χρησιμοποιήθηκε
          η λιγότερο ακριβής μηχανή, ώστε να ελέγξει το αποτέλεσμα πιο προσεκτικά. */}
      {engineFallback && (
        <div className="alert alert-error">
          ⚠️ Το ALPR δεν ήταν διαθέσιμο — χρησιμοποιήθηκε το εναλλακτικό
          tesseract (λιγότερο ακριβές). Έλεγξε προσεκτικά την πινακίδα.
        </div>
      )}

      {/* Επιφυλάξεις της ανάλυσης — τι μάντεψε ο parser και γιατί.
          Χωρίς αυτό ο χρήστης βλέπει μια καθαρή πινακίδα και δεν έχει λόγο
          να την ελέγξει, ενώ στην πραγματικότητα είναι εικασία. */}
      {warnings.length > 0 && (
        <div className="ocr-warn">
          ⚠️ Η πινακίδα ΔΕΝ διαβάστηκε καθαρά — έλεγξέ την:
          <ul>
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Preview: τι «είδε» το OCR μετά την προεπεξεργασία */}
      {preview && (
        <div className="ocr-preview">
          <span className="muted small">Προεπεξεργασμένη εικόνα (OCR input):</span>
          <img src={preview} alt="OCR preview" />
        </div>
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

      <button
        className={`btn btn-block${isPerfect ? " btn-success" : " btn-primary"}`}
        onClick={handleConfirm}
        disabled={disabled || ocrRunning}
      >
        {isPerfect
          ? "✓ Δημιουργία εγγραφής"
          : "➕ Δημιουργία εγγραφής (SendClient)"}
      </button>
    </div>
  );
}
