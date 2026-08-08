"""
routes_settings.py
--------------------------------------------------------------------
Ρυθμίσεις ΑΑΔΕ (credentials) — GET/PUT, έλεγχος σύνδεσης, live/mock switch.

Οι routes εδώ χρησιμοποιούν helpers (ApiError, _get_settings, _build_aade,
_use_mock, _log_aade) που ζουν στο aade_core.py — κοινή λογική επεξεργασίας
ΑΑΔΕ, μοιρασμένη ανάμεσα σε πολλά blueprints (settings, dcl). Αναφορά μέσω
`aade_core.<helper>` (module attribute lookup) — ώστε ένα test που κάνει
monkeypatch σε `aade_core._build_aade` να πιάνει ΚΑΙ τις κλήσεις από εδώ.
--------------------------------------------------------------------
"""
import aade_core
from auth import require_auth
from flask import Blueprint, jsonify, request
from models import db

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/api/settings", methods=["GET"])
@require_auth
def get_settings():
    # Επιστρέφει ΠΑΝΤΑ masked key (ποτέ ολόκληρο).
    return jsonify(aade_core._get_settings().to_dict())


@settings_bp.route("/api/settings", methods=["PUT"])
@require_auth
def update_settings():
    data = request.get_json(silent=True) or {}
    settings = aade_core._get_settings()

    # --- Validation ---
    username = (data.get("aade_username") or "").strip()
    if not username:
        raise aade_core.ApiError("Το «Όνομα Χρήστη» είναι υποχρεωτικό.")

    branch = data.get("branch")
    try:
        branch = int(branch)
    except (TypeError, ValueError):
        raise aade_core.ApiError("Ο «Αριθμός Εγκατάστασης» πρέπει να είναι ακέραιος ≥ 0.")
    if branch < 0:
        raise aade_core.ApiError("Ο «Αριθμός Εγκατάστασης» πρέπει να είναι ≥ 0.")

    entity_vat = (data.get("entity_vat_number") or "").strip()
    if entity_vat and not (entity_vat.isdigit() and len(entity_vat) == 9):
        raise aade_core.ApiError("Το ΑΦΜ υπόχρεης οντότητας πρέπει να είναι 9 ψηφία.")

    # --- Αποθήκευση ---
    settings.aade_username = username
    settings.branch = branch
    settings.entity_vat_number = entity_vat or None

    # Το key: αν έρθει κενό ή masked (περιέχει •), ΜΗΝ το αντικαθιστάς.
    new_key = data.get("aade_subscription_key")
    if new_key and "•" not in new_key and new_key.strip():
        settings.aade_subscription_key = new_key.strip()

    db.session.commit()
    return jsonify(settings.to_dict())


# ----------------------------------------------------------------
# Έλεγχος σύνδεσης ΑΑΔΕ (ελαφριά κλήση RequestClients)
# ----------------------------------------------------------------
@settings_bp.route("/api/settings/test-connection", methods=["POST"])
@require_auth
def test_connection():
    settings = aade_core._get_settings()

    if not settings.has_key or not settings.aade_username:
        return jsonify({"ok": False, "reason": "Όρισε πρώτα κωδικούς ΑΑΔΕ."})

    # Σεβασμός mock/real switch (ίδια λογική με _build_aade: το per-workshop
    # force_real_aade υπερισχύει του global USE_MOCK_AADE).
    if aade_core._use_mock(settings):
        return jsonify(
            {"ok": True, "message": "Mock mode — δεν έγινε πραγματική κλήση"}
        )

    aade = aade_core._build_aade(settings)
    # Ελαφριά κλήση με dummy/μικρό dclid
    res = aade.request_clients(dclid=1)

    # Audit (system-level, χωρίς entry)
    aade_core._log_aade(None, "RequestClients", {"dclid": 1}, res, "error" not in res)
    db.session.commit()

    if "error" in res:
        return jsonify({"ok": False, "reason": res["error"]})
    return jsonify({"ok": True, "message": "Σύνδεση επιτυχής"})


# ----------------------------------------------------------------
# Live/Mock switch — αυτοεξυπηρέτηση από τον χρήστη (workshop-scoped).
# Ίδιο flag με το admin-only /api/admin/.../aade-mode, ώστε ο χρήστης
# να μπορεί να ενεργοποιήσει πραγματική ΑΑΔΕ χωρίς admin key.
# ----------------------------------------------------------------
@settings_bp.route("/api/settings/aade-mode", methods=["PUT"])
@require_auth
def set_own_aade_mode():
    settings = aade_core._get_settings()
    if not settings.has_key or not settings.aade_username:
        raise aade_core.ApiError(
            "Όρισε πρώτα τους κωδικούς ΑΑΔΕ πριν ενεργοποιήσεις πραγματική λειτουργία.",
            400,
        )
    data = request.get_json(silent=True) or {}
    settings.force_real_aade = bool(data.get("forceReal"))
    db.session.commit()
    return jsonify(settings.to_dict())
