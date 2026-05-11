# -*- coding: utf-8 -*-
import time
from flask import Blueprint, jsonify, request
from sqlalchemy import or_
from sqlalchemy import case

from utils.security import token_required
from db.connection import get_session
from db.models import Note, NoteAssignee, Client, User, Department, ClientAssignment

notes_bp = Blueprint("notes", __name__)

def _now_ms() -> int:
    return int(time.time() * 1000)

def _payload():
    return getattr(request, "user", None) or {}

def _company_id() -> int:
    p = _payload()
    return int(p.get("company_id") or p.get("companyId") or 0)

def _user_id() -> int:
    p = _payload()
    return int(p.get("user_id") or 0)

def _role() -> str:
    p = _payload()
    return str(p.get("role") or "")

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
    role_norm = (role or "").strip().lower()

    # директор/президент/админ/интегратор видят всё
    if role_norm in ("admin", "integrator", "director", "president"):
        return q

    # проверяем пользователя
    user = (
        s.query(User)
         .filter(User.company_id == int(company_id), User.id == int(user_id))
         .first()
    )
    if not user:
        return q.filter(Note.id == -1)

    # руководитель отдела (по флагу)
    if getattr(user, "is_department_head", False) and getattr(user, "department_id", None):
        dep_id = int(user.department_id)

        return q.filter(
            or_(
                # 1) заметка явно на отдел
                Note.department_id == dep_id,

                # 2) создатель из этого отдела
                Note.created_by_user_id.in_(
                    s.query(User.id)
                     .filter(User.company_id == int(company_id))
                     .filter(User.department_id == dep_id)
                ),

                # 3) назначенные из этого отдела
                Note.id.in_(
                    s.query(NoteAssignee.note_id)
                     .join(User, User.id == NoteAssignee.user_id)
                     .filter(NoteAssignee.company_id == int(company_id))
                     .filter(User.department_id == dep_id)
                )
            )
        )

    # менеджер: свои заметки (создал / назначены / по его клиентам)
    return q.filter(
        or_(
            Note.created_by_user_id == int(user_id),

            Note.id.in_(
                s.query(NoteAssignee.note_id)
                 .filter(NoteAssignee.company_id == int(company_id))
                 .filter(NoteAssignee.user_id == int(user_id))
            ),

            Note.client_id.in_(
                s.query(ClientAssignment.client_id)
                 .filter(ClientAssignment.company_id == int(company_id))
                 .filter(ClientAssignment.user_id == int(user_id))
            )
        )
    )

def _get_note_with_acl(s, company_id: int, note_id: int, role: str, user_id: int, dep_id: int):
    q = s.query(Note).filter(Note.company_id == int(company_id)).filter(Note.id == int(note_id))
    q = _apply_acl_query(q, s, int(company_id), role, int(user_id), int(dep_id))
    return q.first()


