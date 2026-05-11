# -*- coding: utf-8 -*-
import os
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta

from db.connection import get_session
from db.models import User, Company
from utils.hashing import hash_password, make_client_hash
from utils.security import token_required
from server.mail.smtp_client import send_mail
from db.models import MailAccount
from utils.crypto import decrypt

employees_bp = Blueprint("employees", __name__)

# ===========================================
# 0) Хелперы
# ===========================================
def _role() -> str:
    p = getattr(request, "user", None) or {}
    return str(p.get("role") or "")

def _company_id() -> int:
    p = getattr(request, "user", None) or {}
    return int(p.get("companyId") or p.get("company_id") or 0)

def _user_id() -> int:
    p = getattr(request, "user", None) or {}
    return int(p.get("user_id") or 0)

def _is_head(session) -> bool:
    uid = _user_id()
    cid = _company_id()
    if uid <= 0 or cid <= 0:
        return False
    u = session.query(User).filter_by(id=uid, company_id=cid).first()
    return bool(getattr(u, "is_department_head", False))

def _my_department_id(session) -> int:
    uid = _user_id()
    cid = _company_id()
    if uid <= 0 or cid <= 0:
        return 0
    u = session.query(User).filter_by(id=uid, company_id=cid).first()
    return int(getattr(u, "department_id", 0) or 0)


# ===========================================
# 1) Создание сотрудника
# ===========================================
@employees_bp.route("/create", methods=["POST"])
@token_required
def create_employee():
    payload = request.user
    role_me = str(payload.get("role") or "")

    data = request.get_json(silent=True) or {}

    
    username = str(data.get("username") or "").strip()
    plain_password = str(data.get("password") or "").strip()
    role = data.get("role", "User")

    if not username or not plain_password:
        return jsonify({"status": "error", "message": "Missing fields"}), 400

    if len(username) < 4:
        return jsonify({"status": "error", "message": "Login must be at least 4 characters"}), 400

    if len(plain_password) < 4:
        return jsonify({"status": "error", "message": "Password must be at least 4 characters"}), 400

    temp_password = plain_password
    client_hash = make_client_hash(temp_password)


    session = get_session()
    try:
        # === ПРАВА: Admin/Integrator или руководитель отдела (только свой отдел) ===
        if role_me in ("Integrator", "Admin"):
            pass
        else:
            if not _is_head(session):
                return jsonify({"status": "error", "message": "Access denied"}), 403

            my_dep = _my_department_id(session)
            req_dep = int(data.get("department_id") or 0)

            if my_dep <= 0 or req_dep != my_dep:
                return jsonify({"status": "error", "message": "Access denied"}), 403

            req_role = str(data.get("role") or "User")
            if req_role in ("Integrator", "Admin"):
                return jsonify({"status": "error", "message": "Access denied"}), 403

        # Компания (ТОЛЬКО из токена)
        company_id = _company_id()
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404


        # 2. Хеширование PBKDF2
        password_hash, salt, iterations = hash_password(client_hash)

        # 3. Создание сотрудника
        user = User(
            username=username,
            role=role,
            company_id=company.id,
            password_hash=password_hash,
            salt=salt,
            iterations=iterations,

            department_id=data.get("department_id"),

            full_name=data.get("full_name"),
            phone=data.get("phone"),
            email=data.get("email"),
            birth_date=data.get("birth_date"),
            hire_date=data.get("hire_date"),
            position=data.get("position"),
            address=data.get("address"),
            notes=data.get("notes"),
            status=data.get("status", "active"),
            resume_path=data.get("resume_path"),

            first_login=False,
            temp_password_expire=None
        )

        # Руководитель отдела НЕ может создавать руководителя отдела (по желанию)
        if role_me not in ("Integrator", "Admin"):
            user.is_department_head = False

        session.add(user)
        session.commit()

        # 📧 отправка временного пароля с почты компании (если интегрирована)
        if user.email:
            acc = session.query(MailAccount).filter_by(company_id=company.id).first()
            if acc:
                try:
                    smtp_password = decrypt(acc.encrypted_password)

                    send_mail(
                        login=acc.email,               # почта компании
                        password=smtp_password,        # пароль из БД
                        to=user.email,
                        subject="Временный пароль (действует 3 суток)",
                        html_body=f"""
                            <p>Здравствуйте, {user.full_name or user.username}.</p>
                            <p>Ваш временный пароль: <b>{temp_password}</b></p>
                            <p>Срок действия: 3 суток.</p>
                        """
                    )
                except Exception as e:
                    print("MAIL SEND ERROR:", e)

        return jsonify({
            "status": "ok",
            "user_id": user.id,
            "temp_password": temp_password
        }), 200

    except Exception as e:
        session.rollback()
        import traceback
        print("\n\n🔥🔥🔥 ERROR IN /api/employees/create 🔥🔥🔥")
        traceback.print_exc()
        print("MESSAGE:", str(e))
        print("=============================================\n\n")
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        session.close()



