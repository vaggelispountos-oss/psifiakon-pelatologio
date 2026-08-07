// components/RentalVehiclePicker.jsx
// 1ος Χρόνος για Ενοικιάσεις — αντί για κάμερα/OCR, ο χρήστης βλέπει ΜΙΑ λίστα
// με τα διαθέσιμα οχήματα του στόλου του (δες tab «Οχήματα» / FleetVehicles.jsx)
// και πατάει πάνω σε αυτό που παραδίδει. Δύο ρητά βήματα αντί για ένα σελίδα
// που μεγαλώνει καθώς επιλέγεις: 1) διάλεξε όχημα (grid, ένα tap) 2) στοιχεία
// παράδοσης. Ο στόλος είναι σταθερός/λίγα οχήματα — μια λίστα με κλικ είναι
// πιο γρήγορη από dropdown. Οχήματα που έχουν ήδη ανοιχτή ενοικίαση
// εμφανίζονται ως μη διαθέσιμα και δεν επιλέγονται — το backend το επιβάλλει
// ούτως ή άλλως (create_entry: 400 αν η πινακίδα δεν ανήκει στον στόλο), εδώ
// απλά δεν αφήνουμε τον χρήστη να διαλέξει κάτι εκτός λίστας ή σε κίνηση.
import { useEffect, useMemo, useState } from "react";
import { getFleetVehicles } from "../services/api";
import { VEHICLE_CATEGORIES, VEHICLE_MOVEMENT_PURPOSES } from "../constants";

// Καταστάσεις που σημαίνουν "το όχημα είναι έξω, δεν έχει επιστραφεί ακόμα".
const ACTIVE_RENTAL_STATUSES = new Set(["open", "in_progress"]);

// Σκοπός Κίνησης Οχήματος: η "Ενοικίαση" (1) καλύπτει σχεδόν όλες τις
// παραδόσεις — προεπιλέγεται, ο χρήστης το αλλάζει μόνο στην σπάνια
// περίπτωση Ιδιόχρησης/Δωρεάν Υπηρεσίας (πίσω από «Περισσότερα»).
const DEFAULT_MOVEMENT_PURPOSE = "1";

// Γρήγορες επιλογές διάρκειας — πληκτρολόγηση αριθμού σε κινητό είναι αργή.
const DAY_CHIPS = [1, 2, 3, 7];

