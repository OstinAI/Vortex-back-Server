# -*- coding: utf-8 -*-
import time
import json
import os
import requests
from db.models import WhatsAppNumber, Client, ClientIdentity

from db.models import WhatsAppMessage, ClientIdentity
from sqlalchemy import func
from db.models import AutomationJob
from db.models import (
    Client, ClientAssignment, User,
    Task, TaskAssignee,
    Note,
    LeadRoundRobinState
)


def _now_ms():
    return int(time.time() * 1000)


def _ensure_client_exists(s, company_id: int, client_id: int):
    return (
        s.query(Client)
        .filter(Client.company_id == int(company_id))
        .filter(Client.id == int(client_id))
        .first()
    )


def _action_add_note(s, company_id: int, ctx: dict, a: dict, actor_user_id: int = 0):
    client_id = int(ctx.get("client_id") or 0)
    if client_id <= 0:
        return
    if not _ensure_client_exists(s, company_id, client_id):
        return

    text = (a.get("text") or "").strip()
    if not text:
        return

    s.add(Note(
        company_id=int(company_id),
        client_id=int(client_id),
        department_id=None,
        created_by_user_id=int(actor_user_id or 0) if int(actor_user_id or 0) > 0 else None,
        description=text,
        type="system",
        created_ts_ms=_now_ms(),
        updated_ts_ms=_now_ms(),
    ))


def _action_create_task(s, company_id: int, ctx: dict, a: dict, actor_user_id: int = 0):
    client_id = int(ctx.get("client_id") or 0)
    if client_id <= 0:
        return
    if not _ensure_client_exists(s, company_id, client_id):
        return

    title = (a.get("title") or "").strip()
    if not title:
        return

    due_minutes = a.get("due_minutes")
    try:
        due_minutes = int(due_minutes) if due_minutes is not None else None
    except:
        due_minutes = None

    now = _now_ms()
    end_ts = None
    if due_minutes is not None and due_minutes > 0:
        end_ts = now + due_minutes * 60 * 1000

    t = Task(
        company_id=int(company_id),
        client_id=int(client_id),
        department_id=None,
        created_by_user_id=int(actor_user_id or 0) if int(actor_user_id or 0) > 0 else None,
        title=title,
        description=(a.get("description") or ""),
        start_ts_ms=now,
        end_ts_ms=end_ts,
        status="open",
        priority=(a.get("priority") or "normal"),
        created_ts_ms=now,
        updated_ts_ms=now,
    )
    s.add(t)
    s.flush()

    # assignees: user_ids OR from ctx["assigned_user_id"]
    user_ids = a.get("user_ids")
    if not isinstance(user_ids, list):
        user_ids = []

    if not user_ids:
        uid = int(ctx.get("assigned_user_id") or 0)
        if uid > 0:
            user_ids = [uid]

    clean = []
    for x in user_ids:
        try:
            uid = int(x)
            if uid > 0 and uid not in clean:
                clean.append(uid)
        except:
            pass

    for uid in clean:
        s.add(TaskAssignee(
            company_id=int(company_id),
            task_id=int(t.id),
            user_id=int(uid),
            created_ts_ms=now,
        ))


def _pick_managers(s, company_id: int, a: dict, ctx: dict):
    role = (a.get("role") or "Manager").strip()
    dep_id = a.get("department_id")
    region_id = a.get("region_id")

    try:
        dep_id = int(dep_id) if dep_id is not None else 0
    except:
        dep_id = 0

    try:
        region_id = int(region_id) if region_id is not None else 0
    except:
        region_id = 0

    # если не передали — можно брать из ctx
    if dep_id <= 0:
        dep_id = int(ctx.get("department_id") or 0)
    if region_id <= 0:
        region_id = int(ctx.get("region_id") or 0)

    q = (
        s.query(User)
        .filter(User.company_id == int(company_id))
        .filter(User.status == "active")
        .filter(User.role == role)
    )
    if dep_id > 0:
        q = q.filter(User.department_id == dep_id)

    # region filter (если используешь M2M user_regions, тут не фильтрую, чтобы не усложнять v1)
    managers = q.order_by(User.id.asc()).all()
    return managers, role, dep_id, region_id


