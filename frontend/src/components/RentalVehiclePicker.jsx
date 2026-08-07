// components/RentalVehiclePicker.jsx
// 1ος Χρόνος για Ενοικιάσεις — αντί για κάμερα/OCR, ο χρήστης βλέπει ΜΙΑ λίστα
// με τα διαθέσιμα οχήματα του στόλου του (δες tab «Οχήματα» / FleetVehicles.jsx)
// και πατάει πάνω σε αυτό που παραδίδει. Ο στόλος είναι σταθερός/λίγα οχήματα
// — μια λίστα με κλικ είναι πιο γρήγορη από dropdown. Οχήματα που έχουν ήδη
// ανοιχτή ενοικίαση εμφανίζονται ως μη διαθέσιμα και δεν επιλέγονται — το
// backend το επιβάλλει ούτως ή άλλως (create_entry: 400 αν η πινακίδα δεν
// ανήκει στον στόλο), εδώ απλά δεν αφήνουμε τον χρήστη να διαλέξει κάτι εκτός
// λίστας ή κάτι ήδη σε κίνηση.
import { useEffect, useMemo, useState } from "react";
import { getFleetVehicles } from "../services/api";
import { VEHICLE_CATEGORIES, VEHICLE_MOVEMENT_PURPOSES } from "../constants";

// Καταστάσεις που σημαίνουν "το όχημα είναι έξω, δεν έχει επιστραφεί ακόμα".
const ACTIVE_RENTAL_STATUSES = new Set(["open", "in_progress"]);

// Ομαδοποιεί μια λίστα οχημάτων ανά κατηγορία, με τη σειρά του
// VEHICLE_CATEGORIES — επιστρέφει μόνο τις κατηγορίες που έχουν όχημα.
function groupByCategory(vehicles) {
  const groups = new Map();
  for (const v of vehicles) {
    const key = v.category || "car";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(v);
  }
  return VEHICLE_CATEGORIES.filter((c) => groups.has(c.value)).map((c) => ({
    ...c,
    vehicles: groups.get(c.value),
  }));
}

