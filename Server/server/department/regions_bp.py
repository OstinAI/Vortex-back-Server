# -*- coding: utf-8 -*-
from flask import Blueprint, jsonify, request

from utils.security import token_required
from db.connection import get_session
from db.models import Region

regions_bp = Blueprint("regions", __name__)

def _payload():
    return getattr(request, "user", None) or {}

def _company_id() -> int:
    p = _payload()
    return int(p.get("company_id") or p.get("companyId") or 0)

@regions_bp.route("/", methods=["GET"])
@token_required
def list_regions():
    company_id = _company_id()

    s = get_session()
    try:
        rows = (
            s.query(Region)
            .filter(Region.company_id == company_id)
            .order_by(Region.name.asc())
            .all()
        )

        items = []
        for r in rows:
            items.append({
                "id": int(getattr(r, "id", 0) or 0),
                "name": getattr(r, "name", "") or "",
            })

        return jsonify({"ok": True, "regions": items}), 200
    finally:
        s.close()

@regions_bp.route("/", methods=["POST"])
@token_required
def create_region():
    company_id = _company_id()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"ok": False, "error": "name_required"}), 400

    s = get_session()
    try:
        exists = (
            s.query(Region)
            .filter(Region.company_id == company_id)
            .filter(Region.name == name)
            .first()
        )
        if exists:
            return jsonify({"ok": True, "region": {"id": int(exists.id), "name": exists.name}}), 200

        r = Region(company_id=company_id, name=name)
        s.add(r)
        s.commit()

        return jsonify({"ok": True, "region": {"id": int(r.id), "name": r.name}}), 200
    finally:
        s.close()

@regions_bp.route("/<int:region_id>", methods=["DELETE"])
@token_required
def delete_region(region_id: int):
    company_id = _company_id()

    s = get_session()
    try:
        r = (
            s.query(Region)
            .filter(Region.company_id == company_id, Region.id == int(region_id))
            .first()
        )
        if not r:
            return jsonify({"ok": False, "error": "not_found"}), 404

        s.delete(r)
        s.commit()
        return jsonify({"ok": True}), 200
    finally:
        s.close()