# ===========================================
# 2) Получение списка сотрудников
# ===========================================
@employees_bp.route("/list", methods=["GET"])
@token_required
def list_employees():
    payload = request.user
    role = str(payload.get("role") or "")
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)

    session = get_session()
    try:
        q = session.query(User).filter_by(company_id=company_id)

        # Director видит всех, Observer видит всех
        # Руководитель видит свой отдел
        # Остальные — свой отдел
        if role in ("Integrator", "Admin", "Director", "Observer"):
            pass
        else:
            dep_id = _my_department_id(session)
            if dep_id > 0:
                q = q.filter(User.department_id == dep_id)
            else:
                # если отдел не задан — только себя
                uid = _user_id()
                q = q.filter(User.id == uid)

        users = q.all()

        result = []
        for u in users:
            result.append({
                "id": u.id,
                "username": u.username,
                "role": u.role,
                "full_name": u.full_name,
                "phone": u.phone,
                "email": u.email,
                "birth_date": u.birth_date,
                "hire_date": u.hire_date,
                "position": u.position,
                "address": u.address,
                "status": u.status,
                "notes": u.notes,
                "resume_path": u.resume_path,
                "avatar_path": u.avatar_path,
                "department_id": int(u.department_id or 0),
                "is_department_head": bool(u.is_department_head),
                "is_inventory_head": bool(getattr(u, "is_inventory_head", False)),

            })

        return jsonify({"status": "ok", "employees": result}), 200

    finally:
        session.close()

