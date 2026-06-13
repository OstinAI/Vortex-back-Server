# -*- coding: utf-8 -*-
from flask import Blueprint, jsonify, request

from utils.security import token_required
from db.connection import get_session
from db.models import CompanyCRMSettings, CRMChannelRoute, Pipeline, PipelineStage
import time

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


# ============================================
# ⭐ НОВЫЙ КОД: УПРАВЛЕНИЕ МАРШРУТАМИ КАНАЛОВ
# ============================================

@crm_settings_bp.route("/channel-routes", methods=["GET"])
@token_required
def get_channel_routes():
    """Получить все маршруты для каналов (Telegram, WhatsApp и т.д.)"""
    company_id = _company_id()
    
    s = get_session()
    try:
        routes = s.query(CRMChannelRoute).filter_by(company_id=company_id).all()
        
        result = []
        for route in routes:
            result.append({
                "id": route.id,
                "channel": route.channel,
                "pipeline_id": route.pipeline_id,
                "stage_id": route.stage_id,
                "pipeline_name": route.pipeline.name if route.pipeline else None,
                "stage_name": route.stage.name if route.stage else None,
            })
        
        return jsonify({"ok": True, "routes": result}), 200
    finally:
        s.close()


@crm_settings_bp.route("/channel-routes", methods=["POST"])
@token_required
def create_or_update_channel_route():
    """
    Создать или обновить маршрут для канала
    
    Тело запроса:
    {
        "channel": "telegram",      // или whatsapp, instagram, email, manual, other
        "pipeline_id": 1,           // ID воронки (опционально)
        "stage_id": 5               // ID этапа (опционально)
    }
    """
    payload = getattr(request, "user", None) or {}
    
    # Только Admin и Integrator могут менять настройки
    if str(payload.get("role") or "").strip().lower() not in ("integrator", "admin"):
        return jsonify({"ok": False, "message": "Access denied"}), 403
    
    company_id = _company_id()
    data = request.get_json(silent=True) or {}
    
    channel = data.get("channel", "").strip().lower()
    pipeline_id = data.get("pipeline_id")
    stage_id = data.get("stage_id")
    
    if not channel:
        return jsonify({"ok": False, "message": "channel is required"}), 400
    
    # Поддерживаемые каналы
    allowed_channels = ["whatsapp", "telegram", "instagram", "email", "manual", "other"]
    if channel not in allowed_channels:
        return jsonify({
            "ok": False, 
            "message": f"channel must be one of: {allowed_channels}"
        }), 400
    
    s = get_session()
    try:
        # Проверяем, существует ли pipeline (если указан)
        if pipeline_id:
            pipeline = s.query(Pipeline).filter_by(
                id=pipeline_id, company_id=company_id
            ).first()
            if not pipeline:
                return jsonify({"ok": False, "message": "Pipeline not found"}), 404
        
        # Проверяем, существует ли stage (если указан)
        if stage_id:
            stage = s.query(PipelineStage).filter_by(
                id=stage_id, company_id=company_id
            ).first()
            if not stage:
                return jsonify({"ok": False, "message": "Stage not found"}), 404
        
        # Ищем существующий маршрут
        route = s.query(CRMChannelRoute).filter_by(
            company_id=company_id, channel=channel
        ).first()
        
        now_ms = int(time.time() * 1000)
        
        if route:
            # Обновляем существующий
            route.pipeline_id = pipeline_id
            route.stage_id = stage_id
            route.updated_ts_ms = now_ms
            message = "Route updated"
        else:
            # Создаём новый
            route = CRMChannelRoute(
                company_id=company_id,
                channel=channel,
                pipeline_id=pipeline_id,
                stage_id=stage_id,
                created_ts_ms=now_ms,
                updated_ts_ms=now_ms
            )
            s.add(route)
            message = "Route created"
        
        s.commit()
        
        return jsonify({
            "ok": True,
            "message": message,
            "route": {
                "id": route.id,
                "channel": route.channel,
                "pipeline_id": route.pipeline_id,
                "stage_id": route.stage_id
            }
        }), 200
        
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": str(e)}), 500
    finally:
        s.close()


@crm_settings_bp.route("/channel-routes/<int:route_id>", methods=["DELETE"])
@token_required
def delete_channel_route(route_id):
    """Удалить маршрут для канала"""
    payload = getattr(request, "user", None) or {}
    
    if str(payload.get("role") or "").strip().lower() not in ("integrator", "admin"):
        return jsonify({"ok": False, "message": "Access denied"}), 403
    
    company_id = _company_id()
    
    s = get_session()
    try:
        route = s.query(CRMChannelRoute).filter_by(
            id=route_id, company_id=company_id
        ).first()
        
        if not route:
            return jsonify({"ok": False, "message": "Route not found"}), 404
        
        s.delete(route)
        s.commit()
        
        return jsonify({"ok": True, "message": "Route deleted"}), 200
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": str(e)}), 500
    finally:
        s.close()


@crm_settings_bp.route("/channel-routes/defaults", methods=["POST"])
@token_required
def setup_default_routes():
    """
    Создать маршруты по умолчанию для всех каналов
    """
    payload = getattr(request, "user", None) or {}
    
    if str(payload.get("role") or "").strip().lower() not in ("integrator", "admin"):
        return jsonify({"ok": False, "message": "Access denied"}), 403
    
    company_id = _company_id()
    
    s = get_session()
    try:
        # Находим первую активную воронку
        first_pipeline = s.query(Pipeline).filter_by(
            company_id=company_id, is_enabled=True
        ).first()
        
        pipeline_id = first_pipeline.id if first_pipeline else None
        stage_id = None
        
        if first_pipeline:
            # Находим первый этап в воронке
            first_stage = s.query(PipelineStage).filter_by(
                pipeline_id=first_pipeline.id, is_enabled=True
            ).order_by(PipelineStage.order_index).first()
            stage_id = first_stage.id if first_stage else None
        
        now_ms = int(time.time() * 1000)
        channels = ["whatsapp", "telegram", "instagram", "email", "manual"]
        
        created_count = 0
        for channel in channels:
            existing = s.query(CRMChannelRoute).filter_by(
                company_id=company_id, channel=channel
            ).first()
            
            if not existing:
                route = CRMChannelRoute(
                    company_id=company_id,
                    channel=channel,
                    pipeline_id=pipeline_id,
                    stage_id=stage_id,
                    created_ts_ms=now_ms,
                    updated_ts_ms=now_ms
                )
                s.add(route)
                created_count += 1
        
        s.commit()
        
        return jsonify({
            "ok": True,
            "message": f"Created {created_count} default routes",
            "pipeline_id": pipeline_id,
            "stage_id": stage_id
        }), 200
        
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": str(e)}), 500
    finally:
        s.close()

@crm_settings_bp.route("/channel-routes", methods=["DELETE"])
@token_required
def delete_channel_route_by_channel():
    """Удалить маршрут для канала по имени канала"""
    payload = getattr(request, "user", None) or {}
    
    if str(payload.get("role") or "").strip().lower() not in ("integrator", "admin"):
        return jsonify({"ok": False, "message": "Access denied"}), 403
    
    company_id = _company_id()
    channel = request.args.get("channel", "").strip().lower()
    
    if not channel:
        return jsonify({"ok": False, "message": "channel required"}), 400
    
    s = get_session()
    try:
        route = s.query(CRMChannelRoute).filter_by(
            company_id=company_id, channel=channel
        ).first()
        
        if route:
            s.delete(route)
            s.commit()
        
        return jsonify({"ok": True, "message": f"Route for {channel} deleted"}), 200
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": str(e)}), 500
    finally:
        s.close()