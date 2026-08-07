// components/RentalVehiclePicker.jsx
// 1ος Χρόνος για Ενοικιάσεις — αντί για κάμερα/OCR, ο χρήστης επιλέγει την
// πινακίδα από ΈΝΑ dropdown που περιέχει ΜΟΝΟ τα οχήματα του δικού του στόλου
// (δες tab «Οχήματα» / FleetVehicles.jsx). Το backend το επιβάλλει ούτως ή
// άλλως (create_entry: 400 αν η πινακίδα δεν ανήκει στον στόλο) — εδώ απλά
// δεν αφήνουμε καν τον χρήστη να διαλέξει κάτι εκτός λίστας.
import { useEffect, useState } from "react";
import { getFleetVehicles } from "../services/api";
import { VEHICLE_MOVEMENT_PURPOSES } from "../constants";

export default function RentalVehiclePicker({ onConfirm, disabled }) {
  const [vehicles, setVehicles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [plate, setPlate] = useState("");
  const [movementPurpose, setMovementPurpose] = useState("");
  const [diffPickupLocation, setDiffPickupLocation] = useState(false);
  const [pickupLocation, setPickupLocation] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError("");
      try {
        const data = await getFleetVehicles();
        setVehicles(Array.isArray(data) ? data : []);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  function handleConfirm() {
    if (!plate) {
      setError("Επίλεξε όχημα από τον στόλο.");
      return;
    }
    if (!movementPurpose) {
      setError("Επίλεξε Σκοπό Κίνησης Οχήματος.");
      return;
    }
    if (diffPickupLocation && !pickupLocation.trim()) {
      setError("Συμπλήρωσε τον τόπο παραλαβής.");
      return;
    }
    setError("");
    onConfirm(plate, {
      vehicleMovementPurpose: Number(movementPurpose),
      isDiffVehPickupLocation: diffPickupLocation,
      vehiclePickupLocation: diffPickupLocation ? pickupLocation.trim() : null,
    });
  }

  return (
    <div className="card">
      <h2>1ος Χρόνος — Παραλαβή οχήματος</h2>
      <p className="muted">
        Επίλεξε το όχημα από τον στόλο σου. Για να προσθέσεις νέο όχημα, πήγαινε
        στο tab «Οχήματα».
      </p>

      {loading && <p className="muted">Φόρτωση στόλου…</p>}

      {!loading && vehicles.length === 0 && (
        <div className="alert alert-error">
          ⚠️ Δεν έχεις καταχωρήσει ακόμη κανένα όχημα στον στόλο σου. Πήγαινε
          στο tab «Οχήματα» για να προσθέσεις τις πινακίδες που ενοικιάζεις.
        </div>
      )}

      {!loading && vehicles.length > 0 && (
        <>
          <label className="field-label">
            Όχημα:
            <select
              className="input"
              value={plate}
              onChange={(e) => setPlate(e.target.value)}
              disabled={disabled}
            >
              <option value="">— Επίλεξε όχημα —</option>
              {vehicles.map((v) => (
                <option key={v.id} value={v.plate}>
                  {v.plate}
                  {v.label ? ` — ${v.label}` : ""}
                </option>
              ))}
            </select>
          </label>

          <label className="field-label">
            Σκοπός Κίνησης Οχήματος:
            <select
              className="input"
              value={movementPurpose}
              onChange={(e) => setMovementPurpose(e.target.value)}
              disabled={disabled}
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
              disabled={disabled}
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
                disabled={disabled}
              />
            </label>
          )}

          {error && <div className="alert alert-error">{error}</div>}

          <div className="sticky-cta">
            <button
              className="btn btn-primary btn-block"
              onClick={handleConfirm}
              disabled={disabled}
            >
              ➕ Δημιουργία εγγραφής (SendClient)
            </button>
          </div>
        </>
      )}

      {!loading && vehicles.length === 0 && error && (
        <div className="alert alert-error">{error}</div>
      )}
    </div>
  );
}
