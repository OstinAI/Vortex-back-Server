# -*- coding: utf-8 -*-
import json
import time
from flask import Blueprint, jsonify, request

from utils.security import token_required
from db.connection import get_session
from db.models import AutomationRule

automator_bp = Blueprint("crm_automator", __name__)


def _now_ms():
    return int(time.time() * 1000)

def _company_id() -> int:
    payload = getattr(request, "user", None) or {}
    return int(payload.get("company_id") or payload.get("companyId") or 0)

def _role() -> str:
    payload = getattr(request, "user", None) or {}
    return str(payload.get("role") or "")

def _require_admin():
    return _role() in ("Integrator", "Admin")


@automator_bp.route("/automation/rules", methods=["GET"])
@token_required
def list_rules():
    company_id = _company_id()
    s = get_session()
    try:
        rows = (
            s.query(AutomationRule)
            .filter(AutomationRule.company_id == company_id)
            .order_by(AutomationRule.event_name.asc(), AutomationRule.priority.asc(), AutomationRule.id.asc())
            .all()
        )
        out = []
        for r in rows:
            out.append({
                "id": int(r.id),
                "event_name": r.event_name,
                "title": r.title or "",
                "enabled": bool(r.enabled),
                "priority": int(r.priority or 0),
                "conditions_json": r.conditions_json or "{}",
                "actions_json": r.actions_json or "[]",
                "stop_on_match": bool(getattr(r, "stop_on_match", True)),
            })
        return jsonify({"ok": True, "rules": out}), 200
    finally:
        s.close()


@automator_bp.route("/automation/rules", methods=["POST"])
@token_required
def upsert_rule():
    payload = getattr(request, "user", None) or {}
    if str(payload.get("role") or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403
    if not _require_admin():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    rid = data.get("id")
    event_name = (data.get("event_name") or "").strip()
    title = (data.get("title") or "").strip()
    enabled = bool(data.get("enabled", True))
    priority = int(data.get("priority") or 100)
    stop_on_match = bool(data.get("stop_on_match", True))

    conditions_json = data.get("conditions_json") or "{}"
    actions_json = data.get("actions_json") or "[]"

    # проверка что это валидный JSON
    try:
        json.loads(conditions_json)
    except:
        return jsonify({"ok": False, "message": "BAD_CONDITIONS_JSON"}), 400

    try:
        json.loads(actions_json)
    except:
        return jsonify({"ok": False, "message": "BAD_ACTIONS_JSON"}), 400

    if not event_name:
        return jsonify({"ok": False, "message": "EVENT_REQUIRED"}), 400

    s = get_session()
    try:
        if rid:
            row = s.query(AutomationRule).filter_by(company_id=company_id, id=int(rid)).first()
            if not row:
                return jsonify({"ok": False, "message": "NOT_FOUND"}), 404
        else:
            row = AutomationRule(company_id=company_id, created_ts_ms=_now_ms())
            s.add(row)

        row.event_name = event_name
        row.title = title
        row.enabled = enabled
        row.priority = priority
        row.conditions_json = conditions_json
        row.actions_json = actions_json
        row.stop_on_match = stop_on_match
        row.updated_ts_ms = _now_ms()

        s.commit()
        return jsonify({"ok": True, "id": int(row.id)}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "SAVE_FAILED", "error": str(e)}), 500
    finally:
        s.close()
        
@automator_bp.route("/automation/rules/<int:rid>", methods=["DELETE"])
@token_required
def delete_rule(rid: int):
    payload = getattr(request, "user", None) or {}
    if str(payload.get("role") or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403
    if not _require_admin():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    company_id = _company_id()
    s = get_session()
    try:
        row = s.query(AutomationRule).filter_by(company_id=company_id, id=int(rid)).first()
        if not row:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        s.delete(row)
        s.commit()
        return jsonify({"ok": True}), 200
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "DELETE_FAILED", "error": str(e)}), 500
    finally:
        s.close()