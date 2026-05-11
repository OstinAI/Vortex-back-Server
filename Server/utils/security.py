# -*- coding: utf-8 -*-
import datetime
from functools import wraps

import jwt
from flask import current_app, request, jsonify
from db.connection import get_session
from db.models import User, Company



def create_jwt(user) -> str:
    """
    Создание JWT-токена для пользователя.
    Payload:
      - user_id
      - companyId
      - role
      - exp (48 часов)
      - iat
    """
    now = datetime.datetime.utcnow()
    payload = {
        'user_id': user.id,
        'companyId': user.company_id,   # ⭐ ПРАВИЛЬНОЕ НАЗВАНИЕ
        'role': user.role,
        'iat': now,
        'exp': now + datetime.timedelta(hours=48),
    }

    token = jwt.encode(
        payload,
        current_app.config['SECRET_KEY'],
        algorithm=current_app.config.get('JWT_ALGORITHM', 'HS256')
    )
    return token


def decode_jwt(token: str):
    """
    Декодирование и проверка токена.
    Возвращает payload или None, если токен невалиден/истёк.
    """
    try:
        payload = jwt.decode(
            token,
            current_app.config['SECRET_KEY'],
            algorithms=[current_app.config.get('JWT_ALGORITHM', 'HS256')]
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def token_required(f):
    """
    Декоратор для маршрутов, где нужна авторизация по Bearer-токену.
    + Проверка блокировки компании и пользователя в БД.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'status': 'error', 'message': 'Token is missing'}), 401

        token = auth_header.split(' ', 1)[1].strip()
        payload = decode_jwt(token)
        if not payload:
            return jsonify({'status': 'error', 'message': 'Token is invalid or expired'}), 401

        # совместимость ключей
        if "companyId" in payload and "company_id" not in payload:
            payload["company_id"] = payload["companyId"]

        user_id = payload.get("user_id")
        company_id = payload.get("company_id") or payload.get("companyId")

        if not user_id or not company_id:
            return jsonify({'status': 'error', 'message': 'Token is invalid or expired'}), 401

        # Проверка блокировки в БД
        session = get_session()
        try:
            company = session.query(Company).filter_by(id=int(company_id)).first()
            if (not company) or (not company.is_active):
                return jsonify({'status': 'error', 'message': 'Company is blocked'}), 403

            user = session.query(User).filter_by(id=int(user_id), company_id=int(company_id)).first()
            if not user:
                return jsonify({'status': 'error', 'message': 'Account is blocked'}), 403

            if (user.status or "").lower() != "active":
                return jsonify({'status': 'error', 'message': 'Account is blocked'}), 403

            # можно обновить роль из БД (если роль поменяли после выдачи токена)
            payload["role"] = user.role

        except Exception:
            return jsonify({'status': 'error', 'message': 'Token is invalid or expired'}), 401
        finally:
            session.close()

        request.user = payload
        return f(*args, **kwargs)

    return decorated
