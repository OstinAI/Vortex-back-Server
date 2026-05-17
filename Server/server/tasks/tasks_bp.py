# -*- coding: utf-8 -*-
import time
from flask import Blueprint, jsonify, request

from utils.security import token_required
from db.connection import get_session
from db.models import Task, TaskAssignee, Client, User, Department, ClientAssignment
from sqlalchemy import or_

tasks_bp = Blueprint("tasks", __name__)

def _now_ms() -> int:
    return int(time.time() * 1000)

def _payload():
    return getattr(request, "user", None) or {}

def _company_id() -> int:
    payload = _payload()
    return int(payload.get("company_id") or payload.get("companyId") or 0)

def _user_id() -> int:
    payload = _payload()
    return int(payload.get("user_id") or payload.get("userId") or payload.get("id") or 0)



def _role() -> str:
    payload = _payload()
    return str(payload.get("role") or "")


def _clean_status(v: str) -> str:
    v = (v or "").strip().lower()
    allowed = {"open", "in_progress", "done", "canceled"}
    return v if v in allowed else "open"

def _clean_priority(v: str) -> str:
    v = (v or "").strip().lower()
    allowed = {"normal", "urgent"}
    return v if v in allowed else "normal"

def _int_or_none(x):
    try:
        if x is None:
            return None
        return int(x)
    except:
        return None

def _my_department_id(s, company_id: int, user_id: int) -> int:
    if company_id <= 0 or user_id <= 0:
        return 0
    u = s.query(User).filter_by(id=int(user_id), company_id=int(company_id)).first()
    return int(getattr(u, "department_id", 0) or 0) if u else 0

def _apply_acl_query(q, s, company_id: int, role: str, user_id: int, dep_id: int):
    """
    Admin / Integrator -> все задачи
    Руководитель отдела (is_department_head=True) -> задачи своего отдела
    Менеджер -> только свои задачи
    """
    role_norm = (role or "").strip().lower()

    # Админ / интегратор — всё
    if role_norm in ("admin", "integrator", "director", "president"):
        return q


    # проверяем пользователя
    user = (
        s.query(User)
         .filter(User.company_id == company_id, User.id == user_id)
         .first()
    )
    if not user:
        return q.filter(Task.id == -1)

    # Руководитель отдела
    if user.is_department_head and user.department_id:
        dep_id = int(user.department_id)

        return q.filter(
            or_(
                # задача явно на отдел
                Task.department_id == dep_id,

                # создатель из отдела
                Task.created_by_user_id.in_(
                    s.query(User.id)
                     .filter(User.company_id == company_id)
                     .filter(User.department_id == dep_id)
                ),

                # назначенные из отдела
                Task.id.in_(
                    s.query(TaskAssignee.task_id)
                     .join(User, User.id == TaskAssignee.user_id)
                     .filter(TaskAssignee.company_id == company_id)
                     .filter(User.department_id == dep_id)
                )
            )
        )

    # Обычный менеджер — ТОЛЬКО свои задачи
    return q.filter(
        or_(
            Task.created_by_user_id == user_id,

            Task.id.in_(
                s.query(TaskAssignee.task_id)
                 .filter(TaskAssignee.company_id == company_id)
                 .filter(TaskAssignee.user_id == user_id)
            ),

            Task.client_id.in_(
                s.query(ClientAssignment.client_id)
                 .filter(ClientAssignment.company_id == company_id)
                 .filter(ClientAssignment.user_id == user_id)
            )
        )
    )

def _get_task_with_acl(s, company_id: int, task_id: int, role: str, user_id: int, dep_id: int):
    q = s.query(Task).filter(Task.company_id == int(company_id)).filter(Task.id == int(task_id))
    q = _apply_acl_query(q, s, int(company_id), role, int(user_id), int(dep_id))
    return q.first()


