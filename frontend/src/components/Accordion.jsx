// components/Accordion.jsx
// --------------------------------------------------------------------
// Ελαφρύ accordion: μόνο ΜΙΑ ενότητα ανοιχτή τη φορά ώστε οι κάρτες να
// μην πιάνουν πολύ χώρο. Το περιεχόμενο δεν ξεφορτώνεται όταν κλείνει
// (μόνο κρύβεται), ώστε να μη χάνεται η κατάσταση (π.χ. τιμές φόρμας).
// --------------------------------------------------------------------
import { useState } from "react";

export default function Accordion({ sections, defaultOpen }) {
  const [openId, setOpenId] = useState(defaultOpen ?? sections[0]?.id ?? null);

  return (
    <div className="accordion">
      {sections.map((s) => {
        const isOpen = openId === s.id;
        return (
          <div key={s.id} className={`accordion-item card${isOpen ? " open" : ""}`}>
            <button
              type="button"
              className="accordion-header"
              onClick={() => setOpenId(isOpen ? null : s.id)}
              aria-expanded={isOpen}
            >
              <span>{s.title}</span>
              <span className="accordion-chevron">{isOpen ? "▾" : "▸"}</span>
            </button>
            <div className="accordion-body" hidden={!isOpen}>
              {s.render()}
            </div>
          </div>
        );
      })}
    </div>
  );
}
