# -*- coding: utf-8 -*-
from flask import Blueprint, request, jsonify
import logging
import hashlib
import base64
import os
import threading
import time

from db.connection import get_session
from db.models import User, Company, CompanyProfileField
from utils.hashing import verify_password, hash_password
from utils.security import create_jwt, token_required

login_bp = Blueprint('auth', __name__)


def _async_import_company(company_id):
    """Фоновый импорт компании в CRM"""
    try:
        time.sleep(2)
        from server.crm.Automator.auto_import import import_company_to_crm, is_automation_enabled, load_automation_settings
        
        load_automation_settings()
        
        if is_automation_enabled():
            print(f'[REGISTER] Фоновый импорт компании ID={company_id}')
            result = import_company_to_crm(company_id)
            print(f'[REGISTER] Результат импорта: {result}')
        else:
            print(f'[REGISTER] Автоматизация отключена, импорт не выполнен')
    except Exception as e:
        print(f'[REGISTER] Ошибка фонового импорта: {e}')
        import traceback
        traceback.print_exc()


@login_bp.route('/login', methods=['POST'])
def login():
    """POST /api/auth/login"""
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
            return jsonify({'status': 'error', 'message': 'Invalid login or password'}), 401

        user = session.query(User).filter(
            User.username == username,
            User.company_id == company.id
        ).first()

        if not user:
            return jsonify({'status': 'error', 'message': 'Invalid login or password'}), 401

        if (user.status or "").lower() != "active":
            return jsonify({'status': 'error', 'message': 'Account is blocked'}), 403

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
    payload = getattr(request, 'user', None)
    if not payload:
        return jsonify({'status': 'error', 'message': 'Token is invalid'}), 401

    return jsonify({
        'status': 'ok',
        'user': payload
    }), 200


