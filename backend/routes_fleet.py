"""
routes_fleet.py
--------------------------------------------------------------------
Στόλος οχημάτων (μόνο Ενοικιάσεις) — οι ΜΟΝΕΣ πινακίδες που επιτρέπεται
να επιλεγούν κατά τη δημιουργία νέας ενοικίασης (δες routes_dcl.create_entry).
--------------------------------------------------------------------
"""
import aade_core
from auth import require_auth
from flask import Blueprint, g, jsonify, request
from models import FleetVehicle, db

fleet_bp = Blueprint("fleet", __name__)


@fleet_bp.route("/api/fleet-vehicles", methods=["GET"])
@require_auth
def list_fleet_vehicles():
    vehicles = (
        FleetVehicle.query.filter_by(workshop_id=g.workshop_id)
        .order_by(FleetVehicle.plate.asc())
        .all()
    )
    return jsonify([v.to_dict() for v in vehicles])


@fleet_bp.route("/api/fleet-vehicles", methods=["POST"])
@require_auth
def create_fleet_vehicle():
    data = request.get_json(silent=True) or {}
    plate = aade_core._canonical_plate((data.get("plate") or "").strip())
    if not plate:
        raise aade_core.ApiError("Το πεδίο 'plate' (πινακίδα) είναι υποχρεωτικό.")

    existing = FleetVehicle.query.filter_by(
        workshop_id=g.workshop_id, plate=plate
    ).first()
    if existing is not None:
        raise aade_core.ApiError("Η πινακίδα υπάρχει ήδη στον στόλο.")

    category = (data.get("category") or "").strip().lower() or None
    if category and category not in aade_core.VEHICLE_CATEGORIES:
        raise aade_core.ApiError("Μη έγκυρη κατηγορία οχήματος.")

    vehicle = FleetVehicle(
        workshop_id=g.workshop_id,
        plate=plate,
        label=(data.get("label") or "").strip() or None,
        category=category,
    )
    db.session.add(vehicle)
    db.session.commit()
    return jsonify(vehicle.to_dict()), 201


@fleet_bp.route("/api/fleet-vehicles/<int:vehicle_id>", methods=["PATCH"])
@require_auth
def update_fleet_vehicle(vehicle_id):
    vehicle = FleetVehicle.query.filter_by(
        id=vehicle_id, workshop_id=g.workshop_id
    ).first()
    if vehicle is None:
        raise aade_core.ApiError("Δεν βρέθηκε το όχημα.", 404)

    data = request.get_json(silent=True) or {}
    if "plate" in data:
        plate = aade_core._canonical_plate((data.get("plate") or "").strip())
        if not plate:
            raise aade_core.ApiError("Το πεδίο 'plate' (πινακίδα) είναι υποχρεωτικό.")
        dup = FleetVehicle.query.filter(
            FleetVehicle.workshop_id == g.workshop_id,
            FleetVehicle.plate == plate,
            FleetVehicle.id != vehicle_id,
        ).first()
        if dup is not None:
            raise aade_core.ApiError("Η πινακίδα υπάρχει ήδη στον στόλο.")
        vehicle.plate = plate
    if "label" in data:
        vehicle.label = (data.get("label") or "").strip() or None
    if "category" in data:
        category = (data.get("category") or "").strip().lower() or None
        if category and category not in aade_core.VEHICLE_CATEGORIES:
            raise aade_core.ApiError("Μη έγκυρη κατηγορία οχήματος.")
        vehicle.category = category

    db.session.commit()
    return jsonify(vehicle.to_dict())


@fleet_bp.route("/api/fleet-vehicles/<int:vehicle_id>", methods=["DELETE"])
@require_auth
def delete_fleet_vehicle(vehicle_id):
    vehicle = FleetVehicle.query.filter_by(
        id=vehicle_id, workshop_id=g.workshop_id
    ).first()
    if vehicle is None:
        raise aade_core.ApiError("Δεν βρέθηκε το όχημα.", 404)
    db.session.delete(vehicle)
    db.session.commit()
    return "", 204
