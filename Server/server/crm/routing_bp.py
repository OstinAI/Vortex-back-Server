# -*- coding: utf-8 -*-
import time
from flask import Blueprint, jsonify, request

from utils.security import token_required
from db.connection import get_session
from db.models import CRMChannelRoute, PipelineStage, Pipeline

routing_bp = Blueprint("crm_routing", __name__)

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

def _norm_channel(ch: str) -> str:
    ch = (ch or "").strip().lower()
    if ch in ("wa", "whatsapp"):
        return "whatsapp"
    if ch in ("insta", "instagram"):
        return "instagram"
    if ch in ("mail", "email"):
        return "email"
    if ch in ("manual",):
        return "manual"
    return ch or "other"


@routing_bp.route("/routing", methods=["GET"])
@token_required
def get_routes():
    company_id = _company_id()
    s = get_session()
    try:
        rows = (
            s.query(CRMChannelRoute)
            .filter(CRMChannelRoute.company_id == company_id)
            .order_by(CRMChannelRoute.channel.asc())
            .all()
        )

        items = []
        for r in rows:
            items.append({
                "id": int(r.id),
                "channel": r.channel,
                "pipeline_id": int(r.pipeline_id) if r.pipeline_id else None,
                "stage_id": int(r.stage_id) if r.stage_id else None,
            })

        return jsonify({"ok": True, "routes": items}), 200
    finally:
        s.close()


@routing_bp.route("/routing", methods=["POST"])
@token_required
def set_route():
    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    if not _require_admin():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    channel = _norm_channel(data.get("channel"))
    pipeline_id = data.get("pipeline_id")
    stage_id = data.get("stage_id")

    pid = int(pipeline_id) if pipeline_id else None
    sid = int(stage_id) if stage_id else None

    s = get_session()
    try:
        # валидация (если задали pipeline/stage)
        if pid is not None:
            p = s.query(Pipeline).filter_by(id=pid, company_id=company_id).first()
            if not p:
                return jsonify({"ok": False, "message": "PIPELINE_NOT_FOUND"}), 404

        if sid is not None:
            st = s.query(PipelineStage).filter_by(id=sid, company_id=company_id).first()
            if not st:
                return jsonify({"ok": False, "message": "STAGE_NOT_FOUND"}), 404
            if pid is not None and int(st.pipeline_id) != int(pid):
                return jsonify({"ok": False, "message": "STAGE_NOT_IN_PIPELINE"}), 400

        row = (
            s.query(CRMChannelRoute)
            .filter(CRMChannelRoute.company_id == company_id)
            .filter(CRMChannelRoute.channel == channel)
            .first()
        )
        now = _now_ms()

        if not row:
            row = CRMChannelRoute(
                company_id=company_id,
                channel=channel,
                created_ts_ms=now,
                updated_ts_ms=now
            )
            s.add(row)

        row.pipeline_id = pid
        row.stage_id = sid
        row.updated_ts_ms = now

        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "SAVE_FAILED", "error": str(e)}), 500
    finally:
        s.close()
