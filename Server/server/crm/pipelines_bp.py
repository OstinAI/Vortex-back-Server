# -*- coding: utf-8 -*-
import time
from flask import Blueprint, jsonify, request

from utils.security import token_required
from db.connection import get_session
from db.models import Pipeline, PipelineStage

pipelines_bp = Blueprint("crm_pipelines", __name__)

def _now_ms():
    return int(time.time() * 1000)

def _company_id() -> int:
    payload = getattr(request, "user", None) or {}
    return int(payload.get("company_id") or payload.get("companyId") or 0)

def _role() -> str:
    payload = getattr(request, "user", None) or {}
    return str(payload.get("role") or "")

def _require_admin():
    if _role() not in ("Integrator", "Admin"):
        return False
    return True


@pipelines_bp.route("/pipelines", methods=["GET"])
@token_required
def list_pipelines():
    company_id = _company_id()
    s = get_session()
    try:
        rows = (
            s.query(Pipeline)
            .filter(Pipeline.company_id == company_id)
            .order_by(Pipeline.order_index.asc(), Pipeline.id.asc())
            .all()
        )

        items = []
        for p in rows:
            items.append({
                "id": int(p.id),
                "name": p.name or "",
                "is_enabled": bool(p.is_enabled),
                "order_index": int(p.order_index or 0),
            })
        return jsonify({"ok": True, "pipelines": items}), 200
    finally:
        s.close()