@login_bp.route('/register_company', methods=['POST'])
def register_company():
    """POST /api/auth/register_company"""
    def _client_hash(plain: str) -> str:
        d = hashlib.sha256((plain or "").encode("utf-8")).digest()
        return base64.b64encode(d).decode("utf-8")

    data = request.get_json(silent=True) or {}

    company_name = (data.get("company") or "").strip()
    username = (data.get("username") or "").strip()
    client_hash = (data.get("password") or "").strip()
    client_hash2 = (data.get("password2") or "").strip()

    fields = data.get("fields") or {}
    if not isinstance(fields, dict):
        return jsonify({"status": "error", "message": "fields must be an object/dict"}), 400

    required_fields = data.get("required_fields") or []
    if not isinstance(required_fields, list):
        return jsonify({"status": "error", "message": "required_fields must be an array"}), 400
    required_set = set(str(x) for x in required_fields)

    if not company_name or not username or not client_hash or not client_hash2:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    if client_hash != client_hash2:
        return jsonify({"status": "error", "message": "Passwords do not match"}), 400

    for k in required_set:
        v = fields.get(k)
        if v is None or str(v).strip() == "":
            return jsonify({"status": "error", "message": f"Required field missing: {k}"}), 400

    session = get_session()
    try:
        exists = session.query(Company).filter(Company.name == company_name).first()
        if exists:
            return jsonify({"status": "error", "message": "Company already exists"}), 409

        # ============================================================
        # 🔥 СОЗДАЕМ КОМПАНИЮ СО ВСЕМИ ПОЛЯМИ
        # ============================================================
        comp = Company(
            name=company_name,
            is_active=True,
            # Извлекаем поля из fields
            bin=fields.get("bin") or fields.get("БИН") or "",
            phone=fields.get("phone") or fields.get("Телефон") or "",
            address=fields.get("address") or fields.get("Адрес") or "",
            website=fields.get("website") or fields.get("Веб-сайт") or "",
            slogan=fields.get("slogan") or fields.get("Слоган") or "",
        )
        session.add(comp)
        session.flush()

        company_id = comp.id
        company_name_saved = company_name
        
        # ✅ Сохраняем данные компании ДО закрытия сессии
        company_data = {
            "name": company_name_saved,
            "bin": comp.bin,
            "phone": comp.phone,
            "address": comp.address,
            "website": comp.website,
            "slogan": comp.slogan,
        }

        # Admin
        ph_admin, salt_admin, it_admin = hash_password(client_hash)
        u_admin = User(
            username=username,
            role="Admin",
            company_id=company_id,
            password_hash=ph_admin,
            salt=salt_admin,
            iterations=it_admin,
            status="active",
            first_login=False,
            # Извлекаем данные администратора из fields
            full_name=fields.get("full_name") or fields.get("ФИО") or fields.get("Имя") or "",
            phone=fields.get("admin_phone") or fields.get("Телефон администратора") or "",
            email=fields.get("email") or fields.get("Email") or "",
        )
        session.add(u_admin)
        session.flush()
        
        # ✅ Сохраняем данные администратора ДО закрытия сессии
        admin_data = {
            "username": u_admin.username,
            "role": u_admin.role,
            "full_name": u_admin.full_name,
            "email": u_admin.email,
        }

        # Integrator
        integrator_username = "admin"
        integrator_client_hash = _client_hash("1234")
        ph_int, salt_int, it_int = hash_password(integrator_client_hash)
        u_integrator = User(
            username=integrator_username,
            role="Integrator",
            company_id=company_id,
            password_hash=ph_int,
            salt=salt_int,
            iterations=it_int,
            status="active",
            first_login=False
        )
        session.add(u_integrator)
        session.flush()

        integrator_username_saved = u_integrator.username
        integrator_role = u_integrator.role
        integrator_password = "1234"

        # Логотип
        logo_base64 = fields.get("logo_base64")
        logo_filename = (fields.get("logo_filename") or "logo.png").strip() or "logo.png"
        logo_path_public = ""

        if logo_base64:
            try:
                logo_bytes = base64.b64decode(logo_base64)
                folder = os.path.join("uploads", "company", str(company_id))
                os.makedirs(folder, exist_ok=True)
                save_path = os.path.join(folder, logo_filename)
                with open(save_path, "wb") as f:
                    f.write(logo_bytes)
                logo_path_public = "/" + save_path.replace("\\", "/")

                session.add(CompanyProfileField(
                    company_id=company_id,
                    key="logo",
                    value=logo_path_public,
                    required=False
                ))
            except Exception:
                pass

        # Кастомные поля (сохраняем все остальные)
        # Исключаем поля, которые уже сохранили
        exclude_keys = {
            "bin", "БИН", "phone", "Телефон", "address", "Адрес",
            "website", "Веб-сайт", "slogan", "Слоган",
            "full_name", "ФИО", "Имя", "admin_phone", "Телефон администратора",
            "email", "Email", "logo_base64", "logo_filename"
        }
        
        for k, v in fields.items():
            key = (str(k) or "").strip()
            if not key:
                continue
            if key in exclude_keys:
                continue
            if key in ("logo_base64", "logo_filename"):
                continue
            val = "" if v is None else str(v)
            session.add(CompanyProfileField(
                company_id=company_id,
                key=key,
                value=val,
                required=(key in required_set)
            ))

        session.commit()
        session.close()

        # 🔥 АВТОМАТИЧЕСКИЙ ИМПОРТ В CRM (в фоновом потоке)
        try:
            thread = threading.Thread(target=_async_import_company, args=(company_id,))
            thread.daemon = True
            thread.start()
            print(f'[REGISTER] Запущен фоновый импорт компании "{company_name_saved}" (ID={company_id})')
            print(f'[REGISTER] Данные компании: БИН={company_data["bin"]}, Телефон={company_data["phone"]}, Адрес={company_data["address"]}')
        except Exception as e:
            print(f'[REGISTER] Ошибка запуска фонового импорта: {e}')
            import traceback
            traceback.print_exc()

        # ✅ Используем сохраненные данные, а не объекты после закрытия сессии
        return jsonify({
            "status": "ok",
            "companyId": company_id,
            "company": company_data,
            "admin": admin_data,
            "integrator": {
                "username": integrator_username_saved, 
                "role": integrator_role, 
                "password": integrator_password
            },
            "logo_path": logo_path_public
        }), 200

    except Exception as e:
        session.rollback()
        session.close()
        print(f'[REGISTER] Ошибка регистрации: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500