def _assign_user(s, company_id: int, client_id: int, user_id: int, role: str = "responsible", replace: bool = False):
    if replace:
        rows = (
            s.query(ClientAssignment)
            .filter(ClientAssignment.company_id == int(company_id))
            .filter(ClientAssignment.client_id == int(client_id))
            .filter((ClientAssignment.role == role) | (ClientAssignment.role == None) | (ClientAssignment.role == ""))
            .all()
        )
        for r in rows:
            s.delete(r)
        s.flush()

    exists = (
        s.query(ClientAssignment)
        .filter(ClientAssignment.company_id == int(company_id))
        .filter(ClientAssignment.client_id == int(client_id))
        .filter(ClientAssignment.user_id == int(user_id))
        .filter((ClientAssignment.role == role) | (ClientAssignment.role == None) | (ClientAssignment.role == ""))
        .first()
    )
    if exists:
        return

    s.add(ClientAssignment(
        company_id=int(company_id),
        client_id=int(client_id),
        user_id=int(user_id),
        role=role,
        created_ts_ms=_now_ms(),
    ))


def _action_assign_manager(s, company_id: int, ctx: dict, a: dict, actor_user_id: int = 0):
    client_id = int(ctx.get("client_id") or 0)
    if client_id <= 0:
        return

    c = _ensure_client_exists(s, company_id, client_id)
    if not c:
        return

    assignment_role = (a.get("assignment_role") or "responsible").strip() or "responsible"
    replace_existing = bool(a.get("replace_existing", False))

    # если уже назначен ответственный — можно не трогать
    if bool(a.get("skip_if_assigned", True)) and not replace_existing:
        ex = (
            s.query(ClientAssignment)
            .filter(ClientAssignment.company_id == int(company_id))
            .filter(ClientAssignment.client_id == int(client_id))
            .filter(ClientAssignment.role == assignment_role)
            .first()
        )
        if ex:
            return

    # ====== 1) если в actions_json передали user_ids — используем их напрямую ======
    managers = []
    role = ""
    dep_id = 0
    region_id = 0

    raw_ids = a.get("user_ids") or []
    if isinstance(raw_ids, list) and raw_ids:
        clean_ids = []
        for x in raw_ids:
            try:
                uid = int(x)
                if uid > 0 and uid not in clean_ids:
                    clean_ids.append(uid)
            except:
                pass

        if clean_ids:
            managers = (
                s.query(User)
                .filter(User.company_id == int(company_id))
                .filter(User.status == "active")
                .filter(User.id.in_(clean_ids))
                .order_by(User.id.asc())
                .all()
            )
            # для round_robin ключа (чтобы разные наборы user_ids не мешались)
            role = f"user_ids:{','.join(map(str, clean_ids))}"

            try:
                dep_id = int(a.get("department_id") if a.get("department_id") is not None else (ctx.get("department_id") or 0))
            except:
                dep_id = int(ctx.get("department_id") or 0)

            try:
                region_id = int(a.get("region_id") if a.get("region_id") is not None else (ctx.get("region_id") or 0))
            except:
                region_id = int(ctx.get("region_id") or 0)

            if not managers:
                return

    # ====== 2) если user_ids не дали — берём менеджеров как раньше (по role/dep) ======
    if not managers:
        managers, role, dep_id, region_id = _pick_managers(s, company_id, a, ctx)
        if not managers:
            return

    mode = (a.get("mode") or "round_robin").strip().lower()
    chosen = None

    if mode == "least_loaded":
        best = None
        for u in managers:
            cnt = (
                s.query(ClientAssignment)
                .filter(ClientAssignment.company_id == int(company_id))
                .filter(ClientAssignment.user_id == int(u.id))
                .count()
            )
            if best is None or cnt < best[1]:
                best = (u, cnt)
        chosen = best[0] if best else None

    else:
        key = f"pipe:{int(ctx.get('pipeline_id') or 0)}:stage:{int(ctx.get('stage_id') or 0)}:role:{role}:dep:{dep_id}:region:{region_id}"

        st = (
            s.query(LeadRoundRobinState)
            .filter(LeadRoundRobinState.company_id == int(company_id))
            .filter(LeadRoundRobinState.key == key)
            .first()
        )
        last_id = int(st.last_user_id) if st and st.last_user_id else 0

        ids = [int(u.id) for u in managers]
        if last_id in ids:
            idx = ids.index(last_id)
            chosen = managers[(idx + 1) % len(managers)]
        else:
            chosen = managers[0]

        now = _now_ms()
        if not st:
            st = LeadRoundRobinState(company_id=int(company_id), key=key)
            s.add(st)
        st.last_user_id = int(chosen.id)
        st.updated_ts_ms = now

    if not chosen:
        return

    _assign_user(s, company_id, client_id, int(chosen.id), role=assignment_role, replace=replace_existing)

    ctx["assigned_user_id"] = int(chosen.id)

    if bool(a.get("add_note", True)):
        nm = (chosen.full_name or chosen.username or "").strip()
        _action_add_note(s, company_id, ctx, {"text": f"Авто: назначен ответственный: {nm}"}, actor_user_id=actor_user_id)

