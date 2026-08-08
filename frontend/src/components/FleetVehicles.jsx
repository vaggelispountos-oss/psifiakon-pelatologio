// components/FleetVehicles.jsx
// Στόλος οχημάτων (μόνο Ενοικιάσεις) — ο ιδιοκτήτης καταχωρεί ΕΔΩ τις
// πινακίδες που πραγματικά κατέχει/ενοικιάζει. Η φόρμα «Νέα ενοικίαση»
// επιτρέπει επιλογή ΜΟΝΟ από αυτή τη λίστα (dropdown, όχι ελεύθερο κείμενο) —
// το backend το επιβάλλει ούτως ή άλλως (δες create_entry: 400 αν η πινακίδα
// δεν ανήκει στον στόλο).
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getFleetVehicles,
  createFleetVehicle,
  updateFleetVehicle,
  deleteFleetVehicle,
} from "../services/api";
import { normalizePlateInput } from "../utils";
import { VEHICLE_CATEGORIES } from "../constants";

function categoryMeta(value) {
  return (
    VEHICLE_CATEGORIES.find((c) => c.value === value) || VEHICLE_CATEGORIES[0]
  );
}

// Καταστάσεις που σημαίνουν "το όχημα είναι έξω, δεν έχει επιστραφεί ακόμα".
const ACTIVE_RENTAL_STATUSES = new Set(["open", "in_progress"]);

// Διαθέσιμο (λαχανί) / Ενοικιασμένο (κίτρινο) / Θέμα με τον χρόνο επιστροφής (κόκκινο)
function vehicleStatus(plate, entries) {
  let rented = false;
  let overdue = false;
  for (const e of entries || []) {
    if (e.plate !== plate || !ACTIVE_RENTAL_STATUSES.has(e.status)) continue;
    rented = true;
    if (e.isOverdue) overdue = true;
  }
  if (overdue) return { key: "overdue", label: "Εκπρόθεσμο", cls: "vehicle-status-overdue" };
  if (rented) return { key: "rented", label: "Ενοικιασμένο", cls: "vehicle-status-rented" };
  return { key: "available", label: "Διαθέσιμο", cls: "vehicle-status-available" };
}

function EditRow({ vehicle, onCancel, onSaved }) {
  const [plate, setPlate] = useState(vehicle.plate || "");
  const [label, setLabel] = useState(vehicle.label || "");
  const [category, setCategory] = useState(vehicle.category || "car");
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
        category,
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
      <td colSpan={4}>
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
          <label className="field-label">
            Κατηγορία
            <select
              className="input"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {VEHICLE_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.icon} {c.label}
                </option>
              ))}
            </select>
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

export default function FleetVehicles({ entries }) {
  const queryClient = useQueryClient();
  const vehiclesQuery = useQuery({
    queryKey: ["fleetVehicles"],
    queryFn: getFleetVehicles,
    placeholderData: (prev) => prev,
  });
  const vehicles = vehiclesQuery.data || [];
  const loading = vehiclesQuery.isFetching;
  const [actionError, setActionError] = useState("");
  const error = vehiclesQuery.error?.message || actionError;
  const [editingId, setEditingId] = useState(null);

  const [newPlate, setNewPlate] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [newCategory, setNewCategory] = useState("car");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState("");

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["fleetVehicles"] });

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
      await createFleetVehicle({
        plate,
        label: newLabel.trim(),
        category: newCategory,
      });
      await refresh();
      setNewPlate("");
      setNewLabel("");
      setNewCategory("car");
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
      await refresh();
    } catch (err) {
      setActionError(err.message);
    }
  }

  return (
    <div className="card">
      <div className="list-header">
        <h2>Στόλος Οχημάτων</h2>
        <button className="btn btn-ghost btn-sm" onClick={refresh}>
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
        <label className="field-label">
          Κατηγορία
          <select
            className="input"
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value)}
          >
            {VEHICLE_CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.icon} {c.label}
              </option>
            ))}
          </select>
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
                <th>Κατηγορία</th>
                <th>Κατάσταση</th>
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
                      onSaved={() => {
                        refresh();
                        setEditingId(null);
                      }}
                    />
                  );
                }
                const status = vehicleStatus(v.plate, entries);
                const cat = categoryMeta(v.category);
                return (
                  <tr key={v.id}>
                    <td className="mono">{v.plate}</td>
                    <td>{v.label || "—"}</td>
                    <td>
                      {cat.icon} {cat.label}
                    </td>
                    <td>
                      <span className={`vehicle-status-badge ${status.cls}`}>
                        {status.label}
                      </span>
                    </td>
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
