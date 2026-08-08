"""
routes_customers.py
--------------------------------------------------------------------
Βάση Πελατών/Οχημάτων — λίστα (με αναζήτηση) + επεξεργασία στοιχείων.
Ξεχωριστό από τα /api/dcl/entries: εδώ είναι ΜΙΑ γραμμή ανά πινακίδα με τα
στοιχεία επαφής (όνομα/ΑΦΜ/τηλέφωνο) που κρατά ήδη το μοντέλο Customer.
--------------------------------------------------------------------
"""
import aade_core
from auth import require_auth
from flask import Blueprint, g, jsonify, request
from models import Customer, db

customers_bp = Blueprint("customers", __name__)


@customers_bp.route("/api/customers", methods=["GET"])
@require_auth
def list_customers():
    q = (request.args.get("q") or "").strip()
    query = Customer.query.filter_by(workshop_id=g.workshop_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Customer.plate.ilike(like),
                Customer.name.ilike(like),
                Customer.vat.ilike(like),
                Customer.phone.ilike(like),
            )
        )
    customers = query.order_by(Customer.plate.asc()).all()
    return jsonify([c.to_dict() for c in customers])


# Ελαφριά εκδοχή του παραπάνω: ΜΟΝΟ plate/name, όχι όλο το Customer
# (vat, phone, vehicleCategory, ...). Το CameraCapture τη φορτώνει σε
# ΚΑΘΕ άνοιγμα κάμερας για το "μήπως εννοείς" — δεν χρειάζεται τίποτα
# παραπάνω από αυτά τα δύο πεδία, οπότε with_entities() ώστε η SQL να
# μη διαβάζει/επιστρέφει τις υπόλοιπες στήλες.
@customers_bp.route("/api/customers/plates", methods=["GET"])
@require_auth
def list_customer_plates():
    rows = (
        Customer.query.filter_by(workshop_id=g.workshop_id)
        .with_entities(Customer.plate, Customer.name)
        .all()
    )
    return jsonify([{"plate": plate, "name": name} for plate, name in rows])


@customers_bp.route("/api/customers/<int:customer_id>", methods=["PATCH"])
@require_auth
def update_customer(customer_id):
    customer = Customer.query.filter_by(
        id=customer_id, workshop_id=g.workshop_id
    ).first()
    if customer is None:
        raise aade_core.ApiError("Δεν βρέθηκε ο πελάτης.", 404)

    data = request.get_json(silent=True) or {}
    if "name" in data:
        customer.name = (data.get("name") or "").strip() or None
    if "vat" in data:
        vat = (data.get("vat") or "").strip()
        if vat and not (vat.isdigit() and len(vat) == 9):
            raise aade_core.ApiError("Το ΑΦΜ πρέπει να είναι 9 ψηφία.")
        customer.vat = vat or None
    if "phone" in data:
        customer.phone = (data.get("phone") or "").strip() or None

    db.session.commit()
    return jsonify(customer.to_dict())
