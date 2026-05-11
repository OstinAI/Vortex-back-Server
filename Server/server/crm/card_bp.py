# -*- coding: utf-8 -*-
import time
from flask import Blueprint, jsonify, request

from utils.security import token_required
from db.connection import get_session
from db.models import Client, CRMFieldDefinition, CRMFieldValue, User

crm_card_bp = Blueprint("crm_card", __name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _company_id() -> int:
    payload = getattr(request, "user", None) or {}
    return int(payload.get("company_id") or payload.get("companyId") or 0)


def _user_id() -> int:
    payload = getattr(request, "user", None) or {}
    return int(payload.get("user_id") or 0)


@crm_card_bp.route("/clients/<int:client_id>/card", methods=["GET"])
@token_required
def get_client_card(client_id: int):
    """
    Возвращает:
    - client
    - fields (definitions) для отдела пользователя + company
    - values (по field_id)
    """
    company_id = _company_id()
    user_id = _user_id()

    s = get_session()
    try:
        client = s.query(Client).filter_by(id=int(client_id), company_id=company_id).first()
        if not client:
            return jsonify({"ok": False, "message": "CLIENT_NOT_FOUND"}), 404

        user = s.query(User).filter_by(id=int(user_id), company_id=company_id).first()
        dep_id = int(getattr(user, "department_id", 0) or 0) if user else 0

        # definitions: company + department(dep_id)
        defs = s.query(CRMFieldDefinition).filter(CRMFieldDefinition.company_id == company_id).filter(CRMFieldDefinition.is_enabled == True).all()

        fields = []
        field_ids = []
        for f in defs:
            if f.scope_type == "company" and int(f.scope_id) == 0:
                pass
            elif f.scope_type == "department" and int(f.scope_id) == dep_id:
                pass
            else:
                continue

            fields.append({
                "id": int(f.id),
                "key": f.key,
                "title": f.title,
                "type": f.type,
                "required": bool(f.required),
                "order_index": int(f.order_index),
                "options_json": f.options_json or "",
            })
            field_ids.append(int(f.id))

        fields.sort(key=lambda x: (x["order_index"], x["id"]))

        # values
        vals = []
        if field_ids:
            rows = (
                s.query(CRMFieldValue)
                .filter(CRMFieldValue.company_id == company_id)
                .filter(CRMFieldValue.client_id == int(client.id))
                .filter(CRMFieldValue.field_id.in_(field_ids))
                .all()
            )
            for v in rows:
                vals.append({
                    "field_id": int(v.field_id),
                    "value_text": v.value_text or "",
                    "value_number": v.value_number,
                    "value_bool": v.value_bool,
                    "value_ts_ms": v.value_ts_ms,
                })

        return jsonify({
            "ok": True,
            "client": {
                "id": int(client.id),
                "name": client.name or "",
                "status": client.status or "active",
                "region_id": int(client.region_id) if client.region_id else None,
                "pipeline_id": int(client.pipeline_id) if getattr(client, "pipeline_id", None) else 0,
                "stage_id": int(client.stage_id) if getattr(client, "stage_id", None) else 0,
            },

            "fields": fields,
            "values": vals,
        }), 200

    finally:
        s.close()


@crm_card_bp.route("/clients/<int:client_id>/values", methods=["POST"])
@token_required
def save_client_values(client_id: int):
    """
    body:
    {
      "values": [
        {"field_id": 10, "value": "Алматы, ..."},
        {"field_id": 11, "value": 120000},
        {"field_id": 12, "value": true},
        {"field_id": 13, "value": 1735689600000}
      ]
    }
    """

    payload = getattr(request, "user", None) or {}
    if str(payload.get("role") or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}
    values = data.get("values") or []

    s = get_session()
    try:
        client = s.query(Client).filter_by(id=int(client_id), company_id=company_id).first()
        if not client:
            return jsonify({"ok": False, "message": "CLIENT_NOT_FOUND"}), 404

        # подтягиваем определения чтобы знать тип
        defs = s.query(CRMFieldDefinition).filter_by(company_id=company_id, is_enabled=True).all()
        defs_map = {int(f.id): f for f in defs}

        now = _now_ms()

        for item in values:
            fid = int(item.get("field_id") or 0)
            if fid <= 0:
                continue
            fdef = defs_map.get(fid)
            if not fdef:
                continue

            v = item.get("value")

            row = s.query(CRMFieldValue).filter_by(company_id=company_id, client_id=int(client.id), field_id=fid).first()
            if not row:
                row = CRMFieldValue(company_id=company_id, client_id=int(client.id), field_id=fid)
                s.add(row)

            # очистка
            row.value_text = ""
            row.value_number = None
            row.value_bool = None
            row.value_ts_ms = None

            t = (fdef.type or "text").lower()

            if t in ("text", "select"):
                row.value_text = "" if v is None else str(v)
            elif t == "number":
                try:
                    row.value_number = float(v)
                except Exception:
                    row.value_number = None
            elif t == "bool":
                row.value_bool = bool(v)
            elif t == "date":
                # ожидаем timestamp ms
                try:
                    row.value_ts_ms = int(v)
                except Exception:
                    row.value_ts_ms = None
            else:
                row.value_text = "" if v is None else str(v)

            row.updated_ts_ms = now

        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "SAVE_FAILED", "error": str(e)}), 500
    finally:
        s.close()
