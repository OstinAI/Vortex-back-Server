# -*- coding: utf-8 -*-
from flask import Blueprint, jsonify, request

from utils.security import token_required
from db.connection import get_session
from db.models import CompanyCRMSettings

crm_settings_bp = Blueprint("crm_settings", __name__)


def _company_id() -> int:
    payload = getattr(request, "user", None) or {}
    return int(payload.get("company_id") or payload.get("companyId") or 0)


@crm_settings_bp.route("/settings", methods=["GET"])
@token_required
def get_settings():
    company_id = _company_id()
    s = get_session()
    try:
        row = s.query(CompanyCRMSettings).filter_by(company_id=company_id).first()
        if not row:
            # дефолт создаём сразу
            row = CompanyCRMSettings(company_id=company_id)
            s.add(row)
            s.commit()

        return jsonify({
            "ok": True,
            "settings": {
                "auto_create_from_whatsapp": bool(row.auto_create_from_whatsapp),
                "auto_create_from_instagram": bool(row.auto_create_from_instagram),
                "auto_create_from_email": bool(row.auto_create_from_email),
            }
        }), 200
    finally:
        s.close()


@crm_settings_bp.route("/settings", methods=["POST"])
@token_required
def update_settings():
    payload = getattr(request, "user", None) or {}
    if str(payload.get("role") or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    s = get_session()
    try:
        row = s.query(CompanyCRMSettings).filter_by(company_id=company_id).first()
        if not row:
            row = CompanyCRMSettings(company_id=company_id)
            s.add(row)
            s.flush()

        if "auto_create_from_whatsapp" in data:
            row.auto_create_from_whatsapp = bool(data.get("auto_create_from_whatsapp"))
        if "auto_create_from_instagram" in data:
            row.auto_create_from_instagram = bool(data.get("auto_create_from_instagram"))
        if "auto_create_from_email" in data:
            row.auto_create_from_email = bool(data.get("auto_create_from_email"))

        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPDATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()