@notes_bp.route("/", methods=["POST"])
@token_required
def create_note():

    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    """
    POST /api/notes/
    body:
    {
      "client_id": 10,
      "description": "Заметка...",
      "department_id": 3,
      "assignees": [5,7,9]
    }
    """
    company_id = _company_id()
    creator_id = _user_id()
    data = request.get_json(silent=True) or {}

    client_id = int(data.get("client_id") or 0)
    description = (data.get("description") or "").strip()
    department_id = _int_or_none(data.get("department_id"))
    assignees = data.get("assignees") or []

    if company_id <= 0:
        return jsonify({"ok": False, "message": "INVALID_COMPANY"}), 400
    if client_id <= 0:
        return jsonify({"ok": False, "message": "CLIENT_ID_REQUIRED"}), 400
    if not description:
        return jsonify({"ok": False, "message": "DESCRIPTION_REQUIRED"}), 400

    s = get_session()
    try:
        c = s.query(Client).filter_by(id=int(client_id), company_id=int(company_id)).first()
        if not c:
            return jsonify({"ok": False, "message": "CLIENT_NOT_FOUND"}), 404

        if department_id:
            d = s.query(Department).filter_by(id=int(department_id), company_id=int(company_id)).first()
            if not d:
                return jsonify({"ok": False, "message": "DEPARTMENT_NOT_FOUND"}), 404

        now = _now_ms()

        row = Note(
            company_id=int(company_id),
            client_id=int(client_id),
            department_id=int(department_id) if department_id else None,
            created_by_user_id=int(creator_id) if creator_id else None,
            description=description,
            type=data.get("type", "note"),
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
                        s.add(NoteAssignee(
                            company_id=int(company_id),
                            note_id=int(row.id),
                            user_id=int(uid),
                            created_ts_ms=now
                        ))

        s.commit()
        return jsonify({"ok": True, "note_id": int(row.id)}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@notes_bp.route("/", methods=["GET"])
@token_required
def list_notes():
    """
    GET /api/notes/?client_id=10&assigned_user_id=5&department_id=3&limit=200
    """
    company_id = _company_id()
    role = _role()
    user_id = _user_id()

    client_id = _int_or_none(request.args.get("client_id"))
    assigned_user_id = _int_or_none(request.args.get("assigned_user_id"))
    department_id = _int_or_none(request.args.get("department_id"))
    limit = _int_or_none(request.args.get("limit")) or 200
    if limit < 1: limit = 1
    if limit > 500: limit = 500

    s = get_session()
    try:
        q = s.query(Note).filter(Note.company_id == int(company_id))

        dep_id = _my_department_id(s, int(company_id), int(user_id))
        q = _apply_acl_query(q, s, int(company_id), role, int(user_id), int(dep_id))

        if client_id:
            q = q.filter(Note.client_id == int(client_id))

        if department_id:
            q = q.filter(Note.department_id == int(department_id))

        if assigned_user_id:
            q = q.filter(
                Note.id.in_(
                    s.query(NoteAssignee.note_id)
                     .filter(NoteAssignee.company_id == int(company_id))
                     .filter(NoteAssignee.user_id == int(assigned_user_id))
                )
            )

       
        rows = (
            q.order_by(
                case((Note.type == "note", 0), else_=1),   # сначала желтая заметка
                Note.created_ts_ms.desc()                  # потом по времени
            )
            .limit(int(limit))
            .all()
        )

        items = []
        for n in rows:
            a_rows = (
                s.query(NoteAssignee)
                .filter_by(company_id=int(company_id), note_id=int(n.id))
                .all()
            )
            a_ids = [int(a.user_id) for a in a_rows]

            items.append({
                "id": int(n.id),
                "client_id": int(n.client_id),
                "department_id": int(n.department_id) if n.department_id else None,
                "description": n.description or "",
                "type": (getattr(n, "type", None) or "note"),
                "assignees": a_ids,
                "created_ts_ms": int(n.created_ts_ms or 0),
                "updated_ts_ms": int(n.updated_ts_ms or 0),
            })

        return jsonify({"ok": True, "notes": items}), 200
    finally:
        s.close()


@notes_bp.route("/<int:note_id>", methods=["GET"])
@token_required
def get_note(note_id: int):
    company_id = _company_id()
    s = get_session()
    try:
        role = _role()
        user_id = _user_id()
        dep_id = _my_department_id(s, int(company_id), int(user_id))
        n = _get_note_with_acl(s, int(company_id), int(note_id), role, int(user_id), int(dep_id))

        if not n:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        a_rows = s.query(NoteAssignee).filter_by(company_id=int(company_id), note_id=int(n.id)).all()
        a_ids = [int(a.user_id) for a in a_rows]

        return jsonify({
            "ok": True,
            "note": {
                "id": int(n.id),
                "client_id": int(n.client_id),
                "department_id": int(n.department_id) if n.department_id else None,
                "description": n.description or "",
                "assignees": a_ids,
                "created_ts_ms": int(n.created_ts_ms or 0),
                "updated_ts_ms": int(n.updated_ts_ms or 0),
            }
        }), 200
    finally:
        s.close()


@notes_bp.route("/<int:note_id>", methods=["POST"])
@token_required
def update_note(note_id: int):

    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    """
    POST /api/notes/<id>
    можно менять: description, department_id
    """
    company_id = _company_id()
    data = request.get_json(silent=True) or {}

    s = get_session()
    try:
        role = _role()
        user_id = _user_id()
        dep_id = _my_department_id(s, int(company_id), int(user_id))
        n = _get_note_with_acl(s, int(company_id), int(note_id), role, int(user_id), int(dep_id))

        if not n:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        if "description" in data:
            desc = (data.get("description") or "").strip()
            if not desc:
                return jsonify({"ok": False, "message": "DESCRIPTION_REQUIRED"}), 400
            n.description = desc

        if "department_id" in data:
            dep = _int_or_none(data.get("department_id"))
            if dep:
                d = s.query(Department).filter_by(id=int(dep), company_id=int(company_id)).first()
                if not d:
                    return jsonify({"ok": False, "message": "DEPARTMENT_NOT_FOUND"}), 404
                n.department_id = int(dep)
            else:
                n.department_id = None

        n.updated_ts_ms = _now_ms()
        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPDATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@notes_bp.route("/<int:note_id>/assignees", methods=["POST"])
@token_required
def set_note_assignees(note_id: int):

    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    """
    POST /api/notes/<id>/assignees
    body: { "assignees": [5,7,9] }
    """
    company_id = _company_id()
    data = request.get_json(silent=True) or {}
    assignees = data.get("assignees") or []

    s = get_session()
    try:
        role = _role()
        user_id = _user_id()
        dep_id = _my_department_id(s, int(company_id), int(user_id))
        n = _get_note_with_acl(s, int(company_id), int(note_id), role, int(user_id), int(dep_id))

        if not n:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        s.query(NoteAssignee).filter_by(company_id=int(company_id), note_id=int(note_id)).delete()

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
                    s.add(NoteAssignee(
                        company_id=int(company_id),
                        note_id=int(note_id),
                        user_id=int(uid),
                        created_ts_ms=now
                    ))

        n.updated_ts_ms = now
        s.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "SET_ASSIGNEES_FAILED", "error": str(e)}), 500
    finally:
        s.close()


@notes_bp.route("/<int:note_id>", methods=["DELETE"])
@token_required
def delete_note(note_id: int):

    if (_role() or "").strip().lower() == "observer":
        return jsonify({"ok": False, "message": "READ_ONLY"}), 403

    company_id = _company_id()
    s = get_session()
    try:
        role = _role()
        user_id = _user_id()
        dep_id = _my_department_id(s, int(company_id), int(user_id))
        n = _get_note_with_acl(s, int(company_id), int(note_id), role, int(user_id), int(dep_id))

        if not n:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        s.delete(n)
        s.commit()
        return jsonify({"ok": True, "message": "DELETED"}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "DELETE_FAILED", "error": str(e)}), 500
    finally:
        s.close()


