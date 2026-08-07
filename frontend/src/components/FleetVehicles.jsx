// components/FleetVehicles.jsx
// Στόλος οχημάτων (μόνο Ενοικιάσεις) — ο ιδιοκτήτης καταχωρεί ΕΔΩ τις
// πινακίδες που πραγματικά κατέχει/ενοικιάζει. Η φόρμα «Νέα ενοικίαση»
// επιτρέπει επιλογή ΜΟΝΟ από αυτή τη λίστα (dropdown, όχι ελεύθερο κείμενο) —
// το backend το επιβάλλει ούτως ή άλλως (δες create_entry: 400 αν η πινακίδα
// δεν ανήκει στον στόλο).
import { useEffect, useState } from "react";
import {
  getFleetVehicles,
  createFleetVehicle,
  updateFleetVehicle,
  deleteFleetVehicle,
} from "../services/api";
import { normalizePlateInput } from "../utils";

function EditRow({ vehicle, onCancel, onSaved }) {
  const [plate, setPlate] = useState(vehicle.plate || "");
  const [label, setLabel] = useState(vehicle.label || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const updated = await updateFleetVehicle(vehicle.id, {
        plate: normalizePlateInput(plate),
        label: label.trim(),
      });
      onSaved(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <tr className="customer-edit-row">
      <td colSpan={3}>
        <form onSubmit={handleSave} className="customer-edit-form">
          <label className="field-label">
            Πινακίδα
            <input
              className="input mono"
              value={plate}
              onChange={(e) => setPlate(e.target.value)}
            />
          </label>
          <label className="field-label">
            Περιγραφή
            <input
              className="input"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="π.χ. Toyota Yaris λευκό"
            />
          </label>
          {error && (
            <div className="alert alert-error" style={{ flex: "1 1 100%" }}>
              {error}
            </div>
          )}
          <div style={{ display: "flex", gap: "8px", flex: "1 1 100%" }}>
            <button className="btn btn-primary btn-sm" disabled={saving}>
              {saving ? "Αποθήκευση…" : "Αποθήκευση"}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onCancel}
              disabled={saving}
            >
              Ακύρωση
            </button>
          </div>
        </form>
      </td>
    </tr>
  );
}

export default function FleetVehicles() {
  const [vehicles, setVehicles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState(null);

  const [newPlate, setNewPlate] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState("");

  async function load() {
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
  }

  useEffect(() => {
    load();
  }, []);

  async function handleAdd(e) {
    e.preventDefault();
    const plate = normalizePlateInput(newPlate);
    if (!plate) {
      setAddError("Συμπλήρωσε πινακίδα.");
      return;
    }
    setAdding(true);
    setAddError("");
    try {
      const created = await createFleetVehicle({ plate, label: newLabel.trim() });
      setVehicles((prev) =>
        [...prev, created].sort((a, b) => a.plate.localeCompare(b.plate))
      );
      setNewPlate("");
      setNewLabel("");
    } catch (err) {
      setAddError(err.message);
    } finally {
      setAdding(false);
    }
  }

  async function handleDelete(vehicle) {
    if (!window.confirm(`Διαγραφή του οχήματος ${vehicle.plate} από τον στόλο;`)) return;
    try {
      await deleteFleetVehicle(vehicle.id);
      setVehicles((prev) => prev.filter((v) => v.id !== vehicle.id));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="card">
      <div className="list-header">
        <h2>Στόλος Οχημάτων</h2>
        <button className="btn btn-ghost btn-sm" onClick={load}>
          ↻ Ανανέωση
        </button>
      </div>
      <p className="muted">
        Καταχώρησε εδώ τις πινακίδες των οχημάτων που διαθέτεις για ενοικίαση.
        Στη φόρμα «Νέα ενοικίαση» θα μπορείς να επιλέξεις ΜΟΝΟ από αυτή τη
        λίστα.
      </p>

      <form onSubmit={handleAdd} className="customer-edit-form" style={{ marginBottom: "16px" }}>
        <label className="field-label">
          Πινακίδα
          <input
            className="input mono"
            value={newPlate}
            onChange={(e) => setNewPlate(e.target.value)}
            placeholder="π.χ. ΙΚΧ-1833"
          />
        </label>
        <label className="field-label">
          Περιγραφή (προαιρετικό)
          <input
            className="input"
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            placeholder="π.χ. Toyota Yaris λευκό"
          />
        </label>
        {addError && (
          <div className="alert alert-error" style={{ flex: "1 1 100%" }}>
            {addError}
          </div>
        )}
        <button className="btn btn-primary btn-sm" disabled={adding}>
          {adding ? "Προσθήκη…" : "＋ Προσθήκη οχήματος"}
        </button>
      </form>

      {error && <div className="alert alert-error">{error}</div>}
      {loading && <p className="muted">Φόρτωση…</p>}
      {!loading && vehicles.length === 0 && (
        <p className="muted">Δεν έχεις προσθέσει ακόμη κανένα όχημα στον στόλο.</p>
      )}

      <div className="table-wrap">
        {vehicles.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Πινακίδα</th>
                <th>Περιγραφή</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {vehicles.map((v) => {
                if (editingId === v.id) {
                  return (
                    <EditRow
                      key={v.id}
                      vehicle={v}
                      onCancel={() => setEditingId(null)}
                      onSaved={(updated) => {
                        setVehicles((prev) =>
                          prev
                            .map((row) => (row.id === updated.id ? updated : row))
                            .sort((a, b) => a.plate.localeCompare(b.plate))
                        );
                        setEditingId(null);
                      }}
                    />
                  );
                }
                return (
                  <tr key={v.id}>
                    <td className="mono">{v.plate}</td>
                    <td>{v.label || "—"}</td>
                    <td style={{ display: "flex", gap: "8px" }}>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setEditingId(v.id)}
                      >
                        ✎ Επεξεργασία
                      </button>
                      <button
                        type="button"
                        className="btn btn-danger btn-sm"
                        onClick={() => handleDelete(v)}
                      >
                        🗑 Διαγραφή
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
