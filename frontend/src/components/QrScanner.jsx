// components/QrScanner.jsx
// --------------------------------------------------------------------
// 4ος Χρόνος — Σκανάρισμα QR απόδειξης για εξαγωγή του ΜΑΡΚ.
// Χρησιμοποιεί html5-qrcode (πίσω κάμερα κινητού).
// Το αποτέλεσμα εμφανίζεται σε πεδίο που ο χρήστης μπορεί να διορθώσει
// ή να πληκτρολογήσει χειροκίνητα (fallback).
// --------------------------------------------------------------------
import { useEffect, useRef, useState } from "react";
import { Html5Qrcode } from "html5-qrcode";
import { parseMark } from "../utils";

const REGION_ID = "qr-reader-region";

export default function QrScanner({ onCorrelate, disabled, isRental }) {
  const scannerRef = useRef(null);
  const [scanning, setScanning] = useState(false);
  const [mark, setMark] = useState("");
  const [rawQr, setRawQr] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  useEffect(() => {
    return () => {
      stopScan();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startScan() {
    setError("");
    setInfo("");
    try {
      const html5Qr = new Html5Qrcode(REGION_ID);
      scannerRef.current = html5Qr;
      await html5Qr.start(
        { facingMode: "environment" }, // πίσω κάμερα
        { fps: 10, qrbox: { width: 250, height: 250 } },
        (decodedText) => handleDecoded(decodedText),
        () => {
          /* αγνόησε τα per-frame σφάλματα σάρωσης */
        }
      );
      setScanning(true);
    } catch (err) {
      setError(
        "Δεν ήταν δυνατή η εκκίνηση του σαρωτή QR. Έλεγξε τα δικαιώματα " +
          `κάμερας. (${err.message})`
      );
    }
  }

  async function stopScan() {
    const inst = scannerRef.current;
    if (inst) {
      try {
        if (inst.isScanning) await inst.stop();
        inst.clear();
      } catch {
        /* ignore */
      }
      scannerRef.current = null;
    }
    setScanning(false);
  }

  async function handleDecoded(decodedText) {
    setRawQr(decodedText);
    const extracted = parseMark(decodedText);
    if (extracted) {
      setMark(extracted);
      setInfo("Βρέθηκε ΜΑΡΚ από το QR. Έλεγξέ τον και επιβεβαίωσε.");
    } else {
      setInfo(
        "Το QR διαβάστηκε αλλά δεν εντοπίστηκε αυτόματα ΜΑΡΚ. " +
          "Πληκτρολόγησέ τον χειροκίνητα."
      );
    }
    await stopScan();
  }

  function handleConfirm() {
    const value = mark.trim();
    if (!value) {
      setError("Συμπλήρωσε ΜΑΡΚ πριν τη συσχέτιση.");
      return;
    }
    setError("");
    onCorrelate(value);
  }

  return (
    <div className="card">
      <h2>Συσχέτιση ΜΑΡΚ</h2>
      <p className="muted">
        Σκάναρε το QR της απόδειξης. Αν δεν διαβαστεί σωστά, γράψε τον ΜΑΡΚ
        χειροκίνητα.
      </p>

      <div id={REGION_ID} className="qr-region" />

      <div className="btn-row">
        {!scanning ? (
          <button className="btn" onClick={startScan} disabled={disabled}>
            📷 Έναρξη σάρωσης QR
          </button>
        ) : (
          <button className="btn btn-ghost" onClick={stopScan}>
            Διακοπή σάρωσης
          </button>
        )}
      </div>

      {info && <div className="alert alert-info">{info}</div>}

      <label className="field-label">
        ΜΑΡΚ (διόρθωσε ή πληκτρολόγησε χειροκίνητα):
        <input
          className="input"
          type="text"
          inputMode="numeric"
          value={mark}
          placeholder="π.χ. 400001234567890"
          onChange={(e) => setMark(e.target.value)}
        />
      </label>

      {rawQr && (
        <details className="raw-qr">
          <summary>Περιεχόμενο QR (raw)</summary>
          <code>{rawQr}</code>
        </details>
      )}

      {error && <div className="alert alert-error">{error}</div>}

      <button
        className="btn btn-primary btn-block"
        onClick={handleConfirm}
        disabled={disabled}
      >
        ✅ Επιβεβαίωση &amp; Συσχέτιση
      </button>
    </div>
  );
}
