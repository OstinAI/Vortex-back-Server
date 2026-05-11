# -*- coding: utf-8 -*-
import time
from flask import Blueprint, jsonify, request

from utils.security import token_required
from db.connection import get_session
from db.models import Client, ClientIdentity, ClientAssignment, CompanyCRMSettings, CRMChannelRoute, User, Note
from db.models import PipelineStage
from server.crm.Automator.engine import run_event
from server.extensions import socketio # ИМПОРТИРУЙ ТОЛЬКО ОТСЮДА

crm_clients_bp = Blueprint("crm_clients", __name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _company_id() -> int:
    payload = getattr(request, "user", None) or {}
    return int(payload.get("company_id") or payload.get("companyId") or 0)

def _pick_route(s, company_id: int, channel: str):
    channel = (channel or "").strip().lower() or "manual"
    row = (
        s.query(CRMChannelRoute)
        .filter(CRMChannelRoute.company_id == company_id)
        .filter(CRMChannelRoute.channel == channel)
        .first()
    )
    if not row:
        # РµСЃР»Рё РЅРµС‚ вЂ” РїСЂРѕР±СѓРµРј manual
        row = (
            s.query(CRMChannelRoute)
            .filter(CRMChannelRoute.company_id == company_id)
            .filter(CRMChannelRoute.channel == "manual")
            .first()
        )
    if not row:
        return (None, None)

    pid = int(row.pipeline_id) if row.pipeline_id else None
    sid = int(row.stage_id) if row.stage_id else None
    return (pid, sid)


def _norm(kind: str, value: str) -> str:
    kind = (kind or "").strip().lower()
    v = (value or "").strip()
    if kind in ("email",):
        return v.lower()
    if kind in ("phone", "whatsapp"):
        # С‚РѕР»СЊРєРѕ С†РёС„СЂС‹ + РІРµРґСѓС‰РёР№ +
        digits = "".join(ch for ch in v if ch.isdigit())
        return digits
    if kind in ("instagram", "telegram"):
        return v.lstrip("@").lower()
    return v


@crm_clients_bp.route("/clients", methods=["GET"])
@token_required
def list_clients():
    company_id = _company_id()
    s = get_session()
    try:
        rows = (
            s.query(Client)
            .filter(Client.company_id == company_id)
            .filter(Client.is_archived == False)
            .order_by(Client.id.desc())
            .limit(200)
            .all()
        )

        items = []
        for c in rows:
            items.append({
                "id": int(c.id),
                "name": c.name or "",
                "status": c.status or "active",
                "region_id": int(c.region_id) if c.region_id else None,
                "merged_into_id": int(c.merged_into_id) if c.merged_into_id else None,
            })
        return jsonify({"ok": True, "clients": items}), 200
    finally:
        s.close()


@crm_clients_bp.route("/clients", methods=["POST"])
@token_required
def create_client():
    payload = getattr(request, "user", None) or {}
    if str(payload.get("role") or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    region_id = data.get("region_id")
    channel = (data.get("channel") or "manual").strip().lower()
    pipeline_id = data.get("pipeline_id")
    stage_id = data.get("stage_id")

    if not name:
        name = "Р‘РµР· РёРјРµРЅРё"

    s = get_session()
    try:
        pid = int(pipeline_id) if pipeline_id else None
        sid = int(stage_id) if stage_id else None

        if pid is None and sid is None:
            pid2, sid2 = _pick_route(s, company_id, channel)
            pid = pid2
            sid = sid2

        c = Client(
            company_id=company_id,
            region_id=int(region_id) if region_id else None,
            pipeline_id=pid,
            stage_id=sid,
            name=name,
            status="active",
            created_ts_ms=_now_ms(),
        )

        s.add(c)
        s.commit()

        creator_user_id = int(payload.get("user_id") or 0)
        if creator_user_id > 0:
            exists_assign = (
                s.query(ClientAssignment)
                .filter(ClientAssignment.company_id == company_id)
                .filter(ClientAssignment.client_id == c.id)
                .filter(ClientAssignment.user_id == creator_user_id)
                .first()
            )
            if not exists_assign:
                s.add(ClientAssignment(
                    company_id=company_id,
                    client_id=c.id,
                    user_id=creator_user_id,
                    role="responsible",
                    created_ts_ms=_now_ms(),
                ))
                s.commit()

        ctx = {
            "client_id": int(c.id),
            "pipeline_id": int(c.pipeline_id or 0),
            "stage_id": int(c.stage_id or 0),
            "region_id": int(c.region_id or 0) if c.region_id else 0,
            "channel": channel,
        }
        run_event(s, company_id, "client.created", ctx, actor_user_id=creator_user_id)
        s.commit()

        return jsonify({"ok": True, "client": {"id": int(c.id), "name": c.name}}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()



@crm_clients_bp.route("/clients/<int:client_id>", methods=["GET"])
@token_required
def get_client(client_id: int):
    company_id = _company_id()
    s = get_session()
    try:
        c = s.query(Client).filter_by(id=int(client_id), company_id=company_id).first()
        if not c:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        ids = (
            s.query(ClientIdentity)
            .filter_by(company_id=company_id, client_id=c.id)
            .order_by(ClientIdentity.id.asc())
            .all()
        )
        identities = [{
            "id": int(x.id),
            "kind": x.kind,
            "value": x.value,
            "is_primary": bool(x.is_primary),
        } for x in ids]

        assigns = (
            s.query(ClientAssignment)
            .filter_by(company_id=company_id, client_id=c.id)
            .order_by(ClientAssignment.id.asc())
            .all()
        )
        ass = [{
            "id": int(a.id),
            "user_id": int(a.user_id),
            "role": a.role,
        } for a in assigns]

        return jsonify({
            "ok": True,
            "client": {
                "id": int(c.id),
                "name": c.name or "",
                "status": c.status or "active",
                "region_id": int(c.region_id) if c.region_id else None,
                "notes": c.notes or "",
                "merged_into_id": int(c.merged_into_id) if c.merged_into_id else None,
                "is_archived": bool(c.is_archived),
            },
            "identities": identities,
            "assignments": ass,
        }), 200
    finally:
        s.close()


@crm_clients_bp.route("/clients/<int:client_id>", methods=["POST"])
@token_required
def update_client(client_id: int):
    payload = getattr(request, "user", None) or {}
    if str(payload.get("role") or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    s = get_session()
    try:
        c = s.query(Client).filter_by(id=int(client_id), company_id=company_id).first()
        if not c:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        if "name" in data:
            c.name = (data.get("name") or "").strip() or c.name
        if "status" in data:
            c.status = (data.get("status") or "").strip() or c.status
        if "region_id" in data:
            rid = data.get("region_id")
            c.region_id = int(rid) if rid else None
        if "notes" in data:
            c.notes = data.get("notes") or ""

        s.commit()
        return jsonify({"ok": True}), 200
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPDATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()

@crm_clients_bp.route("/clients/<int:client_id>/move", methods=["POST"])
@token_required
def move_client(client_id: int):
    payload = getattr(request, "user", None) or {}
    if str(payload.get("role") or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    pid = int(data.get("pipeline_id") or 0)
    sid = int(data.get("stage_id") or 0)
    if pid <= 0 or sid <= 0:
        return jsonify({"ok": False, "message": "PIPELINE_STAGE_REQUIRED"}), 400

    s = get_session()
    try:
        c = s.query(Client).filter_by(id=int(client_id), company_id=company_id).first()
        if not c:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        st = (
            s.query(PipelineStage)
            .filter(PipelineStage.company_id == company_id)
            .filter(PipelineStage.pipeline_id == pid)
            .filter(PipelineStage.id == sid)
            .first()
        )
        if not st:
            return jsonify({"ok": False, "message": "STAGE_NOT_FOUND"}), 404

        prev_pid = int(c.pipeline_id or 0)
        prev_sid = int(c.stage_id or 0)

        c.pipeline_id = pid
        c.stage_id = sid
        s.commit() # Сохраняем перемещение

        # Запускаем автоматизацию (Automator)
        ctx = {
            "client_id": int(c.id),
            "pipeline_id": int(c.pipeline_id or 0),
            "stage_id": int(c.stage_id or 0),
            "prev_pipeline_id": prev_pid,
            "prev_stage_id": prev_sid,
            "region_id": int(c.region_id or 0) if c.region_id else 0,
        }
        run_event(s, company_id, "client.moved", ctx, actor_user_id=int(payload.get("user_id") or 0))
        s.commit() # Сохраняем результаты работы автоматизации

        # ОТПРАВЛЯЕМ СОКЕТ (в самом конце, когда всё точно готово)
        try:
            if socketio:
                socketio.emit('deal_moved', {
                    'dealId': int(c.id),
                    'newStageId': int(c.stage_id),
                    'pipelineId': int(c.pipeline_id)
                })
                print(f"[VORTEX] Сигнал отправлен: Сделка {c.id} -> Этап {c.stage_id}")
        except Exception as socket_err:
            print(f"[VORTEX-ERROR] Ошибка сокета: {socket_err}")

        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "MOVE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@crm_clients_bp.route("/clients/<int:client_id>/identities", methods=["POST"])
@token_required
def add_identity(client_id: int):
    payload = getattr(request, "user", None) or {}
    if str(payload.get("role") or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    kind = (data.get("kind") or "").strip().lower()
    value = _norm(kind, data.get("value") or "")
    is_primary = bool(data.get("is_primary", False))

    if not kind or not value:
        return jsonify({"ok": False, "message": "KIND_VALUE_REQUIRED"}), 400

    s = get_session()
    try:
        c = s.query(Client).filter_by(id=int(client_id), company_id=company_id).first()
        if not c:
            return jsonify({"ok": False, "message": "CLIENT_NOT_FOUND"}), 404

        # РµСЃР»Рё identity СѓР¶Рµ СЃСѓС‰РµСЃС‚РІСѓРµС‚ (Рё РїСЂРёРІСЏР·Р°РЅР° Рє РґСЂСѓРіРѕРјСѓ РєР»РёРµРЅС‚Сѓ) вЂ” СЌС‚Рѕ РєР°Рє СЂР°Р· РєРµР№СЃ РґР»СЏ merge
        exists = (
            s.query(ClientIdentity)
            .filter_by(company_id=company_id, kind=kind, value=value)
            .first()
        )
        if exists and int(exists.client_id) != int(c.id):
            return jsonify({
                "ok": False,
                "message": "IDENTITY_ALREADY_LINKED",
                "linked_client_id": int(exists.client_id),
            }), 409

        x = ClientIdentity(
            company_id=company_id,
            client_id=c.id,
            kind=kind,
            value=value,
            is_primary=is_primary,
            created_ts_ms=_now_ms(),
        )
        s.add(x)
        s.commit()
        return jsonify({"ok": True, "identity": {"id": int(x.id), "kind": x.kind, "value": x.value}}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "ADD_IDENTITY_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@crm_clients_bp.route("/clients/merge", methods=["POST"])
@token_required
def merge_clients():
    """
    body: { "from_client_id": 12, "to_client_id": 5 }
    from -> to
    """
    payload = getattr(request, "user", None) or {}
    if str(payload.get("role") or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    from_id = int(data.get("from_client_id") or 0)
    to_id = int(data.get("to_client_id") or 0)

    if from_id <= 0 or to_id <= 0 or from_id == to_id:
        return jsonify({"ok": False, "message": "BAD_IDS"}), 400

    s = get_session()
    try:
        src = s.query(Client).filter_by(id=from_id, company_id=company_id).first()
        dst = s.query(Client).filter_by(id=to_id, company_id=company_id).first()
        if not src or not dst:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        # РїРµСЂРµРЅРѕСЃ identities
        src_ids = s.query(ClientIdentity).filter_by(company_id=company_id, client_id=src.id).all()
        for x in src_ids:
            # РµСЃР»Рё Сѓ dst СѓР¶Рµ РµСЃС‚СЊ С‚Р°РєРѕР№ identity вЂ” СѓРґР°Р»СЏРµРј РґСѓР±Р»СЊ
            dup = (
                s.query(ClientIdentity)
                .filter_by(company_id=company_id, kind=x.kind, value=x.value)
                .first()
            )
            if dup and int(dup.client_id) == int(dst.id):
                s.delete(x)
            else:
                x.client_id = dst.id

        # РїРµСЂРµРЅРѕСЃ assignments (С‡С‚РѕР±С‹ 1 РєР»РёРµРЅС‚ РјРѕРі РёРјРµС‚СЊ РЅРµСЃРєРѕР»СЊРєРѕ РјРµРЅРµРґР¶РµСЂРѕРІ)
        src_as = s.query(ClientAssignment).filter_by(company_id=company_id, client_id=src.id).all()
        for a in src_as:
            dup = (
                s.query(ClientAssignment)
                .filter_by(company_id=company_id, client_id=dst.id, user_id=a.user_id)
                .first()
            )
            if dup:
                s.delete(a)
            else:
                a.client_id = dst.id

        # РїРѕРјРµС‡Р°РµРј src РєР°Рє РѕР±СЉРµРґРёРЅС‘РЅРЅС‹Р№
        src.merged_into_id = dst.id
        src.is_archived = True
        src.status = "merged"

        s.commit()
        return jsonify({"ok": True, "merged": {"from": src.id, "to": dst.id}}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "MERGE_FAILED", "error": str(e)}), 500
    finally:
        s.close()

@crm_clients_bp.route("/board", methods=["GET"])
@token_required
def board():
    company_id = _company_id()
    
    payload = getattr(request, "user", None) or {}
    role = str(payload.get("role") or "").strip().lower()
    user_id = int(payload.get("user_id") or payload.get("userId") or payload.get("id") or 0)

    pipeline_id = request.args.get("pipeline_id", "").strip()
    pid = int(pipeline_id) if pipeline_id.isdigit() else 0
    if pid <= 0:
        return jsonify({"ok": False, "message": "PIPELINE_ID_REQUIRED"}), 400

    s = get_session()
    try:
        # 1) СЌС‚Р°РїС‹
        stages = (
            s.query(PipelineStage)
            .filter(PipelineStage.company_id == company_id)
            .filter(PipelineStage.pipeline_id == pid)
            .filter(PipelineStage.is_enabled == True)
            .order_by(PipelineStage.order_index.asc(), PipelineStage.id.asc())
            .all()
        )

        stage_items = [{
            "id": int(st.id),
            "name": st.name or "",
            "order_index": int(st.order_index or 0),
        } for st in stages]

        stage_ids = [int(st.id) for st in stages]

        # 2) РєР»РёРµРЅС‚С‹ СЌС‚РѕР№ РІРѕСЂРѕРЅРєРё (РєР°СЂС‚С‹)
        q_clients = (
            s.query(Client)
            .filter(Client.company_id == company_id)
            .filter(Client.is_archived == False)
            .filter(Client.pipeline_id == pid)
        )

        # ACL: РєС‚Рѕ РєР°РєРёРµ РєР°СЂС‚С‹ РІРёРґРёС‚
        if role not in ("admin", "integrator", "director", "president"):
            u = (
                s.query(User)
                 .filter(User.company_id == company_id, User.id == int(user_id))
                 .first()
            )
            if not u:
                q_clients = q_clients.filter(Client.id == -1)
            else:
                # Р СѓРєРѕРІРѕРґРёС‚РµР»СЊ РѕС‚РґРµР»Р°: РєР°СЂС‚С‹ СЃРІРѕРµРіРѕ РѕС‚РґРµР»Р° (С‡РµСЂРµР· РЅР°Р·РЅР°С‡РµРЅРёРµ РєР»РёРµРЅС‚РѕРІ СЃРѕС‚СЂСѓРґРЅРёРєР°Рј РѕС‚РґРµР»Р°)
                if getattr(u, "is_department_head", False) and getattr(u, "department_id", None):
                    dep_id = int(u.department_id)

                    q_clients = q_clients.filter(
                        Client.id.in_(
                            s.query(ClientAssignment.client_id)
                             .join(User, User.id == ClientAssignment.user_id)
                             .filter(ClientAssignment.company_id == company_id)
                             .filter(User.company_id == company_id)
                             .filter(User.department_id == dep_id)
                        )
                    )
                else:
                    # РњРµРЅРµРґР¶РµСЂ: С‚РѕР»СЊРєРѕ СЃРІРѕРё РєР°СЂС‚С‹ (РіРґРµ РѕРЅ РЅР°Р·РЅР°С‡РµРЅ РІ ClientAssignment)
                    q_clients = q_clients.filter(
                        Client.id.in_(
                            s.query(ClientAssignment.client_id)
                             .filter(ClientAssignment.company_id == company_id)
                             .filter(ClientAssignment.user_id == int(user_id))
                        )
                    )

        clients = (
            q_clients
            .order_by(Client.id.desc())
            .limit(500)
            .all()
        )


        client_ids = [int(c.id) for c in clients]

        # 3) identities
        ids_rows = []
        if client_ids:
            ids_rows = (
                s.query(ClientIdentity)
                .filter(ClientIdentity.company_id == company_id)
                .filter(ClientIdentity.client_id.in_(client_ids))
                .order_by(
                    ClientIdentity.client_id.asc(),
                    ClientIdentity.is_primary.desc(),
                    ClientIdentity.id.asc()
                )
                .all()
            )

        ids_map = {}
        for x in ids_rows:
            cid = int(x.client_id)
            if cid not in ids_map:
                ids_map[cid] = []
            ids_map[cid].append({
                "kind": x.kind or "",
                "value": x.value or "",
                "is_primary": bool(x.is_primary),
            })

        # 4) assignments
        as_rows = []
        if client_ids:
            as_rows = (
                s.query(ClientAssignment)
                .filter(ClientAssignment.company_id == company_id)
                .filter(ClientAssignment.client_id.in_(client_ids))
                .order_by(ClientAssignment.client_id.asc(), ClientAssignment.id.asc())
                .all()
            )

        as_map = {}
        for a in as_rows:
            cid = int(a.client_id)
            if cid not in as_map:
                as_map[cid] = []
            as_map[cid].append({
                "user_id": int(a.user_id),
                "role": a.role or "",
            })

        # 4.1) users_map: user_id -> name (С‡С‚РѕР±С‹ РѕС‚РґР°С‚СЊ owner_name РІ РјРёРЅРёРєР°СЂС‚Рµ)
        users_map = {}
        user_ids = set()
        for cid, arr in as_map.items():
            for x in (arr or []):
                uid = int(x.get("user_id") or 0)
                if uid > 0:
                    user_ids.add(uid)

        if user_ids:
            users = (
                s.query(User)
                .filter(User.company_id == company_id)
                .filter(User.id.in_(list(user_ids)))
                .all()
            )
            for u in users:
                users_map[int(u.id)] = (u.full_name or u.username or "").strip()

        # 5) РіСЂСѓРїРїРёСЂРѕРІРєР° РїРѕ СЌС‚Р°РїР°Рј
        by_stage = {st_id: [] for st_id in stage_ids}

        for c in clients:
            st_id = int(c.stage_id) if c.stage_id else 0
            if st_id not in by_stage:
                by_stage[st_id] = []

            identities = ids_map.get(int(c.id), [])
            primary = identities[0] if identities else None

            channel = ""
            title = c.name or ""
            if primary:
                channel = (primary.get("kind") or "").lower()
                if not title.strip():
                    title = primary.get("value") or ""

            assignments = as_map.get(int(c.id), [])
            uid0 = int(assignments[0]["user_id"]) if assignments else 0
            owner_name = users_map.get(uid0, "") if uid0 > 0 else ""

            by_stage[st_id].append({
                "id": int(c.id),
                "title": title,
                "channel": channel,
                "identities": identities,
                "assignments": assignments,
                "owner_name": owner_name,   # <-- Р’РђР–РќРћ РґР»СЏ WPF OwnerName
                "unread": 0,
            })

        return jsonify({
            "ok": True,
            "pipeline_id": pid,
            "stages": stage_items,
            "cards_by_stage": by_stage,
        }), 200

    finally:
        s.close()



@crm_clients_bp.route("/clients/<int:client_id>/assignments", methods=["POST"])
@token_required
def set_assignments(client_id: int):
    payload = getattr(request, "user", None) or {}
    if str(payload.get("role") or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    user_ids = data.get("user_ids") or []
    if not isinstance(user_ids, list):
        return jsonify({"ok": False, "message": "BAD_USER_IDS"}), 400

    # РЅРѕСЂРјР°Р»РёР·СѓРµРј
    clean_ids = []
    for x in user_ids:
        try:
            uid = int(x)
            if uid > 0 and uid not in clean_ids:
                clean_ids.append(uid)
        except:
            pass

    s = get_session()
    try:
        c = s.query(Client).filter_by(id=int(client_id), company_id=company_id).first()
        if not c:
            return jsonify({"ok": False, "message": "CLIENT_NOT_FOUND"}), 404

        # С‚РµРєСѓС‰РµРµ
        rows = (
            s.query(ClientAssignment)
            .filter_by(company_id=company_id, client_id=c.id)
            .all()
        )

        existing = {int(r.user_id): r for r in rows}

        # СѓРґР°Р»РёС‚СЊ Р»РёС€РЅРёРµ
        for uid, row in list(existing.items()):
            if uid not in clean_ids:
                s.delete(row)

        # РґРѕР±Р°РІРёС‚СЊ РЅРѕРІС‹Рµ
        for uid in clean_ids:
            if uid not in existing:
                s.add(ClientAssignment(
                    company_id=company_id,
                    client_id=c.id,
                    user_id=uid,
                    role="responsible",
                    created_ts_ms=_now_ms(),
                ))

        # --- Р»РѕРі РёР·РјРµРЅРµРЅРёСЏ РѕС‚РІРµС‚СЃС‚РІРµРЅРЅРѕРіРѕ (РґРѕР±Р°РІРёР»Рё/СѓР±СЂР°Р»Рё) ---
        old_user_ids = [int(r.user_id) for r in rows]
        new_user_ids = clean_ids

        old_set = set(old_user_ids)
        new_set = set(new_user_ids)

        if old_set != new_set:
            all_ids = list(old_set.union(new_set))

            users = (
                s.query(User)
                 .filter(User.company_id == company_id)
                 .filter(User.id.in_(all_ids))
                 .all()
            )
            name_by_id = {int(u.id): (u.full_name or u.username or "").strip() for u in users}

            def _names(ids):
                out = []
                for uid in ids:
                    nm = name_by_id.get(int(uid), "")
                    if nm:
                        out.append(nm)
                return out

            added = _names([uid for uid in new_user_ids if uid not in old_set])
            removed = _names([uid for uid in old_user_ids if uid not in new_set])
            now_list = _names(new_user_ids)

            parts = []
            if added: parts.append("РґРѕР±Р°РІР»РµРЅ: " + ", ".join(added))
            if removed: parts.append("СѓР±СЂР°РЅ: " + ", ".join(removed))
            parts.append("С‚РµРїРµСЂСЊ: " + (", ".join(now_list) if now_list else "РЅРµ РЅР°Р·РЅР°С‡РµРЅ"))

            text = "РћС‚РІРµС‚СЃС‚РІРµРЅРЅС‹Р№ РёР·РјРµРЅС‘РЅ: " + " | ".join(parts)

            s.add(Note(
                company_id=company_id,
                client_id=c.id,
                created_by_user_id=int(payload.get("user_id") or 0),
                description=text,
                type="system",
                created_ts_ms=_now_ms(),
                updated_ts_ms=_now_ms(),
            ))

        s.commit()
        return jsonify({"ok": True, "user_ids": clean_ids}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "ASSIGN_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@crm_clients_bp.route("/clients/<int:client_id>/assignments", methods=["GET"])
@token_required
def get_assignments(client_id: int):
    company_id = _company_id()
    s = get_session()
    try:
        rows = (
            s.query(ClientAssignment)
            .filter_by(company_id=company_id, client_id=int(client_id))
            .order_by(ClientAssignment.id.asc())
            .all()
        )
        user_ids = [int(r.user_id) for r in rows]
        return jsonify({"ok": True, "user_ids": user_ids}), 200
    finally:
        s.close()


@crm_clients_bp.route("/board/stage_cards", methods=["GET"])
@token_required
def board_stage_cards():
    company_id = _company_id()

    payload = getattr(request, "user", None) or {}
    role = str(payload.get("role") or "").strip().lower()
    user_id = int(payload.get("user_id") or payload.get("userId") or payload.get("id") or 0)

    pipeline_id = request.args.get("pipeline_id", "").strip()
    stage_id = request.args.get("stage_id", "").strip()

    pid = int(pipeline_id) if pipeline_id.isdigit() else 0
    sid = int(stage_id) if stage_id.isdigit() else 0
    if pid <= 0 or sid <= 0:
        return jsonify({"ok": False, "message": "PIPELINE_STAGE_REQUIRED"}), 400

    try:
        limit = int(request.args.get("limit") or 50)
    except:
        limit = 50
    try:
        offset = int(request.args.get("offset") or 0)
    except:
        offset = 0

    # пїЅпїЅпїЅпїЅпїЅпїЅ
    if limit < 1: limit = 1
    if limit > 200: limit = 200
    if offset < 0: offset = 0

    s = get_session()
    try:
        # base query
        q_clients = (
            s.query(Client)
            .filter(Client.company_id == company_id)
            .filter(Client.is_archived == False)
            .filter(Client.pipeline_id == pid)
            .filter(Client.stage_id == sid)
        )

        # ACL (пїЅпїЅпїЅпїЅпїЅ пїЅпїЅпїЅпїЅпїЅпїЅ пїЅпїЅ board) :contentReference[oaicite:0]{index=0}
        if role not in ("admin", "integrator", "director", "president"):
            u = (
                s.query(User)
                 .filter(User.company_id == company_id, User.id == int(user_id))
                 .first()
            )
            if not u:
                q_clients = q_clients.filter(Client.id == -1)
            else:
                if getattr(u, "is_department_head", False) and getattr(u, "department_id", None):
                    dep_id = int(u.department_id)
                    q_clients = q_clients.filter(
                        Client.id.in_(
                            s.query(ClientAssignment.client_id)
                             .join(User, User.id == ClientAssignment.user_id)
                             .filter(ClientAssignment.company_id == company_id)
                             .filter(User.company_id == company_id)
                             .filter(User.department_id == dep_id)
                        )
                    )
                else:
                    q_clients = q_clients.filter(
                        Client.id.in_(
                            s.query(ClientAssignment.client_id)
                             .filter(ClientAssignment.company_id == company_id)
                             .filter(ClientAssignment.user_id == int(user_id))
                        )
                    )

        clients = (
            q_clients
            .order_by(Client.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        client_ids = [int(c.id) for c in clients]

        # identities
        ids_map = {}
        if client_ids:
            ids_rows = (
                s.query(ClientIdentity)
                .filter(ClientIdentity.company_id == company_id)
                .filter(ClientIdentity.client_id.in_(client_ids))
                .order_by(
                    ClientIdentity.client_id.asc(),
                    ClientIdentity.is_primary.desc(),
                    ClientIdentity.id.asc()
                )
                .all()
            )
            for x in ids_rows:
                cid = int(x.client_id)
                if cid not in ids_map:
                    ids_map[cid] = []
                ids_map[cid].append({
                    "kind": x.kind or "",
                    "value": x.value or "",
                    "is_primary": bool(x.is_primary),
                })

        # assignments
        as_map = {}
        if client_ids:
            as_rows = (
                s.query(ClientAssignment)
                .filter(ClientAssignment.company_id == company_id)
                .filter(ClientAssignment.client_id.in_(client_ids))
                .order_by(ClientAssignment.client_id.asc(), ClientAssignment.id.asc())
                .all()
            )
            for a in as_rows:
                cid = int(a.client_id)
                if cid not in as_map:
                    as_map[cid] = []
                as_map[cid].append({
                    "user_id": int(a.user_id),
                    "role": a.role or "",
                })

        # users_map
        users_map = {}
        user_ids = set()
        for cid, arr in as_map.items():
            for x in (arr or []):
                uid = int(x.get("user_id") or 0)
                if uid > 0:
                    user_ids.add(uid)

        if user_ids:
            users = (
                s.query(User)
                .filter(User.company_id == company_id)
                .filter(User.id.in_(list(user_ids)))
                .all()
            )
            for u in users:
                users_map[int(u.id)] = (u.full_name or u.username or "").strip()

        cards = []
        for c in clients:
            identities = ids_map.get(int(c.id), [])
            primary = identities[0] if identities else None

            channel = ""
            title = c.name or ""
            if primary:
                channel = (primary.get("kind") or "").lower()
                if not title.strip():
                    title = primary.get("value") or ""

            assignments = as_map.get(int(c.id), [])
            uid0 = int(assignments[0]["user_id"]) if assignments else 0
            owner_name = users_map.get(uid0, "") if uid0 > 0 else ""

            cards.append({
                "id": int(c.id),
                "title": title,
                "channel": channel,
                "owner_name": owner_name,
                "unread": 0,
            })

        has_more = (len(cards) == limit)

        return jsonify({
            "ok": True,
            "pipeline_id": pid,
            "stage_id": sid,
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "cards": cards,
        }), 200

    finally:
        s.close()