def _action_move_stage(s, company_id: int, ctx: dict, a: dict, actor_user_id: int = 0):
    client_id = int(ctx.get("client_id") or 0)
    if client_id <= 0:
        return

    c = _ensure_client_exists(s, company_id, client_id)
    if not c:
        return

    pid = a.get("pipeline_id")
    sid = a.get("stage_id")

    pid = int(pid) if pid is not None else int(c.pipeline_id or 0)
    sid = int(sid) if sid is not None else 0
    if sid <= 0:
        return

    # === delayed ===
    run_at = a.get("run_at_ts_ms")
    delay = a.get("delay_minutes")

    now = _now_ms()

    try:
        run_at = int(run_at) if run_at is not None else 0
    except:
        run_at = 0

    try:
        delay = int(delay) if delay is not None else 0
    except:
        delay = 0

    if run_at > now or delay > 0:
        if delay > 0 and run_at <= 0:
            run_at = now + delay * 60 * 1000

        job = AutomationJob(
            company_id=int(company_id),
            action_type="move_stage",
            action_json=json.dumps({"pipeline_id": pid, "stage_id": sid}, ensure_ascii=False),
            ctx_json=json.dumps({"client_id": int(client_id)}, ensure_ascii=False),
            run_at_ts_ms=int(run_at),
            status="pending",
            error="",
            created_ts_ms=now,
            updated_ts_ms=now,
        )
        s.add(job)
        return

    # === immediate ===
    c.pipeline_id = pid if pid > 0 else c.pipeline_id
    c.stage_id = sid


def _action_assign_users(s, company_id: int, ctx: dict, a: dict, actor_user_id: int = 0):
    client_id = int(ctx.get("client_id") or 0)
    if client_id <= 0:
        return
    c = _ensure_client_exists(s, company_id, client_id)
    if not c:
        return

    user_ids = a.get("user_ids") or []
    if not isinstance(user_ids, list):
        return

    clean = []
    for x in user_ids:
        try:
            uid = int(x)
            if uid > 0 and uid not in clean:
                clean.append(uid)
        except:
            pass

    if not clean:
        return

    role = (a.get("role") or "responsible").strip() or "responsible"

    for uid in clean:
        _assign_user(s, company_id, client_id, int(uid), role=role)

    # положим первого как assigned_user_id
    ctx["assigned_user_id"] = int(clean[0])

    if bool(a.get("add_note", True)):
        _action_add_note(s, company_id, ctx, {"text": f"Авто: назначены пользователи: {', '.join(map(str, clean))}"}, actor_user_id=actor_user_id)


def _action_clear_assignments(s, company_id: int, ctx: dict, a: dict, actor_user_id: int = 0):
    client_id = int(ctx.get("client_id") or 0)
    if client_id <= 0:
        return

    c = _ensure_client_exists(s, company_id, client_id)
    if not c:
        return

    rows = (
        s.query(ClientAssignment)
        .filter(ClientAssignment.company_id == int(company_id))
        .filter(ClientAssignment.client_id == int(client_id))
        .all()
    )

    for r in rows:
        s.delete(r)

    # очищаем из ctx
    ctx["assigned_user_id"] = 0

    if bool(a.get("add_note", True)):
        _action_add_note(
            s,
            company_id,
            ctx,
            {"text": "Авто: все ответственные сняты"},
            actor_user_id=actor_user_id
        )