@pipelines_bp.route("/pipelines", methods=["POST"])
@token_required
def create_pipeline():
    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    if not _require_admin():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    order_index = int(data.get("order_index") or 0)

    if not name:
        return jsonify({"ok": False, "message": "NAME_REQUIRED"}), 400

    s = get_session()
    try:
        exists = (
            s.query(Pipeline)
            .filter(Pipeline.company_id == company_id)
            .filter(Pipeline.name == name)
            .first()
        )
        if exists:
            return jsonify({"ok": False, "message": "ALREADY_EXISTS"}), 400

        now = _now_ms()
        p = Pipeline(
            company_id=company_id,
            name=name,
            order_index=order_index,
            is_enabled=True,
            created_ts_ms=now,
            updated_ts_ms=now
        )
        s.add(p)
        s.commit()

        return jsonify({"ok": True, "pipeline": {"id": int(p.id), "name": p.name}}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@pipelines_bp.route("/pipelines/<int:pipeline_id>", methods=["POST"])
@token_required
def update_pipeline(pipeline_id: int):
    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    if not _require_admin():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    s = get_session()
    try:
        p = (
            s.query(Pipeline)
            .filter(Pipeline.company_id == company_id)
            .filter(Pipeline.id == int(pipeline_id))
            .first()
        )
        if not p:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        if "name" in data:
            p.name = (data.get("name") or "").strip() or p.name
        if "is_enabled" in data:
            p.is_enabled = bool(data.get("is_enabled"))
        if "order_index" in data:
            p.order_index = int(data.get("order_index") or 0)

        p.updated_ts_ms = _now_ms()
        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPDATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@pipelines_bp.route("/pipelines/<int:pipeline_id>", methods=["DELETE"])
@token_required
def delete_pipeline(pipeline_id: int):
    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    if not _require_admin():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    company_id = _company_id()
    s = get_session()
    try:
        p = (
            s.query(Pipeline)
            .filter(Pipeline.company_id == company_id)
            .filter(Pipeline.id == int(pipeline_id))
            .first()
        )
        if not p:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        s.delete(p)
        s.commit()
        return jsonify({"ok": True, "message": "DELETED"}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "DELETE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


# -----------------------
# STAGES
# -----------------------

@pipelines_bp.route("/pipelines/<int:pipeline_id>/stages", methods=["GET"])
@token_required
def list_stages(pipeline_id: int):
    company_id = _company_id()
    s = get_session()
    try:
        rows = (
            s.query(PipelineStage)
            .filter(PipelineStage.company_id == company_id)
            .filter(PipelineStage.pipeline_id == int(pipeline_id))
            .order_by(PipelineStage.order_index.asc(), PipelineStage.id.asc())
            .all()
        )

        items = []
        for st in rows:
            items.append({
                "id": int(st.id),
                "pipeline_id": int(st.pipeline_id),
                "name": st.name or "",
                "is_won": bool(st.is_won),
                "is_lost": bool(st.is_lost),
                "is_enabled": bool(st.is_enabled),
                "order_index": int(st.order_index or 0),
                # 🟢 ВОТ ЭТО МЫ ДОБАВИЛИ: Если в базе пусто, отдаем наш любимый #00ffff
                "color": st.color if getattr(st, 'color', None) else "#00ffff"
            })
        return jsonify({"ok": True, "stages": items}), 200
    finally:
        s.close()


@pipelines_bp.route("/pipelines/<int:pipeline_id>/stages", methods=["POST"])
@token_required
def create_stage(pipeline_id: int):
    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    if not _require_admin():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    order_index = int(data.get("order_index") or 0)
    is_won = bool(data.get("is_won", False))
    is_lost = bool(data.get("is_lost", False))
    
    # 🟢 Забираем цвет из запроса или ставим дефолтный #00ffff
    color = (data.get("color") or "#00ffff").strip()

    if not name:
        return jsonify({"ok": False, "message": "NAME_REQUIRED"}), 400

    s = get_session()
    try:
        now = _now_ms()
        st = PipelineStage(
            company_id=company_id,
            pipeline_id=int(pipeline_id),
            name=name,
            order_index=order_index,
            is_won=is_won,
            is_lost=is_lost,
            is_enabled=True,
            color=color, # 🟢 Сохраняем цвет в БД
            created_ts_ms=now,
            updated_ts_ms=now
        )
        s.add(st)
        s.commit()

        # Также возвращаем цвет обратно фронтенду
        return jsonify({
            "ok": True, 
            "stage": {
                "id": int(st.id), 
                "name": st.name,
                "color": st.color
            }
        }), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


# 1. Исправленная функция обновления этапа (теперь принимает POST, PUT и OPTIONS)
@pipelines_bp.route("/stages/<int:stage_id>", methods=["POST", "PUT", "OPTIONS"])
@token_required
def update_stage(stage_id: int):
    # ⭐ Автоматически одобряем CORS-проверку от браузера
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200

    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    if not _require_admin():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    s = get_session()
    try:
        st = (
            s.query(PipelineStage)
            .filter(PipelineStage.company_id == company_id)
            .filter(PipelineStage.id == int(stage_id))
            .first()
        )
        if not st:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        if "name" in data:
            st.name = (data.get("name") or "").strip() or st.name
        if "order_index" in data:
            st.order_index = int(data.get("order_index") or 0)
        if "is_enabled" in data:
            st.is_enabled = bool(data.get("is_enabled"))
        if "is_won" in data:
            st.is_won = bool(data.get("is_won"))
        if "is_lost" in data:
            st.is_lost = bool(data.get("is_lost"))
            
        # 🟢 ДОБАВЛЕНО: сохраняем цвет этапа в модель базы данных
        if "color" in data:
            st.color = (data.get("color") or "").strip() or None

        st.updated_ts_ms = _now_ms()
        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPDATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


# 2. НОВЫЙ ЭНДПОИНТ: Сортировка этапов (Решает ошибку 404 /reorder-stages)
@pipelines_bp.route("/pipelines/<int:pipeline_id>/reorder-stages", methods=["POST"])
@token_required
def reorder_stages(pipeline_id: int):
    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    if not _require_admin():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}
    order_list = data.get("order") or []  # Это наш массив [{id: "...", position: 0}, ...]

    s = get_session()
    try:
        # 1. Получаем все этапы этой воронки из базы, чтобы убедиться, что они принадлежат компании
        stages = (
            s.query(PipelineStage)
            .filter(PipelineStage.company_id == company_id)
            .filter(PipelineStage.pipeline_id == int(pipeline_id))
            .all()
        )
        
        # Делаем словарь для быстрого поиска stage по его ID
        stages_map = {int(st.id): st for st in stages}

        # 2. Проходим по пришедшему с фронтенда порядку и обновляем индексы
        for item in order_list:
            stage_id = item.get("id")
            position = item.get("position")

            if stage_id is None or position is None:
                continue

            # Находим этап в нашей карте (приводим ID к int на случай если фронт прислал строку)
            st = stages_map.get(int(stage_id))
            if st:
                # ВАЖНО: Проверьте, как называется колонка в вашей модели (order_index или position)
                # Судя по list_pipelines, у вас в модели Pipeline используется order_index. 
                # Скорее всего у PipelineStage поле называется так же: order_index
                st.order_index = int(position) 
                st.updated_ts_ms = _now_ms()

        # 3. КРИТИЧЕСКИЙ МОМЕНТ: Сохраняем изменения в базу данных!
        s.commit()
        
        return jsonify({"ok": True, "message": "STAGES_REORDERED"}), 200

    except Exception as e:
        s.rollback()  # Откатываем транзакцию в случае сбоя
        return jsonify({"ok": False, "message": "REORDER_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@pipelines_bp.route("/stages/<int:stage_id>", methods=["DELETE"])
@token_required
def delete_stage(stage_id: int):
    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    if not _require_admin():
        return jsonify({"ok": False, "message": "ACCESS_DENIED"}), 403

    company_id = _company_id()
    s = get_session()
    try:
        st = (
            s.query(PipelineStage)
            .filter(PipelineStage.company_id == company_id)
            .filter(PipelineStage.id == int(stage_id))
            .first()
        )
        if not st:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        s.delete(st)
        s.commit()
        return jsonify({"ok": True, "message": "DELETED"}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "DELETE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