# ===========================================
# 3) Обновление сотрудника
# ===========================================
@employees_bp.route("/update", methods=["POST"])
@token_required
def update_employee():
    payload = request.user
    role_me = str(payload.get("role") or "")

    data = request.get_json(silent=True) or {}
    user_id = data.get("id")

    if not user_id:
        return jsonify({"status": "error", "message": "Missing id"}), 400


    session = get_session()
    try:
        company_id = _company_id()
        user = session.query(User).filter_by(id=user_id, company_id=company_id).first()

        if not user:
            return jsonify({"status": "error", "message": "User not found"}), 404

        my_id = _user_id()
        is_self = int(my_id or 0) == int(user.id or 0)

        # ==========================================
        # САМ СОТРУДНИК МОЖЕТ РЕДАКТИРОВАТЬ ТОЛЬКО СЕБЯ
        # ==========================================
        if is_self:
            if "full_name" in data:
                user.full_name = data["full_name"]
            if "phone" in data:
                user.phone = data["phone"]
            if "email" in data:
                user.email = data["email"]
            if "birth_date" in data:
                user.birth_date = data["birth_date"]
            if "address" in data:
                user.address = data["address"]
            if "notes" in data:
                user.notes = data["notes"]

            if "username" in data:
                new_username = str(data.get("username") or "").strip()
                if len(new_username) < 4:
                    return jsonify({"status": "error", "message": "Login must be at least 4 characters"}), 400

                exists = session.query(User).filter(
                    User.company_id == company_id,
                    User.username == new_username,
                    User.id != user.id
                ).first()

                if exists:
                    return jsonify({"status": "error", "message": "Username already exists"}), 400

                user.username = new_username

            if "password" in data:
                plain_password = str(data.get("password") or "").strip()
                if plain_password:
                    if len(plain_password) < 4:
                        return jsonify({"status": "error", "message": "Password must be at least 4 characters"}), 400

                    client_hash = make_client_hash(plain_password)
                    password_hash, salt, iterations = hash_password(client_hash)

                    user.password_hash = password_hash
                    user.salt = salt
                    user.iterations = iterations
                    user.first_login = False
                    user.temp_password_expire = None

            session.commit()
            return jsonify({"status": "ok"}), 200
        
        # === ПРАВА: Admin/Integrator или руководитель отдела (только свой отдел) ===
        if role_me in ("Integrator", "Admin"):
            pass
        else:
            if not _is_head(session):
                return jsonify({"status": "error", "message": "Access denied"}), 403

            my_dep = _my_department_id(session)
            if my_dep <= 0 or int(user.department_id or 0) != int(my_dep):
                return jsonify({"status": "error", "message": "Access denied"}), 403

            # запрет повышать роли
            if "role" in data and str(data.get("role") or "") in ("Integrator", "Admin", "WarehouseHead"):
                return jsonify({"status": "error", "message": "Access denied"}), 403


            # запрет переводить в другой отдел
            if "department_id" in data and int(data.get("department_id") or 0) != int(my_dep):
                return jsonify({"status": "error", "message": "Access denied"}), 403

            # запрет делать руководителем отдела
            if "is_department_head" in data and bool(data.get("is_department_head")):
                return jsonify({"status": "error", "message": "Access denied"}), 403

        if "role" in data:
            user.role = data["role"]
        if "full_name" in data:
            user.full_name = data["full_name"]
        if "phone" in data:
            user.phone = data["phone"]
        if "email" in data:
            user.email = data["email"]
        if "birth_date" in data:
            user.birth_date = data["birth_date"]
        if "hire_date" in data:
            user.hire_date = data["hire_date"]
        if "position" in data:
            user.position = data["position"]
        if "address" in data:
            user.address = data["address"]
        if "notes" in data:
            user.notes = data["notes"]
        if "status" in data:
            user.status = data["status"]
        if "resume_path" in data:
            user.resume_path = data["resume_path"]

        if "department_id" in data:
            user.department_id = data["department_id"]

        # Админ/Интегратор могут менять флаг руководителя
        if role_me in ("Integrator", "Admin"):
            if "is_department_head" in data:
                user.is_department_head = bool(data.get("is_department_head"))

        if role_me in ("Integrator", "Admin"):
            if "is_inventory_head" in data:
                user.is_inventory_head = bool(data.get("is_inventory_head"))


        session.commit()
        return jsonify({"status": "ok"}), 200

    finally:
        session.close()



# ===========================================
# 4) Удаление сотрудника
# ===========================================
@employees_bp.route("/delete", methods=["POST"])
@token_required
def delete_employee():
    payload = request.user
    role_me = str(payload.get("role") or "")

    data = request.get_json(silent=True) or {}
    user_id = data.get("id")

    if not user_id:
        return jsonify({"status": "error", "message": "Missing id"}), 400

    session = get_session()
    try:
        company_id = _company_id()
        user = session.query(User).filter_by(id=user_id, company_id=company_id).first()

        if not user:
            return jsonify({"status": "error", "message": "User not found"}), 404

        # === ПРАВА: Admin/Integrator или руководитель отдела (только свой отдел) ===
        if role_me in ("Integrator", "Admin"):
            pass
        else:
            if not _is_head(session):
                return jsonify({"status": "error", "message": "Access denied"}), 403

            my_dep = _my_department_id(session)
            if my_dep <= 0 or int(user.department_id or 0) != int(my_dep):
                return jsonify({"status": "error", "message": "Access denied"}), 403

            # запрет удалять себя
            if int(_user_id() or 0) == int(user.id):
                return jsonify({"status": "error", "message": "Access denied"}), 403

        # ======================================
        # 🔥 УДАЛЯЕМ ФОТО СОТРУДНИКА С ДИСКА
        # ======================================
        if user.avatar_path:
            fs_path = os.path.join("server", user.avatar_path.lstrip("/"))
            if os.path.exists(fs_path):
                try:
                    os.remove(fs_path)
                    print(f"Удалено фото сотрудника: {fs_path}")
                except Exception as e:
                    print(f"Не удалось удалить фото {fs_path}: {e}")

        # ======================================
        # 🔥 Удаляем сотрудника из базы
        # ======================================
        session.delete(user)
        session.commit()

        return jsonify({"status": "ok"}), 200

    finally:
        session.close()
