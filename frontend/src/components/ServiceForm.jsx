// components/ServiceForm.jsx
// 2ος Χρόνος — Επιλογή Κατηγορίας Παρεχόμενης Υπηρεσίας.
// Οι πρώτες 3 κατηγορίες καλύπτουν σχεδόν όλες τις επισκέψεις — εμφανίζονται
// ως μεγάλα πλήκτρα tap-to-select (ένα tap) αντί για dropdown (tap + scroll +
// tap). Οι υπόλοιπες 4 (σπάνιες περιπτώσεις) κρύβονται πίσω από «Άλλη
// περίπτωση» ώστε να μη ανταγωνίζονται οπτικά τις συνηθισμένες επιλογές.
import { useState } from "react";
import { SERVICE_CATEGORIES, SERVICE_CATEGORY_OTHER } from "../constants";

const PRIMARY_VALUES = [1, 2, 3];
const PRIMARY_CATEGORIES = SERVICE_CATEGORIES.filter((c) =>
  PRIMARY_VALUES.includes(c.value)
);
const OTHER_CATEGORIES = SERVICE_CATEGORIES.filter(
  (c) => !PRIMARY_VALUES.includes(c.value)
);

export default function ServiceForm({ onSubmit, disabled }) {
  const [category, setCategory] = useState("");
  const [showOther, setShowOther] = useState(false);
  const [other, setOther] = useState("");
  const [comments, setComments] = useState("");
  const [error, setError] = useState("");

  const isOtherText = Number(category) === SERVICE_CATEGORY_OTHER;

  function selectCategory(value) {
    setCategory(String(value));
    setError("");
  }

  function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (!category) {
      setError("Επίλεξε κατηγορία παρεχόμενης υπηρεσίας.");
      return;
    }
    if (isOtherText && !other.trim()) {
      setError("Για «Λοιπά» το πεδίο ελεύθερου κειμένου είναι υποχρεωτικό.");
      return;
    }

    onSubmit({
      providedServiceCategory: Number(category),
      providedServiceCategoryOther: isOtherText ? other.trim() : null,
      comments: comments.trim() || null,
    });
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      <h2>Τι έγινε;</h2>

      <div className="choice-list">
        {PRIMARY_CATEGORIES.map((c) => (
          <button
            key={c.value}
            type="button"
            className={`choice-btn${category === String(c.value) ? " is-selected" : ""}`}
            onClick={() => selectCategory(c.value)}
            disabled={disabled}
          >
            {c.label}
          </button>
        ))}
      </div>

      {!showOther ? (
        <button
          type="button"
          className="link-btn"
          onClick={() => setShowOther(true)}
        >
          ⌄ Άλλη περίπτωση
        </button>
      ) : (
        <div className="choice-list">
          {OTHER_CATEGORIES.map((c) => (
            <button
              key={c.value}
              type="button"
              className={`choice-btn${category === String(c.value) ? " is-selected" : ""}`}
              onClick={() => selectCategory(c.value)}
              disabled={disabled}
            >
              {c.label}
            </button>
          ))}
        </div>
      )}

      {isOtherText && (
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

      <button className="btn btn-primary btn-block" disabled={disabled || !category}>
        Καταχώρηση εργασίας
      </button>
    </form>
  );
}
