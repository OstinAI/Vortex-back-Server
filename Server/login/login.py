# -*- coding: utf-8 -*-
from flask import Blueprint, request, jsonify
import logging
import hashlib
import base64

from db.connection import get_session
from db.models import User, Company, CompanyProfileField
from utils.hashing import verify_password, hash_password
from utils.security import create_jwt, token_required

login_bp = Blueprint('auth', __name__)


@login_bp.route('/login', methods=['POST'])
def login():
    """
    POST /api/auth/login

    Входные данные (JSON):
    {
      "company": "БухПроф",
      "username": "admin",
      "password": "<sha256_base64>"
    }
    """
    data = request.get_json(silent=True) or {}

    company_name = data.get('company')
    username = data.get('username')
    client_hash = data.get('password')

    if not company_name or not username or not client_hash:
        return jsonify({
            'status': 'error',
            'message': 'Missing company, username or password'
        }), 400

    session = get_session()
    try:
        company = session.query(Company).filter(Company.name == company_name).first()
        if not company or not company.is_active:
            # Не раскрываем, что именно не так
            return jsonify({'status': 'error', 'message': 'Invalid login or password'}), 401

        user = session.query(User).filter(
            User.username == username,
            User.company_id == company.id
        ).first()

        if not user:
            return jsonify({'status': 'error', 'message': 'Invalid login or password'}), 401

                # Блокировка пользователя
        if (user.status or "").lower() != "active":
            return jsonify({'status': 'error', 'message': 'Account is blocked'}), 403

        # Проверяем PBKDF2(client_hash, salt, iterations)
        if not verify_password(client_hash, user.password_hash, user.salt, user.iterations):
            return jsonify({'status': 'error', 'message': 'Invalid login or password'}), 401

        token = create_jwt(user)

        return jsonify({
            'status': 'ok',
            'token': token,
            'role': user.role,
            'companyId': user.company_id
        }), 200

    except Exception as e:
        logging.exception('Login error')
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

    finally:
        session.close()


@login_bp.route('/check', methods=['GET'])
@token_required
def check():
    """
    GET /api/auth/check

    Заголовок:
      Authorization: Bearer <JWT>

    Возвращает payload токена, если всё ок.
    """
    payload = getattr(request, 'user', None)
    if not payload:
        return jsonify({'status': 'error', 'message': 'Token is invalid'}), 401

    return jsonify({
        'status': 'ok',
        'user': payload
    }), 200

@login_bp.route('/register_company', methods=['POST'])
def register_company():
    """
    POST /api/auth/register_company

    JSON:
    {
      "company": "MyCompany",
      "username": "owner",                 # это будет Admin
      "password": "<sha256_base64>",
      "password2": "<sha256_base64>",
      "fields": {
        "bin": "...",
        "phone": "...",
        "website": "...",
        "address": "...",
        "slogan": "...",
        "logo_filename": "logo.png",
        "logo_base64": "...."
      },
      "required_fields": ["bin","phone"]
    }

    Авто создаём второго пользователя:
      Integrator: login = "admin", password = "1234"
    """
    import hashlib
    import base64
    import os

    def _client_hash(plain: str) -> str:
        d = hashlib.sha256((plain or "").encode("utf-8")).digest()
        return base64.b64encode(d).decode("utf-8")

    data = request.get_json(silent=True) or {}

    company_name = (data.get("company") or "").strip()
    username = (data.get("username") or "").strip()
    client_hash = (data.get("password") or "").strip()
    client_hash2 = (data.get("password2") or "").strip()

    # кастомные поля
    fields = data.get("fields") or {}
    if not isinstance(fields, dict):
        return jsonify({"status": "error", "message": "fields must be an object/dict"}), 400

    required_fields = data.get("required_fields") or []
    if not isinstance(required_fields, list):
        return jsonify({"status": "error", "message": "required_fields must be an array"}), 400
    required_set = set(str(x) for x in required_fields)

    # проверки
    if not company_name or not username or not client_hash or not client_hash2:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    if client_hash != client_hash2:
        return jsonify({"status": "error", "message": "Passwords do not match"}), 400

    # проверка обязательных кастомных полей (если ты их передал)
    for k in required_set:
        v = fields.get(k)
        if v is None or str(v).strip() == "":
            return jsonify({"status": "error", "message": f"Required field missing: {k}"}), 400

    session = get_session()
    try:
        # компания уникальная по name
        exists = session.query(Company).filter(Company.name == company_name).first()
        if exists:
            return jsonify({"status": "error", "message": "Company already exists"}), 409

        # создаём компанию
        comp = Company(name=company_name, is_active=True)
        session.add(comp)
        session.flush()  # получить comp.id

        # ===== Admin: то что ввёл пользователь =====
        ph_admin, salt_admin, it_admin = hash_password(client_hash)
        u_admin = User(
            username=username,
            role="Admin",
            company_id=comp.id,
            password_hash=ph_admin,
            salt=salt_admin,
            iterations=it_admin,
            status="active",
            first_login=False
        )

        # ===== Integrator: всегда admin / 1234 =====
        integrator_username = "admin"
        integrator_client_hash = _client_hash("1234")
        ph_int, salt_int, it_int = hash_password(integrator_client_hash)
        u_integrator = User(
            username=integrator_username,
            role="Integrator",
            company_id=comp.id,
            password_hash=ph_int,
            salt=salt_int,
            iterations=it_int,
            status="active",
            first_login=False
        )

        session.add(u_admin)
        session.add(u_integrator)

        # ===== логотип: сохранить файл (если пришёл) =====
        logo_base64 = fields.get("logo_base64")
        logo_filename = (fields.get("logo_filename") or "logo.png").strip() or "logo.png"
        logo_path_public = ""

        if logo_base64:
            try:
                logo_bytes = base64.b64decode(logo_base64)

                folder = os.path.join("uploads", "company", str(comp.id))
                os.makedirs(folder, exist_ok=True)

                save_path = os.path.join(folder, logo_filename)
                with open(save_path, "wb") as f:
                    f.write(logo_bytes)

                # public path (если будешь отдавать статикой)
                logo_path_public = "/" + save_path.replace("\\", "/")

                # сохраняем в кастомные поля ключ "logo"
                session.add(CompanyProfileField(
                    company_id=comp.id,
                    key="logo",
                    value=logo_path_public,
                    required=False
                ))
            except Exception:
                pass  # если логотип битый — не валим регистрацию

        # ===== сохранить остальные кастомные поля =====
        for k, v in fields.items():
            key = (str(k) or "").strip()
            if not key:
                continue
            if key in ("logo_base64", "logo_filename"):
                continue

            val = "" if v is None else str(v)
            session.add(CompanyProfileField(
                company_id=comp.id,
                key=key,
                value=val,
                required=(key in required_set)
            ))

        session.commit()

        return jsonify({
            "status": "ok",
            "companyId": comp.id,
            "admin": {"username": u_admin.username, "role": u_admin.role},
            "integrator": {"username": u_integrator.username, "role": u_integrator.role, "password": "1234"},
            "logo_path": logo_path_public
        }), 200

    except Exception as e:
        session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()