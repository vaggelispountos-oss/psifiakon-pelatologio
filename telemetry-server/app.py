"""
telemetry-server/app.py
--------------------------------------------------------------------
ΞΕΧΩΡΙΣΤΟΣ, ελαφρύς server που ΕΣΥ (ο πωλητής του λογισμικού) φιλοξενείς σε
δικό σου μηχάνημα/υπηρεσία (π.χ. Render, Railway, μικρό VPS) — ΟΧΙ στο
μηχάνημα του κάθε συνεργείου-πελάτη.

Σκοπός: κάθε εγκατάσταση του backend/ (δες config.py -> TELEMETRY_URL) στέλνει
εδώ ΜΙΑ γραμμή ανά σάρωση πινακίδας, ώστε να βλέπεις συγκεντρωτικά στοιχεία
από ΟΛΟΥΣ τους πελάτες μαζί (πόσο καλά δουλεύει το OCR, πόσο συχνά χρειάζεται
χειροκίνητη διόρθωση) ΧΩΡΙΣ να χρειάζεσαι πρόσβαση στο μηχάνημα του καθενός.

Routes:
    POST /ingest    <- εδώ στέλνουν τα backend εγκαταστάσεων (χρειάζεται
                       header X-Telemetry-Key να ταιριάζει με INGEST_KEY)
    GET  /dashboard?key=... <- η δική σου προβολή (προστατευμένη με DASHBOARD_KEY)
    GET  /health

Τρέξιμο τοπικά:
    pip install -r requirements.txt
    cp .env.example .env    # και συμπλήρωσε τα keys
    python app.py
--------------------------------------------------------------------
"""
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class CentralMetric(db.Model):
    """Ένα αντίγραφο κάθε OcrMetric που έστειλε ΟΠΟΙΑΔΗΠΟΤΕ εγκατάσταση."""

    __tablename__ = "central_metrics"

    id = db.Column(db.Integer, primary_key=True)
    received_at = db.Column(db.DateTime, default=utcnow)

    installation_id = db.Column(db.String(32), nullable=False, index=True)

    mode = db.Column(db.String(10), nullable=True)
    engine = db.Column(db.String(30), nullable=True)
    # ΔΕΝ αποθηκεύουμε ποτέ την πραγματική πινακίδα (προσωπικό δεδομένο του
    # πελάτη του συνεργείου) — μόνο αν αναγνωρίστηκε κάτι ή όχι.
    ocr_success = db.Column(db.Boolean, nullable=True)
    confidence = db.Column(db.Integer, nullable=True)
    warnings_count = db.Column(db.Integer, nullable=True)
    parser_corrected = db.Column(db.Boolean, nullable=True)
    user_edited = db.Column(db.Boolean, nullable=True)
    confirmed = db.Column(db.Boolean, nullable=True)
    # Πότε έγινε η σάρωση στην πλευρά του πελάτη (μπορεί να διαφέρει λίγο από
    # το received_at λόγω δικτύου/καθυστέρησης προώθησης).
    client_created_at = db.Column(db.String(40), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "receivedAt": self.received_at.isoformat() if self.received_at else None,
            "installationId": self.installation_id,
            "mode": self.mode,
            "engine": self.engine,
            "ocrSuccess": self.ocr_success,
            "confidence": self.confidence,
            "warningsCount": self.warnings_count,
            "parserCorrected": self.parser_corrected,
            "userEdited": self.user_edited,
            "confirmed": self.confirmed,
            "clientCreatedAt": self.client_created_at,
        }


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'telemetry.db')}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    with app.app_context():
        db.create_all()

    register_routes(app)
    return app


def _is_local_dev():
    """True ΜΟΝΟ όταν τρέχει ρητά σε development mode (τοπικά)."""
    return os.getenv("FLASK_ENV", "").strip().lower() == "development"


def register_routes(app):
    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"})

    @app.route("/ingest", methods=["POST"])
    def ingest():
        expected_key = os.getenv("INGEST_KEY", "").strip()
        # Fail CLOSED: αν δεν έχει οριστεί INGEST_KEY και ΔΕΝ τρέχουμε τοπικά σε
        # development, αρνήσου την κλήση αντί να δέχεσαι δεδομένα από
        # οποιονδήποτε χωρίς κανένα κλειδί (ξεχασμένο env var σε production).
        if not expected_key:
            if _is_local_dev():
                pass  # τοπικό dev — επιτρέπεται σκόπιμα χωρίς κλειδί
            else:
                return jsonify(
                    {"error": "Ο server δεν έχει ρυθμιστεί (λείπει INGEST_KEY)."}
                ), 503
        elif request.headers.get("X-Telemetry-Key") != expected_key:
            return jsonify({"error": "Μη έγκυρο κλειδί."}), 401

        data = request.get_json(silent=True) or {}
        installation_id = (data.get("installationId") or "unknown").strip()

        # ocrPlate/finalPlate δεν στέλνονται πλέον από τον client (data
        # minimization) — αν κάποιο παλιό client τα στείλει ακόμη, αγνοούνται
        # ρητά εδώ ώστε να ΜΗΝ καταλήξει ποτέ πινακίδα σε αυτή τη βάση.
        row = CentralMetric(
            installation_id=installation_id,
            mode=data.get("mode"),
            engine=data.get("engine"),
            ocr_success=bool(data.get("ocrSuccess", bool(data.get("ocrPlate")))),
            confidence=data.get("confidence"),
            warnings_count=data.get("warningsCount"),
            parser_corrected=data.get("parserCorrected"),
            user_edited=data.get("userEdited"),
            confirmed=data.get("confirmed"),
            client_created_at=data.get("createdAt"),
        )
        db.session.add(row)
        db.session.commit()
        return jsonify({"ok": True}), 201

    @app.route("/dashboard", methods=["GET"])
    def dashboard():
        expected_key = os.getenv("DASHBOARD_KEY", "").strip()
        # Fail CLOSED: χωρίς DASHBOARD_KEY το dashboard είναι δημόσιο σε
        # οποιονδήποτε βρει το URL — επιτρέπεται μόνο σε ρητό local dev.
        if not expected_key:
            if not _is_local_dev():
                return "Ο server δεν έχει ρυθμιστεί (λείπει DASHBOARD_KEY).", 503
        elif request.args.get("key") != expected_key:
            return "Μη εξουσιοδοτημένη πρόσβαση.", 401

        rows = CentralMetric.query.order_by(CentralMetric.received_at.desc()).all()
        total = len(rows)
        successes = sum(1 for r in rows if r.ocr_success)
        confirmed = [r for r in rows if r.confirmed]
        user_edited = sum(1 for r in confirmed if r.user_edited)
        confidences = [r.confidence for r in rows if r.confidence is not None]

        by_install = {}
        for r in rows:
            g = by_install.setdefault(
                r.installation_id, {"total": 0, "successes": 0, "confirmed": 0, "user_edited": 0}
            )
            g["total"] += 1
            if r.ocr_success:
                g["successes"] += 1
            if r.confirmed:
                g["confirmed"] += 1
                if r.user_edited:
                    g["user_edited"] += 1

        return render_template_string(
            DASHBOARD_TEMPLATE,
            total=total,
            successes=successes,
            failures=total - successes,
            success_rate=round(successes / total * 100, 1) if total else None,
            user_edited=user_edited,
            user_edited_rate=round(user_edited / len(confirmed) * 100, 1)
            if confirmed
            else None,
            avg_confidence=round(sum(confidences) / len(confidences), 1)
            if confidences
            else None,
            by_install=sorted(by_install.items()),
            rows=rows[:100],
        )


DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="el">
<head>
<meta charset="utf-8">
<title>OCR Telemetry — Dashboard</title>
<style>
  body { background:#0f1117; color:#e5e7eb; font-family:system-ui,sans-serif; padding:24px; }
  h1 { font-size:1.3rem; }
  h2 { font-size:1.05rem; margin-top:28px; color:#93c5fd; }
  .cards { display:flex; gap:14px; flex-wrap:wrap; margin:14px 0; }
  .card { background:#1a1d27; border:1px solid #2a2e3a; border-radius:10px; padding:14px 18px; min-width:120px; }
  .num { font-size:1.6rem; font-weight:700; display:block; }
  .lbl { font-size:0.78rem; color:#9ca3af; }
  table { border-collapse:collapse; width:100%; margin-top:8px; font-size:0.85rem; }
  th, td { text-align:left; padding:6px 10px; border-bottom:1px solid #2a2e3a; }
  th { color:#9ca3af; font-weight:600; }
  .mono { font-family:ui-monospace,monospace; }
  .yes { color:#4ade80; } .no { color:#f87171; }
</style>
</head>
<body>
  <h1>🔧 OCR Telemetry — Συγκεντρωτικά όλων των εγκαταστάσεων</h1>

  <div class="cards">
    <div class="card"><span class="num">{{ total }}</span><span class="lbl">Σαρώσεις</span></div>
    <div class="card"><span class="num">{{ success_rate if success_rate is not none else "—" }}%</span><span class="lbl">Ποσοστό επιτυχίας</span></div>
    <div class="card"><span class="num">{{ failures }}</span><span class="lbl">Αποτυχίες</span></div>
    <div class="card"><span class="num">{{ user_edited }}</span><span class="lbl">Χειροκίνητες διορθώσεις</span></div>
    <div class="card"><span class="num">{{ user_edited_rate if user_edited_rate is not none else "—" }}%</span><span class="lbl">Ποσοστό διόρθωσης</span></div>
    <div class="card"><span class="num">{{ avg_confidence if avg_confidence is not none else "—" }}%</span><span class="lbl">Μέση βεβαιότητα</span></div>
  </div>

  <h2>Ανά εγκατάσταση (συνεργείο)</h2>
  <table>
    <thead><tr><th>Installation ID</th><th>Σαρώσεις</th><th>Επιτυχίες</th><th>Επιβεβαιωμένες</th><th>Διορθώσεις</th></tr></thead>
    <tbody>
      {% for install_id, g in by_install %}
      <tr>
        <td class="mono">{{ install_id }}</td>
        <td>{{ g.total }}</td>
        <td>{{ g.successes }}</td>
        <td>{{ g.confirmed }}</td>
        <td>{{ g.user_edited }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <h2>Τελευταίες 100 σαρώσεις</h2>
  <table>
    <thead><tr><th>Ώρα</th><th>Εγκατάσταση</th><th>Τύπος</th><th>Μηχανή</th><th>OCR</th><th>Βεβαιότητα</th><th>Διορθώθηκε;</th></tr></thead>
    <tbody>
      {% for r in rows %}
      <tr>
        <td>{{ r.received_at.strftime("%d/%m %H:%M") if r.received_at else "—" }}</td>
        <td class="mono">{{ r.installation_id }}</td>
        <td>{{ r.mode or "—" }}</td>
        <td>{{ r.engine or "—" }}</td>
        <td>{% if r.ocr_success %}<span class="yes">✅</span>{% else %}<span class="no">❌</span>{% endif %}</td>
        <td>{{ r.confidence if r.confidence is not none else "—" }}{{ "%" if r.confidence is not none else "" }}</td>
        <td>
          {% if not r.confirmed %}—
          {% elif r.user_edited %}<span class="no">✏️ Ναι</span>
          {% else %}<span class="yes">✅ Όχι</span>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
"""


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_ENV") == "development")
