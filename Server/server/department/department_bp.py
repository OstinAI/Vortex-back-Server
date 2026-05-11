# -*- coding: utf-8 -*-
from flask import Blueprint, jsonify, request

from utils.security import token_required
from db.connection import get_session
from db.models import Department, User

def _user_id() -> int:
    payload = getattr(request, "user", None) or {}
    return int(payload.get("user_id") or 0)

def _is_head(session) -> bool:
    uid = _user_id()
    cid = _company_id_from_request()
    if uid <= 0 or cid <= 0:
        return False
    u = session.query(User).filter_by(id=uid, company_id=cid).first()
    return bool(getattr(u, "is_department_head", False))

def _my_department_id(session) -> int:
    uid = _user_id()
    cid = _company_id_from_request()
    if uid <= 0 or cid <= 0:
        return 0
    u = session.query(User).filter_by(id=uid, company_id=cid).first()
    return int(getattr(u, "department_id", 0) or 0)

departments_bp = Blueprint("departments", __name__)

def _company_id_from_request() -> int:
    payload = getattr(request, "user", None) or {}
    return int(payload.get("companyId") or payload.get("company_id") or 0)

def _role() -> str:
    payload = getattr(request, "user", None) or {}
    return str(payload.get("role") or "")

def _require_settings_access():
    if _role() not in ("Integrator", "Admin"):
        return jsonify({"ok": False, "message": "Access denied"}), 403
    return None

@departments_bp.route("/", methods=["GET"])
@token_required
def list_departments():
    company_id = _company_id_from_request()
    role = (_role() or "").strip()

    s = get_session()
    try:
        q = (
            s.query(Department)
            .filter(Department.company_id == company_id)
            .order_by(Department.name.asc())
        )

        # Админ/Интегратор (и при желании директор) видят всё
        if role in ("Integrator", "Admin"):
            rows = q.all()
        else:
            # Руководитель и обычные видят только свой отдел
            my_dep_id = _my_department_id(s)
            if my_dep_id > 0:
                rows = q.filter(Department.id == int(my_dep_id)).all()
            else:
                rows = []

        items = []
        for r in rows:
            items.append({
                "id": int(getattr(r, "id", 0) or 0),
                "name": getattr(r, "name", "") or "",
            })

        return jsonify({"ok": True, "company_id": company_id, "departments": items}), 200
    finally:
        s.close()


@departments_bp.route("/", methods=["POST"])
@token_required
def create_department():

    deny = _require_settings_access()
    if deny:
        return deny

    company_id = _company_id_from_request()

    data = request.get_json(silent=True) or {}
    name = (data.get("name", "") or "").strip()

    if not name:
        return jsonify({"ok": False, "message": "NAME_REQUIRED"}), 400

    s = get_session()
    try:
        exists = (
            s.query(Department)
            .filter(Department.company_id == company_id)
            .filter(Department.name == name)
            .first()
        )
        if exists:
            return jsonify({"ok": False, "message": "ALREADY_EXISTS"}), 400

        row = Department(company_id=company_id, name=name)
        s.add(row)
        s.commit()

        return jsonify({
            "ok": True,
            "company_id": company_id,
            "department": {"id": int(row.id), "name": row.name}
        }), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "CREATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()

@departments_bp.route("/<int:dept_id>", methods=["DELETE"])
@token_required
def delete_department(dept_id: int):

    deny = _require_settings_access()
    if deny:
        return deny

    company_id = _company_id_from_request()

    s = get_session()
    try:
        row = (
            s.query(Department)
            .filter(Department.company_id == company_id)
            .filter(Department.id == int(dept_id))
            .first()
        )
        if not row:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        # нельзя удалить если в отделе есть сотрудники
        cnt = (
            s.query(User)
            .filter(User.company_id == company_id)
            .filter(User.department_id == int(dept_id))
            .count()
        )
        if cnt > 0:
            return jsonify({"ok": False, "message": "DEPARTMENT_NOT_EMPTY", "employees_count": int(cnt)}), 400

        s.delete(row)
        s.commit()
        return jsonify({"ok": True, "message": "DELETED", "department_id": int(dept_id)}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "DELETE_FAILED", "error": str(e)}), 500
    finally:
        s.close()

@departments_bp.route("/<int:dept_id>", methods=["POST"])
@token_required
def update_department(dept_id: int):
    company_id = _company_id_from_request()
    role = (_role() or "").strip()

    data = request.get_json(silent=True) or {}
    name = (data.get("name", "") or "").strip()

    if not name:
        return jsonify({"ok": False, "message": "NAME_REQUIRED"}), 400

    s = get_session()
    try:
        row = (
            s.query(Department)
            .filter(Department.company_id == company_id)
            .filter(Department.id == int(dept_id))
            .first()
        )
        if not row:
            return jsonify({"ok": False, "message": "NOT_FOUND"}), 404

        # Integrator/Admin могут менять любой отдел
        if role in ("Integrator", "Admin"):
            pass
        else:
            # Руководитель может менять только СВОЙ отдел
            if not _is_head(s):
                return jsonify({"ok": False, "message": "Access denied"}), 403

            my_dep_id = _my_department_id(s)
            if int(my_dep_id) != int(dept_id):
                return jsonify({"ok": False, "message": "Access denied"}), 403

        # запрет дубля названий в компании
        exists = (
            s.query(Department)
            .filter(Department.company_id == company_id)
            .filter(Department.name == name)
            .filter(Department.id != int(dept_id))
            .first()
        )
        if exists:
            return jsonify({"ok": False, "message": "ALREADY_EXISTS"}), 400

        row.name = name
        s.commit()

        return jsonify({"ok": True, "department": {"id": int(row.id), "name": row.name}}), 200

    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "message": "UPDATE_FAILED", "error": str(e)}), 500
    finally:
        s.close()
