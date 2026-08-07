// components/ServiceForm.jsx
// 2ος Χρόνος — Επιλογή Κατηγορίας Παρεχόμενης Υπηρεσίας.
import { useState } from "react";
import { SERVICE_CATEGORIES, SERVICE_CATEGORY_OTHER } from "../constants";

export default function ServiceForm({ onSubmit, disabled }) {
  const [category, setCategory] = useState("");
  const [other, setOther] = useState("");
  const [comments, setComments] = useState("");
  const [error, setError] = useState("");

  const isOther = Number(category) === SERVICE_CATEGORY_OTHER;

  function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (!category) {
      setError("Επίλεξε κατηγορία παρεχόμενης υπηρεσίας.");
      return;
    }
    if (isOther && !other.trim()) {
      setError("Για «Λοιπά» το πεδίο ελεύθερου κειμένου είναι υποχρεωτικό.");
      return;
    }

    onSubmit({
      providedServiceCategory: Number(category),
      providedServiceCategoryOther: isOther ? other.trim() : null,
      comments: comments.trim() || null,
    });
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>Κατηγορία εργασίας</h2>

      <label className="field-label">
        Κατηγορία Παρεχόμενης Υπηρεσίας:
        <select
          className="input"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">— Επίλεξε —</option>
          {SERVICE_CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.value} — {c.label}
            </option>
          ))}
        </select>
      </label>

      {isOther && (
        <label className="field-label">
          Περιγραφή (Λοιπά) — υποχρεωτικό:
          <input
            className="input"
            type="text"
            value={other}
            onChange={(e) => setOther(e.target.value)}
            placeholder="Περιέγραψε την υπηρεσία"
          />
        </label>
      )}

      <label className="field-label">
        Σχόλια (προαιρετικά):
        <textarea
          className="input"
          rows={2}
          value={comments}
          onChange={(e) => setComments(e.target.value)}
        />
      </label>

      {error && <div className="alert alert-error">{error}</div>}

      <button className="btn btn-primary btn-block" disabled={disabled}>
        Καταχώρηση εργασίας
      </button>
    </form>
  );
}