export default function RentalVehiclePicker({ onConfirm, disabled, entries }) {
  const [vehicles, setVehicles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [plate, setPlate] = useState("");
  const [movementPurpose, setMovementPurpose] = useState("");
  const [diffPickupLocation, setDiffPickupLocation] = useState(false);
  const [pickupLocation, setPickupLocation] = useState("");
  const [expectedDays, setExpectedDays] = useState("");

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

  // Πινακίδες που είναι ΤΩΡΑ σε ανοιχτή ενοικίαση -> δεν επιλέγονται.
  const busyPlates = useMemo(() => {
    const set = new Set();
    for (const e of entries || []) {
      if (ACTIVE_RENTAL_STATUSES.has(e.status)) set.add(e.plate);
    }
    return set;
  }, [entries]);

  const availableVehicles = useMemo(
    () => vehicles.filter((v) => !busyPlates.has(v.plate)),
    [vehicles, busyPlates]
  );
  const unavailableVehicles = useMemo(
    () => vehicles.filter((v) => busyPlates.has(v.plate)),
    [vehicles, busyPlates]
  );

  const availableGroups = useMemo(
    () => groupByCategory(availableVehicles),
    [availableVehicles]
  );
  const unavailableGroups = useMemo(
    () => groupByCategory(unavailableVehicles),
    [unavailableVehicles]
  );

  // Πινακίδες που είναι σε ανοιχτή ενοικίαση ΚΑΙ έχει περάσει η αναμενόμενη
  // ημερομηνία επιστροφής -> κόκκινο (θέμα καιρός), αλλιώς κίτρινο.
  const overduePlates = useMemo(() => {
    const set = new Set();
    for (const e of entries || []) {
      if (ACTIVE_RENTAL_STATUSES.has(e.status) && e.isOverdue) set.add(e.plate);
    }
    return set;
  }, [entries]);

  function handleSelect(v) {
    if (disabled) return;
    setPlate(v.plate);
    setError("");
  }

  function handleConfirm() {
    if (!plate) {
      setError("Επίλεξε όχημα από τη λίστα.");
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
    if (expectedDays && Number(expectedDays) <= 0) {
      setError("Ο αριθμός ημερών πρέπει να είναι θετικός.");
      return;
    }
    setError("");
    onConfirm(plate, {
      vehicleMovementPurpose: Number(movementPurpose),
      isDiffVehPickupLocation: diffPickupLocation,
      vehiclePickupLocation: diffPickupLocation ? pickupLocation.trim() : null,
      rentalExpectedDays: expectedDays ? Number(expectedDays) : null,
    });
  }

  return (
    <div className="card">
      <h2>1ος Χρόνος — Παραλαβή οχήματος</h2>
      <p className="muted">
        Πάτησε το όχημα που παραδίδεις. Για να προσθέσεις νέο όχημα, πήγαινε
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
          {availableVehicles.length === 0 && (
            <div className="alert alert-warn">
              ⏰ Όλα τα οχήματα του στόλου είναι αυτή τη στιγμή σε ενοικίαση.
            </div>
          )}

          {availableGroups.map((group) => (
            <div key={group.value} style={{ marginTop: 12 }}>
              <p className="muted small vehicle-category-heading">
                {group.icon} {group.label}
              </p>
              <div className="vehicle-picker-list">
                {group.vehicles.map((v) => (
                  <button
                    key={v.id}
                    type="button"
                    className={`vehicle-pick-btn vehicle-pick-btn-available ${plate === v.plate ? "vehicle-pick-btn-active" : ""}`}
                    onClick={() => handleSelect(v)}
                    disabled={disabled}
                  >
                    <span className="mono">{v.plate}</span>
                    {v.label && <span className="small">{v.label}</span>}
                  </button>
                ))}
              </div>
            </div>
          ))}

          {unavailableGroups.length > 0 && (
            <>
              <p className="muted small" style={{ marginTop: 20 }}>
                Σε ενοικίαση τώρα (μη διαθέσιμα):
              </p>
              {unavailableGroups.map((group) => (
                <div key={group.value} style={{ marginTop: 8 }}>
                  <p className="muted small vehicle-category-heading">
                    {group.icon} {group.label}
                  </p>
                  <div className="vehicle-picker-list">
                    {group.vehicles.map((v) => {
                      const overdue = overduePlates.has(v.plate);
                      return (
                        <div
                          key={v.id}
                          className={`vehicle-pick-btn vehicle-pick-btn-disabled ${overdue ? "vehicle-pick-btn-overdue" : "vehicle-pick-btn-rented"}`}
                        >
                          <span className="mono">{v.plate}</span>
                          {v.label && <span className="small">{v.label}</span>}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </>
          )}

          {plate && (
            <>
              <label className="field-label" style={{ marginTop: 16 }}>
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

              <label className="field-label">
                Για πόσες μέρες; (προαιρετικό)
                <input
                  className="input"
                  type="number"
                  min="1"
                  step="1"
                  value={expectedDays}
                  onChange={(e) => setExpectedDays(e.target.value)}
                  placeholder="π.χ. 2"
                  disabled={disabled}
                />
              </label>
              <p className="muted small">
                Δεν στέλνεται στην ΑΑΔΕ — χρησιμοποιείται μόνο για να σε
                προειδοποιήσουμε αν το όχημα δεν έχει επιστραφεί όταν περάσουν
                οι μέρες αυτές.
              </p>
            </>
          )}

          {error && <div className="alert alert-error">{error}</div>}

          {plate && (
            <div className="sticky-cta">
              <button
                className="btn btn-primary btn-block"
                onClick={handleConfirm}
                disabled={disabled}
              >
                ➕ Δημιουργία εγγραφής (SendClient)
              </button>
            </div>
          )}
        </>
      )}

      {!loading && vehicles.length === 0 && error && (
        <div className="alert alert-error">{error}</div>
      )}
    </div>
  );
}