@tasks_bp.route("/", methods=["POST"])
@token_required
def create_task():
    """
    POST /api/tasks/
    body:
    {
      "client_id": 10,
      "title": "Позвонить",
      "description": "уточнить адрес",
      "start_ts_ms": 1730000000000,
      "end_ts_ms": null,
      "status": "open",
      "priority": "urgent",
      "department_id": 3,
      "assignees": [5,7,9]
    }
    """
    company_id = _company_id()
    creator_id = _user_id()
    data = request.get_json(silent=True) or {}

    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    client_id = _int_or_none(data.get("client_id"))
    title = (data.get("title") or "").strip()
    description = data.get("description") or ""
    start_ts_ms = _int_or_none(data.get("start_ts_ms")) or 0
    end_ts_ms = _int_or_none(data.get("end_ts_ms"))
    status = _clean_status(data.get("status"))
    priority = _clean_priority(data.get("priority"))
    department_id = _int_or_none(data.get("department_id"))
    assignees = data.get("assignees") or []

    if company_id <= 0:
        return jsonify({"ok": False, "message": "INVALID_COMPANY"}), 400

    if not title:
        return jsonify({"ok": False, "message": "TITLE_REQUIRED"}), 400

    s = get_session()
    try:
        if client_id is not None and client_id > 0:
            c = s.query(Client).filter_by(id=int(client_id), company_id=int(company_id)).first()
            if not c:
                return jsonify({"ok": False, "message": "CLIENT_NOT_FOUND"}), 404
        else:
            client_id = None

        if department_id:
            d = s.query(Department).filter_by(id=int(department_id), company_id=int(company_id)).first()
            if not d:
                return jsonify({"ok": False, "message": "DEPARTMENT_NOT_FOUND"}), 404

        now = _now_ms()

        row = Task(
            company_id=int(company_id),
            # Если клиента нет, пишем 0, чтобы строгая база в облаке не выдавала ошибку 50
            client_id=int(client_id) if client_id is not None else 0,
            department_id=int(department_id) if department_id else None,
            created_by_user_id=int(creator_id) if creator_id else None,
            title=title,
            description=str(description or ""),
            start_ts_ms=int(start_ts_ms),
            end_ts_ms=int(end_ts_ms) if end_ts_ms is not None else None,
            status=status,
            priority=priority,
            created_ts_ms=now,
            updated_ts_ms=now,
        )
        s.add(row)
        s.flush()

        # assignees
        if isinstance(assignees, list) and assignees:
            uniq_ids = []
            for uid in assignees:
                iu = _int_or_none(uid)
                if iu and iu > 0 and iu not in uniq_ids:
                    uniq_ids.append(iu)

            if uniq_ids:
                users = (
                    s.query(User)
                     .filter(User.company_id == int(company_id))
                     .filter(User.id.in_(uniq_ids))
                     .all()
                )
                found_ids = {int(u.id) for u in users}

                for uid in uniq_ids:
                    if uid in found_ids:
                        s.add(TaskAssignee(
                            company_id=int(company_id),
                            task_id=int(row.id),
                            user_id=int(uid),
                            created_ts_ms=now
                        ))

        s.commit()
        return jsonify({"ok": True, "task_id": int(row.id)}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()



@tasks_bp.route("/", methods=["GET"])
@token_required
def list_tasks():
    """
    GET /api/tasks/?client_id=10&status=open&assigned_user_id=5&department_id=3&limit=200
    """
    company_id = _company_id()
    role = _role()
    user_id = _user_id()

    
    client_id = _int_or_none(request.args.get("client_id"))
    status = (request.args.get("status") or "").strip().lower()
    assigned_user_id = _int_or_none(request.args.get("assigned_user_id"))
    department_id = _int_or_none(request.args.get("department_id"))
    limit = _int_or_none(request.args.get("limit")) or 200
    
    print("[TASKS][ACL]", "company=", company_id, "role=", role, "user_id=", user_id, "client_id=", client_id)

    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    s = get_session()
    try:
        q = s.query(Task).filter(Task.company_id == int(company_id))

        dep_id = _my_department_id(s, int(company_id), int(user_id))
        q = _apply_acl_query(q, s, int(company_id), role, int(user_id), int(dep_id))

        if client_id is not None and int(client_id) > 0:
            q = q.filter(Task.client_id == int(client_id))

        if status:
            q = q.filter(Task.status == status)

        if department_id:
            q = q.filter(Task.department_id == int(department_id))

        # ВАЖНО: assigned_user_id ограничим через пересечение, а не переписываем q join-ом
        if assigned_user_id:
            q = q.filter(
                Task.id.in_(
                    s.query(TaskAssignee.task_id)
                     .filter(TaskAssignee.company_id == int(company_id))
                     .filter(TaskAssignee.user_id == int(assigned_user_id))
                )
            )

        rows = (
            q.order_by(Task.id.desc())
             .limit(int(limit))
             .all()
        )

        items = []
        for t in rows:
            a_rows = (
                s.query(TaskAssignee)
                 .filter_by(company_id=int(company_id), task_id=int(t.id))
                 .all()
            )
            a_ids = [int(a.user_id) for a in a_rows]

            items.append({
                "id": int(t.id),
                "client_id": int(t.client_id) if t.client_id else 0,
                "department_id": int(t.department_id) if t.department_id else None,
                "title": t.title or "",
                "description": t.description or "",
                "start_ts_ms": int(t.start_ts_ms or 0),
                "end_ts_ms": int(t.end_ts_ms) if t.end_ts_ms is not None else None,
                "status": t.status or "open",
                "priority": t.priority or "normal",
                "assignees": a_ids,
                "created_ts_ms": int(t.created_ts_ms or 0),
                "updated_ts_ms": int(t.updated_ts_ms or 0),
            })

        return jsonify({"ok": True, "tasks": items}), 200
    finally:
        s.close()


@tasks_bp.route("/<int:task_id>", methods=["GET"])
@token_required
def get_task(task_id: int):

   
    company_id = _company_id()
    s = get_session()
    try:
        role = _role()
        user_id = _user_id()
        dep_id = _my_department_id(s, int(company_id), int(user_id))
        t = _get_task_with_acl(s, int(company_id), int(task_id), role, int(user_id), int(dep_id))

        if not t:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        a_rows = s.query(TaskAssignee).filter_by(company_id=int(company_id), task_id=int(t.id)).all()
        a_ids = [int(a.user_id) for a in a_rows]

        return jsonify({
            "ok": True,
            "task": {
                "id": int(t.id),
                "client_id": int(t.client_id) if t.client_id else 0,
                "department_id": int(t.department_id) if t.department_id else None,
                "title": t.title or "",
                "description": t.description or "",
                "start_ts_ms": int(t.start_ts_ms or 0),
                "end_ts_ms": int(t.end_ts_ms) if t.end_ts_ms is not None else None,
                "status": t.status or "open",
                "priority": t.priority or "normal",
                "assignees": a_ids,
                "created_ts_ms": int(t.created_ts_ms or 0),
                "updated_ts_ms": int(t.updated_ts_ms or 0),
            }
        }), 200
    finally:
        s.close()


@tasks_bp.route("/<int:task_id>", methods=["POST"])
@token_required
def update_task(task_id: int):
    """
    POST /api/tasks/<id>
    можно менять: title, description, start_ts_ms, end_ts_ms, status, priority, department_id
    """
    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    s = get_session()
    try:
        role = _role()
        user_id = _user_id()
        dep_id = _my_department_id(s, int(company_id), int(user_id))
        t = _get_task_with_acl(s, int(company_id), int(task_id), role, int(user_id), int(dep_id))

        if not t:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        if "title" in data:
            title = (data.get("title") or "").strip()
            if not title:
                return jsonify({"ok": False, "message": "TITLE_REQUIRED"}), 400
            t.title = title

        if "description" in data:
            t.description = str(data.get("description") or "")

        if "start_ts_ms" in data:
            v = _int_or_none(data.get("start_ts_ms")) or 0
            t.start_ts_ms = int(v)

        if "end_ts_ms" in data:
            v = _int_or_none(data.get("end_ts_ms"))
            t.end_ts_ms = int(v) if v is not None else None

        if "status" in data:
            t.status = _clean_status(data.get("status"))

        if "priority" in data:
            t.priority = _clean_priority(data.get("priority"))

        if "department_id" in data:
            dep = _int_or_none(data.get("department_id"))
            if dep:
                d = s.query(Department).filter_by(id=int(dep), company_id=int(company_id)).first()
                if not d:
                    return jsonify({"ok": False, "message": "DEPARTMENT_NOT_FOUND"}), 404
                t.department_id = int(dep)
            else:
                t.department_id = None

        t.updated_ts_ms = _now_ms()
        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPDATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@tasks_bp.route("/<int:task_id>/assignees", methods=["POST"])
@token_required
def set_assignees(task_id: int):
    """
    POST /api/tasks/<id>/assignees
    body: { "assignees": [5,7,9] }
    """
    company_id = _company_id()
    data = request.get_json(silent=True) or {}
    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    assignees = data.get("assignees") or []

    s = get_session()
    try:
        role = _role()
        user_id = _user_id()
        dep_id = _my_department_id(s, int(company_id), int(user_id))
        t = _get_task_with_acl(s, int(company_id), int(task_id), role, int(user_id), int(dep_id))

        if not t:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        s.query(TaskAssignee).filter_by(company_id=int(company_id), task_id=int(task_id)).delete()

        now = _now_ms()

        uniq_ids = []
        if isinstance(assignees, list):
            for uid in assignees:
                iu = _int_or_none(uid)
                if iu and iu > 0 and iu not in uniq_ids:
                    uniq_ids.append(iu)

        if uniq_ids:
            users = (
                s.query(User)
                 .filter(User.company_id == int(company_id))
                 .filter(User.id.in_(uniq_ids))
                 .all()
            )
            found_ids = {int(u.id) for u in users}

            for uid in uniq_ids:
                if uid in found_ids:
                    s.add(TaskAssignee(
                        company_id=int(company_id),
                        task_id=int(task_id),
                        user_id=int(uid),
                        created_ts_ms=now
                    ))

        t.updated_ts_ms = now
        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "SET_ASSIGNEES_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@tasks_bp.route("/<int:task_id>", methods=["DELETE"])
@token_required
def delete_task(task_id: int):

    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    s = get_session()
    try:
        role = _role()
        user_id = _user_id()
        dep_id = _my_department_id(s, int(company_id), int(user_id))
        t = _get_task_with_acl(s, int(company_id), int(task_id), role, int(user_id), int(dep_id))

        if not t:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        s.delete(t)
        s.commit()
        return jsonify({"ok": True, "message": "DELETED"}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "DELETE_FAILED", "error": str(e)}), 500
    finally:
        s.close()