def _action_send_message(s, company_id: int, ctx: dict, a: dict, actor_user_id: int = 0):
    client_id = int(ctx.get("client_id") or 0)
    if client_id <= 0:
        return

    c = _ensure_client_exists(s, company_id, client_id)
    if not c:
        return

    text = (a.get("text") or "").strip()
    if not text:
        return

    # берём основной whatsapp identity клиента
    ident = (
        s.query(ClientIdentity)
        .filter(ClientIdentity.company_id == int(company_id))
        .filter(ClientIdentity.client_id == int(client_id))
        .filter(ClientIdentity.kind == "whatsapp")
        .order_by(ClientIdentity.is_primary.desc(), ClientIdentity.id.asc())
        .first()
    )
    if not ident:
        return

    now = _now_ms()

    # создаём WA сообщение (worker доставки уже у тебя есть)
    msg = WhatsAppMessage(
        company_id=int(company_id),
        wa_phone="",  # если нужно — подставим позже номер компании
        peer_phone=ident.value,
        direction="out",
        text=text,
        ts_ms=now,
        status="pending",
        wa_msg_id="",
        msg_key="",
    )
    s.add(msg)
    
def _action_send_whatsapp(s, company_id: int, ctx: dict, a: dict, actor_user_id: int = 0):
    text = (a.get("text") or "").strip()
    if not text:
        return

    to = (a.get("to") or "").strip()

    # авто-номер клиента
    if not to:
        cid = 0
        try:
            cid = int(ctx.get("client_id") or 0)
        except:
            cid = 0

        if cid > 0:
            ident = (
                s.query(ClientIdentity)
                 .filter(ClientIdentity.company_id == int(company_id))
                 .filter(ClientIdentity.client_id == int(cid))
                 .filter(ClientIdentity.kind == "whatsapp")
                 .order_by(ClientIdentity.is_primary.desc(), ClientIdentity.id.asc())
                 .first()
            )
            if ident and getattr(ident, "value", None):
                to = (ident.value or "").strip()

            # fallback: phone в Client
            if not to:
                c = (
                    s.query(Client)
                     .filter(Client.company_id == int(company_id))
                     .filter(Client.id == int(cid))
                     .first()
                )
                if c:
                    to = (getattr(c, "phone", "") or "").strip()

    if not to:
        raise Exception("WA_CLIENT_PHONE_NOT_FOUND")

    # какой WA номер компании использовать
    wa_phone = (a.get("wa_phone") or "").strip()
    if not wa_phone:
        row = (
            s.query(WhatsAppNumber)
             .filter(WhatsAppNumber.company_id == int(company_id))
             .filter(WhatsAppNumber.is_active == True)
             .order_by(WhatsAppNumber.id.asc())
             .first()
        )
        wa_phone = (getattr(row, "phone", "") or "").strip()

    if not wa_phone:
        raise Exception("WA_NO_ACTIVE_NUMBER")

    crm_base = os.getenv("CRM_BASE_URL", "http://127.0.0.1:5000")
    internal_token = os.getenv("INTERNAL_AUTOMATOR_TOKEN", "").strip()

    if not internal_token:
        raise Exception("INTERNAL_AUTOMATOR_TOKEN_NOT_SET")

    try:
        resp = requests.post(
            f"{crm_base}/api/whatsapp/internal/send",
            json={
                "phone": wa_phone,
                "to": to,
                "text": text
            },
            headers={
                "X-Internal-Token": internal_token
            },
            timeout=30
        )
    except Exception as ex:
        raise Exception("WA_HTTP_ERROR: " + str(ex))

    txt = resp.text or ""

    if resp.status_code != 200:
        raise Exception(f"WA_SEND_HTTP_{resp.status_code}: {txt}")

    try:
        data = resp.json()
    except:
        data = {}

    if data.get("ok") is False:
        raise Exception("WA_SEND_FAIL: " + str(data.get("message") or txt))

    

ACTIONS = {
    "add_note": _action_add_note,
    "create_task": _action_create_task,
    "assign_manager": _action_assign_manager,
    "move_stage": _action_move_stage,
    "assign_users": _action_assign_users,
    "clear_assignments": _action_clear_assignments,
    "send_message": _action_send_message,
    "send_whatsapp": _action_send_whatsapp,
}


