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
import { logOcrAttempt, confirmOcrMetric } from "../services/api";
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
 */
function computeCropRect(video, frame, mode) {
  if (!video || !frame) return null;
  const box = frame.getBoundingClientRect();
  if (!box.width || !box.height) return null;
  const view = visibleVideoRect(video, box.width, box.height);
  const guide = GUIDES[mode];

  const guideW = guide.widthFrac * box.width;
  const guideH = guideW / guide.aspect;
  const sw = Math.max(1, Math.round((guideW / box.width) * view.w));
  const sh = Math.max(1, Math.round((guideH / box.height) * view.h));
  const sx = Math.round(view.x + (view.w - sw) / 2);
  const sy = Math.round(view.y + (view.h - sh) / 2);
  return { sx, sy, sw, sh };
}

export default function CameraCapture({ onConfirm, disabled }) {
  const videoRef = useRef(null);
  const frameRef = useRef(null);
  const streamRef = useRef(null);

  const [mode, setMode] = useState("car");
  const [cameraOn, setCameraOn] = useState(false);
  const [ocrRunning, setOcrRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [plate, setPlate] = useState("");
  const [error, setError] = useState("");
  const [confidence, setConfidence] = useState(null);
  const [rawText, setRawText] = useState("");
  const [warnings, setWarnings] = useState([]);
  const [preview, setPreview] = useState(null); // dataURL προεπεξεργασμένης εικόνας
  const [aligned, setAligned] = useState(false); // ζωντανό feedback πλαισίου
  // id της ΤΕΛΕΥΤΑΙΑΣ σάρωσης στο backend (OcrMetric) — για να ενημερώσουμε
  // αν τελικά ο χρήστης το διόρθωσε χειροκίνητα, όταν πατήσει «Δημιουργία».
  const lastMetricIdRef = useRef(null);

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
        const { ok, kept } = assessPlateAlignment(canvas);
        if (!cancelled) setAligned(looksAligned(mode, ok, kept));
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
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setCameraOn(true);
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
  }

  async function captureAndRecognize() {
    setError("");
    const video = videoRef.current;
    const frame = frameRef.current;
    if (!video || !frame) return;

    // Crop ΜΟΝΟ την περιοχή του πλαισίου-οδηγού, μεταφρασμένη από τις
    // συντεταγμένες της οθόνης σε συντεταγμένες του καρέ της κάμερας.
    const rect = computeCropRect(video, frame, mode);
    if (!rect) return;
    const { sx, sy, sw, sh } = rect;

    const crop = document.createElement("canvas");
    crop.width = sw;
    crop.height = sh;
    crop.getContext("2d").drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);

    setOcrRunning(true);
    setProgress(0);
    setConfidence(null);
    setRawText("");
    setWarnings([]);
    setPreview(null);
    try {
      const recognizer = getRecognizer();
      const result = await recognizer.recognizePlate(
        crop,
        (pct) => setProgress(pct),
        { mode }
      );

      if (typeof result.confidence === "number") setConfidence(result.confidence);
      setRawText(result.rawText || "");
      setWarnings(result.warnings || []);
      if (result.processedDataUrl) setPreview(result.processedDataUrl);

      // Καταγραφή ΚΑΘΕ σάρωσης (fire-and-forget) — ποτέ δεν πρέπει να
      // μπλοκάρει ή να χαλάσει τη ροή αν το backend δεν απαντήσει.
      lastMetricIdRef.current = null;
      logOcrAttempt({
        mode,
        engine: recognizerName,
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
      } else {
        setPlate("");
        setError(
          "Δεν αναγνωρίστηκε πινακίδα. Ευθυγράμμισε την πλάκα στο πλαίσιο και " +
            "ξαναδοκίμασε, ή πληκτρολόγησέ την χειροκίνητα."
        );
      }
    } catch (err) {
      setError("Σφάλμα OCR: " + err.message);
    } finally {
      setOcrRunning(false);
    }
  }

  function handleConfirm() {
    const value = plate.trim().toUpperCase();
    if (!value) {
      setError("Συμπλήρωσε πινακίδα πριν τη δημιουργία εγγραφής.");
      return;
    }
    // Αν είχε προηγηθεί σάρωση, ενημέρωσε τη μετρική με το ΤΕΛΙΚΟ κείμενο,
    // ώστε το backend να υπολογίσει αν χρειάστηκε χειροκίνητη διόρθωση.
    if (lastMetricIdRef.current) {
      confirmOcrMetric(lastMetricIdRef.current, value).catch(() => {});
    }
    stopCamera();
    onConfirm(value);
  }

  return (
    <div className="card">
      <h2>1ος Χρόνος — Είσοδος οχήματος</h2>
      <p className="muted">
        Διάλεξε τύπο οχήματος και ευθυγράμμισε την πλάκα μέσα στο πλαίσιο· θα
        γίνει ΠΡΑΣΙΝΟ όταν φαίνεται καθαρά. Αν μείνει κόκκινο, απομακρύνσου
        λίγο — πολύ κοντά η κάμερα δεν εστιάζει καλά. Μετά πάτα «Σκάναρε».
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
        {cameraOn && (
          <div
            className={`plate-guide${aligned ? " is-aligned" : ""}`}
            style={{
              width: `${GUIDES[mode].widthFrac * 100}%`,
              aspectRatio: `${GUIDES[mode].aspect}`,
            }}
          >
            <span className="plate-guide-label">
              {aligned ? "✓ Έτοιμο" : GUIDES[mode].label}
            </span>
          </div>
        )}
      </div>

      <div className="btn-row">
        {!cameraOn ? (
          <button className="btn" onClick={startCamera} disabled={disabled}>
            📷 Άνοιγμα κάμερας
          </button>
        ) : (
          <>
            <button
              className="btn"
              onClick={captureAndRecognize}
              disabled={ocrRunning}
            >
              {ocrRunning ? `Αναγνώριση… ${progress}%` : "🔍 Σκάναρε πινακίδα"}
            </button>
            <button className="btn btn-ghost" onClick={stopCamera}>
              Κλείσιμο
            </button>
          </>
        )}
      </div>

      <label className="field-label">
        Πινακίδα (μπορείς να τη διορθώσεις):
        <input
          className="input"
          type="text"
          value={plate}
          placeholder="π.χ. ΟΤΜ-776 ή ΑΒΓ-1234"
          onChange={(e) => setPlate(e.target.value)}
        />
      </label>

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
          <span className="muted small">Μηχανή: {recognizerName}</span>
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

      <button
        className="btn btn-primary btn-block"
        onClick={handleConfirm}
        disabled={disabled || ocrRunning}
      >
        ➕ Δημιουργία εγγραφής (SendClient)
      </button>
    </div>
  );
}
