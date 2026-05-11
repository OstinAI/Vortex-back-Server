# -*- coding: utf-8 -*-
import time
from flask import Blueprint, jsonify, request

from utils.security import token_required
from db.connection import get_session
from db.models import CRMFieldDefinition
from flask import abort

crm_fields_bp = Blueprint("crm_fields", __name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _company_id() -> int:
    payload = getattr(request, "user", None) or {}
    return int(payload.get("company_id") or payload.get("companyId") or 0)

def _role() -> str:
    payload = getattr(request, "user", None) or {}
    return str(payload.get("role") or "")

def _require_can_configure_fields():
    role = _role()

    # Разрешённые роли:
    allowed = {"Integrator", "Admin"}

    if role not in allowed:
        abort(403)


@crm_fields_bp.route("/fields", methods=["GET"])
@token_required
def list_fields():
    """
    GET /api/crm/fields?department_id=123
    Возвращает поля компании (scope company) + поля отдела (scope department).
    """
    company_id = _company_id()
    dep_id = request.args.get("department_id", "").strip()
    dep_id_int = int(dep_id) if dep_id.isdigit() else 0

    s = get_session()
    try:
        q = s.query(CRMFieldDefinition).filter(CRMFieldDefinition.company_id == company_id)
        rows = q.filter(CRMFieldDefinition.is_enabled == True).all()

        items = []
        for f in rows:
            # scope фильтр: company всегда, department только если совпал
            if f.scope_type == "company" and int(f.scope_id) == 0:
                pass
            elif f.scope_type == "department" and int(f.scope_id) == dep_id_int:
                pass
            else:
                continue

            items.append({
                "id": int(f.id),
                "scope_type": f.scope_type,
                "scope_id": int(f.scope_id),
                "key": f.key,
                "title": f.title,
                "type": f.type,
                "required": bool(f.required),
                "order_index": int(f.order_index),
                "options_json": f.options_json or "",
            })

        items.sort(key=lambda x: (x["order_index"], x["id"]))
        return jsonify({"ok": True, "fields": items}), 200
    finally:
        s.close()


@crm_fields_bp.route("/fields", methods=["POST"])
@token_required
def upsert_field():
    """
    POST /api/crm/fields
    body:
    {
      "id": optional,
      "scope_type": "company"|"department",
      "scope_id": 0|<department_id>,
      "key": "address",
      "title": "Адрес",
      "type": "text"|"number"|"bool"|"date"|"select",
      "required": true/false,
      "order_index": 0,
      "options_json": "[]"
    }
    """
    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    fid = data.get("id")
    scope_type = (data.get("scope_type") or "department").strip().lower()
    scope_id = int(data.get("scope_id") or 0)

    key = (data.get("key") or "").strip()
    title = (data.get("title") or "").strip()
    ftype = (data.get("type") or "text").strip().lower()

    required = bool(data.get("required", False))
    order_index = int(data.get("order_index") or 0)
    options_json = data.get("options_json") or ""

    if scope_type not in ("company", "department"):
        return jsonify({"ok": False, "message": "BAD_SCOPE_TYPE"}), 400
    if scope_type == "company":
        scope_id = 0
    if scope_type == "department" and scope_id <= 0:
        return jsonify({"ok": False, "message": "DEPARTMENT_ID_REQUIRED"}), 400

    if not key or not title:
        return jsonify({"ok": False, "message": "KEY_TITLE_REQUIRED"}), 400

    if ftype not in ("text", "number", "bool", "date", "select"):
        return jsonify({"ok": False, "message": "BAD_FIELD_TYPE"}), 400

    s = get_session()
    try:
        if fid:
            row = s.query(CRMFieldDefinition).filter_by(id=int(fid), company_id=company_id).first()
            if not row:
                return jsonify({"ok": False, "message": "NOT_FOUND"}), 404
        else:
            row = CRMFieldDefinition(company_id=company_id, created_ts_ms=_now_ms())
            s.add(row)

        row.scope_type = scope_type
        row.scope_id = scope_id
        row.key = key
        row.title = title
        row.type = ftype
        row.required = required
        row.order_index = order_index
        row.options_json = options_json
        row.is_enabled = True

        s.commit()
        return jsonify({"ok": True, "field_id": int(row.id)}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPSERT_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@crm_fields_bp.route("/fields/<int:field_id>/disable", methods=["POST"])
@token_required
def disable_field(field_id: int):
    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    s = get_session()
    try:
        row = s.query(CRMFieldDefinition).filter_by(id=int(field_id), company_id=company_id).first()
        if not row:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        row.is_enabled = False
        s.commit()
        return jsonify({"ok": True}), 200
    finally:
        s.close()


@crm_fields_bp.route("/fields/sync", methods=["POST"])
@token_required
def sync_fields():
    # observer read-only
    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    _require_can_configure_fields()

    company_id = _company_id()
    data = request.get_json(silent=True) or {}
    fields = data.get("fields") or []

    # принимаем только company scope (как у тебя в клиенте)
    scope_type = "company"
    scope_id = 0

    s = get_session()
    try:
        # текущие поля компании (company scope)
        existing = (
            s.query(CRMFieldDefinition)
             .filter(CRMFieldDefinition.company_id == company_id)
             .filter(CRMFieldDefinition.scope_type == scope_type)
             .filter(CRMFieldDefinition.scope_id == scope_id)
             .all()
        )

        existing_by_id = {int(x.id): x for x in existing}
        existing_by_key = {(x.key or ""): x for x in existing if (x.key or "")}

        incoming_ids = set()
        incoming_keys = set()

        now = _now_ms()

        for i, f in enumerate(fields):
            fid = f.get("id")
            fid = int(fid) if str(fid).isdigit() else None

            key = (f.get("key") or "").strip()
            title = (f.get("title") or "").strip()
            ftype = (f.get("type") or "text").strip().lower()
            options_json = f.get("options_json") or "[]"
            required = bool(f.get("required", False))
            order_index = int(f.get("order_index") if f.get("order_index") is not None else i)

            if not key or not title:
                continue

            row = None
            if fid and fid in existing_by_id:
                row = existing_by_id[fid]
            elif key in existing_by_key:
                row = existing_by_key[key]
            else:
                row = CRMFieldDefinition(
                    company_id=company_id,
                    created_ts_ms=now
                )
                s.add(row)

            row.scope_type = scope_type
            row.scope_id = scope_id
            row.key = key
            row.title = title
            row.type = ftype
            row.required = required
            row.order_index = order_index
            row.options_json = options_json
            row.is_enabled = True
            row.updated_ts_ms = now

            if fid:
                incoming_ids.add(int(fid))
            incoming_keys.add(key)

        # УДАЛЕНИЕ: всё чего нет в incoming -> выключаем
        for row in existing:
            rid = int(row.id)
            rkey = (row.key or "")
            if (rid not in incoming_ids) and (rkey not in incoming_keys):
                row.is_enabled = False
                row.updated_ts_ms = now

        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "SYNC_FAILED", "error": str(e)}), 500
    finally:
        s.close()