export default function RentalVehiclePicker({ onConfirm, disabled, entries }) {
  const [vehicles, setVehicles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeCategory, setActiveCategory] = useState(null);

  const [selected, setSelected] = useState(null); // επιλεγμένο όχημα (βήμα 2)
  const [renterName, setRenterName] = useState("");
  const [movementPurpose, setMovementPurpose] = useState(DEFAULT_MOVEMENT_PURPOSE);
  const [diffPickupLocation, setDiffPickupLocation] = useState(false);
  const [pickupLocation, setPickupLocation] = useState("");
  const [expectedDays, setExpectedDays] = useState("");
  const [showMore, setShowMore] = useState(false);

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

  // Ποιες κατηγορίες έχουν έστω ένα όχημα στον στόλο -> αυτές εμφανίζονται
  // ως κουτάκια επιλογής. Επιλέγεται μία τη φορά, ώστε η λίστα από κάτω να
  // μη γίνεται μακρόστενο χάος με όλα τα οχήματα μαζί.
  const categoriesPresent = useMemo(
    () =>
      VEHICLE_CATEGORIES.filter((c) =>
        vehicles.some((v) => (v.category || "car") === c.value)
      ),
    [vehicles]
  );

  // Προεπιλογή: η πρώτη κατηγορία που έχει όχημα (μόλις φορτώσει ο στόλος).
  useEffect(() => {
    if (activeCategory === null && categoriesPresent.length > 0) {
      setActiveCategory(categoriesPresent[0].value);
    }
  }, [activeCategory, categoriesPresent]);

  const availableInCategory = useMemo(
    () => availableVehicles.filter((v) => (v.category || "car") === activeCategory),
    [availableVehicles, activeCategory]
  );
  const unavailableInCategory = useMemo(
    () => unavailableVehicles.filter((v) => (v.category || "car") === activeCategory),
    [unavailableVehicles, activeCategory]
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
    setSelected(v);
    setError("");
  }

  function handleBack() {
    setSelected(null);
    setError("");
  }

  function handleConfirm() {
    if (diffPickupLocation && !pickupLocation.trim()) {
      setError("Συμπλήρωσε τον τόπο παραλαβής.");
      return;
    }
    if (expectedDays && Number(expectedDays) <= 0) {
      setError("Ο αριθμός ημερών πρέπει να είναι θετικός.");
      return;
    }
    setError("");
    onConfirm(selected.plate, {
      customerName: renterName.trim() || null,
      vehicleMovementPurpose: Number(movementPurpose),
      isDiffVehPickupLocation: diffPickupLocation,
      vehiclePickupLocation: diffPickupLocation ? pickupLocation.trim() : null,
      rentalExpectedDays: expectedDays ? Number(expectedDays) : null,
    });
  }

  // ---- Βήμα 2: στοιχεία παράδοσης, μόλις επιλεγεί όχημα ----
  if (selected) {
    return (
      <div className="card">
        <button type="button" className="link-btn" onClick={handleBack} disabled={disabled}>
          ← Αλλαγή οχήματος
        </button>
        <h2>
          <span className="mono">{selected.plate}</span>
          {selected.label ? ` · ${selected.label}` : ""}
        </h2>

        <label className="field-label">
          Όνομα ενοικιαστή (προαιρετικό):
          <input
            className="input"
            type="text"
            value={renterName}
            onChange={(e) => setRenterName(e.target.value)}
            placeholder="π.χ. Γιώργος Παπαδόπουλος"
            disabled={disabled}
          />
        </label>

        <label className="field-label">Για πόσες μέρες; (προαιρετικό)</label>
        <div className="day-chips">
          {DAY_CHIPS.map((d) => (
            <button
              key={d}
              type="button"
              className={`day-chip${String(d) === expectedDays ? " is-selected" : ""}`}
              onClick={() => setExpectedDays(String(d))}
              disabled={disabled}
            >
              {d}
            </button>
          ))}
          <input
            className="input day-chip-custom"
            type="number"
            min="1"
            step="1"
            value={expectedDays}
            onChange={(e) => setExpectedDays(e.target.value)}
            placeholder="άλλο"
            disabled={disabled}
          />
        </div>
        <p className="muted small">
          Δεν στέλνεται στην ΑΑΔΕ — χρησιμοποιείται μόνο για να σε
          προειδοποιήσουμε αν το όχημα δεν έχει επιστραφεί όταν περάσουν οι
          μέρες αυτές.
        </p>

        {!showMore ? (
          <button
            type="button"
            className="link-btn"
            onClick={() => setShowMore(true)}
          >
            ⌄ Περισσότερα (σκοπός κίνησης, τόπος παραλαβής)
          </button>
        ) : (
          <>
            <label className="field-label">
              Σκοπός Κίνησης Οχήματος:
              <select
                className="input"
                value={movementPurpose}
                onChange={(e) => setMovementPurpose(e.target.value)}
                disabled={disabled}
              >
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
          </>
        )}

        {error && <div className="alert alert-error">{error}</div>}

        <div className="sticky-cta">
          <button
            className="btn btn-primary btn-block"
            onClick={handleConfirm}
            disabled={disabled}
          >
            ➕ Παράδοση οχήματος
          </button>
        </div>
      </div>
    );
  }

  // ---- Βήμα 1: επιλογή οχήματος ----
  return (
    <div className="card">
      <h2>Παραλαβή οχήματος</h2>
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
          <div className="vehicle-category-tabs">
            {categoriesPresent.map((c) => (
              <button
                key={c.value}
                type="button"
                className={`vehicle-category-tab ${activeCategory === c.value ? "vehicle-category-tab-active" : ""}`}
                onClick={() => {
                  setActiveCategory(c.value);
                  setError("");
                }}
                disabled={disabled}
              >
                <span className="vehicle-category-tab-icon">{c.icon}</span>
                <span>{c.label}</span>
              </button>
            ))}
          </div>

          {availableInCategory.length === 0 && (
            <div className="alert alert-warn">
              ⏰ Όλα τα οχήματα αυτής της κατηγορίας είναι αυτή τη στιγμή σε
              ενοικίαση.
            </div>
          )}

          <div className="vehicle-picker-grid">
            {availableInCategory.map((v) => (
              <button
                key={v.id}
                type="button"
                className="vehicle-pick-btn vehicle-pick-btn-available"
                onClick={() => handleSelect(v)}
                disabled={disabled}
              >
                <span className="mono">{v.plate}</span>
                {v.label && <span className="small">{v.label}</span>}
              </button>
            ))}
          </div>

          {unavailableInCategory.length > 0 && (
            <>
              <p className="muted small" style={{ marginTop: 20 }}>
                Σε ενοικίαση τώρα (μη διαθέσιμα):
              </p>
              <div className="vehicle-picker-grid">
                {unavailableInCategory.map((v) => {
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
            </>
          )}

          {error && <div className="alert alert-error">{error}</div>}
        </>
      )}

      {!loading && vehicles.length === 0 && error && (
        <div className="alert alert-error">{error}</div>
      )}
    </div>
  );
}
