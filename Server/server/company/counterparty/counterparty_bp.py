# -*- coding: utf-8 -*-
"""
Модуль управления контрагентами компании
Путь: server/company/counterparty/counterparty_bp.py
"""

from flask import Blueprint, request, jsonify
from utils.security import token_required
from db.connection import get_session
from db.models import Company, User, StoredFile
from utils.crypto import encrypt, decrypt
import re
import time
import hashlib
from sqlalchemy import or_, and_

# Импортируем модели из db.models (они должны быть там добавлены)
from db.models import Counterparty, CounterpartyCustomField, CounterpartyPaymentField

counterparty_bp = Blueprint("counterparty", __name__, url_prefix="/api/company/counterparty")

# ============================================
# НАСТРОЙКИ ШИФРОВАНИЯ
# ============================================

ENCRYPTED_FIELDS = [
    'president', 'organization', 'phone', 'email', 'bin', 'account', 'holder',
    'contact_phone', 'contact_email', 'address', 'website', 'notes'
]

def should_encrypt(key: str) -> bool:
    for field in ENCRYPTED_FIELDS:
        if field in key.lower():
            return True
    return False

def encrypt_field_value(key: str, value: str) -> str:
    if not value or not should_encrypt(key):
        return value
    try:
        return encrypt(value)
    except Exception as e:
        print(f"[WARN] Ошибка шифрования {key}: {e}")
        return value

def decrypt_field_value(key: str, value: str) -> str:
    if not value:
        return value
    if not should_encrypt(key):
        return value
    try:
        if value.startswith('gAAAAA'):
            return decrypt(value)
        return value
    except Exception as e:
        print(f"[ERROR] Ошибка дешифрования {key}: {e}")
        return value


# ============================================
# API: ПОЛУЧИТЬ ВСЕХ КОНТРАГЕНТОВ
# ============================================
@counterparty_bp.route("/list", methods=["GET"])
@token_required
def get_counterparties():
    """Получить список всех контрагентов"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    session = get_session()
    try:
        counterparties = session.query(Counterparty).filter_by(
            company_id=company_id,
            is_active=True
        ).order_by(Counterparty.created_ts_ms.desc()).all()
        
        result = []
        for cp in counterparties:
            # Получаем кастомные поля
            custom_fields = session.query(CounterpartyCustomField).filter_by(
                counterparty_id=cp.id,
                company_id=company_id
            ).all()
            
            # Получаем платежные реквизиты
            payment_fields = session.query(CounterpartyPaymentField).filter_by(
                counterparty_id=cp.id,
                company_id=company_id
            ).all()
            
            # Формируем данные для ответа
            result.append({
                "id": cp.id,
                "president": decrypt_field_value('president', cp.president or ""),
                "organization": decrypt_field_value('organization', cp.organization or ""),
                "phone": decrypt_field_value('phone', cp.phone or ""),
                "email": decrypt_field_value('email', cp.email or ""),
                "type": cp.type or "",
                "bin": decrypt_field_value('bin', cp.bin or ""),
                "address": decrypt_field_value('address', cp.address or ""),
                "website": decrypt_field_value('website', cp.website or ""),
                "notes": decrypt_field_value('notes', cp.notes or ""),
                "is_active": cp.is_active,
                "created_ts_ms": cp.created_ts_ms,
                "updated_ts_ms": cp.updated_ts_ms,
                "custom_fields": [
                    {
                        "key": f.key,
                        "value": decrypt_field_value(f.key, f.value),
                        "required": f.required
                    }
                    for f in custom_fields
                ],
                "payment_fields": [
                    {
                        "key": f.key,
                        "value": decrypt_field_value(f.key, f.value),
                        "required": f.required
                    }
                    for f in payment_fields
                ]
            })
        
        return jsonify({
            "status": "ok",
            "data": result,
            "total": len(result)
        }), 200
        
    except Exception as e:
        print(f"[ERROR] Ошибка получения контрагентов: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: ПОЛУЧИТЬ ОДНОГО КОНТРАГЕНТА
# ============================================
@counterparty_bp.route("/<int:counterparty_id>", methods=["GET"])
@token_required
def get_counterparty(counterparty_id):
    """Получить данные одного контрагента"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    session = get_session()
    try:
        cp = session.query(Counterparty).filter_by(
            id=counterparty_id,
            company_id=company_id
        ).first()
        
        if not cp:
            return jsonify({"status": "error", "message": "Counterparty not found"}), 404
        
        custom_fields = session.query(CounterpartyCustomField).filter_by(
            counterparty_id=cp.id,
            company_id=company_id
        ).all()
        
        payment_fields = session.query(CounterpartyPaymentField).filter_by(
            counterparty_id=cp.id,
            company_id=company_id
        ).all()
        
        result = {
            "id": cp.id,
            "president": decrypt_field_value('president', cp.president or ""),
            "organization": decrypt_field_value('organization', cp.organization or ""),
            "phone": decrypt_field_value('phone', cp.phone or ""),
            "email": decrypt_field_value('email', cp.email or ""),
            "type": cp.type or "",
            "bin": decrypt_field_value('bin', cp.bin or ""),
            "address": decrypt_field_value('address', cp.address or ""),
            "website": decrypt_field_value('website', cp.website or ""),
            "notes": decrypt_field_value('notes', cp.notes or ""),
            "is_active": cp.is_active,
            "created_ts_ms": cp.created_ts_ms,
            "updated_ts_ms": cp.updated_ts_ms,
            "custom_fields": [
                {
                    "key": f.key,
                    "value": decrypt_field_value(f.key, f.value),
                    "required": f.required
                }
                for f in custom_fields
            ],
            "payment_fields": [
                {
                    "key": f.key,
                    "value": decrypt_field_value(f.key, f.value),
                    "required": f.required
                }
                for f in payment_fields
            ]
        }
        
        return jsonify({"status": "ok", "data": result}), 200
        
    except Exception as e:
        print(f"[ERROR] Ошибка получения контрагента: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: СОЗДАТЬ КОНТРАГЕНТА
# ============================================
@counterparty_bp.route("/create", methods=["POST"])
@token_required
def create_counterparty():
    """Создать нового контрагента"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    data = request.get_json(silent=True) or {}
    
    # Обязательные поля
    president = (data.get("president") or "").strip()
    organization = (data.get("organization") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    type_val = (data.get("type") or "other").strip()
    
    if not president or not organization or not phone or not email:
        return jsonify({
            "status": "error",
            "message": "Обязательные поля: президент, организация, телефон, email"
        }), 400
    
    session = get_session()
    try:
        # Проверяем компанию
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404
        
        # Создаем контрагента
        now = int(time.time() * 1000)
        
        cp = Counterparty(
            company_id=company_id,
            president=encrypt_field_value('president', president),
            organization=encrypt_field_value('organization', organization),
            phone=encrypt_field_value('phone', phone),
            email=encrypt_field_value('email', email),
            type=type_val,
            bin=encrypt_field_value('bin', (data.get("bin") or "").strip()),
            address=encrypt_field_value('address', (data.get("address") or "").strip()),
            website=encrypt_field_value('website', (data.get("website") or "").strip()),
            notes=encrypt_field_value('notes', (data.get("notes") or "").strip()),
            is_active=True,
            created_ts_ms=now,
            updated_ts_ms=now
        )
        session.add(cp)
        session.flush()
        
        # Сохраняем кастомные поля
        custom_fields = data.get("custom_fields") or []
        for field in custom_fields:
            key = (field.get("key") or "").strip()
            value = (field.get("value") or "").strip()
            if key:
                cf = CounterpartyCustomField(
                    counterparty_id=cp.id,
                    company_id=company_id,
                    key=key,
                    value=encrypt_field_value(key, value),
                    required=field.get("required", False)
                )
                session.add(cf)
        
        # Сохраняем платежные реквизиты
        payment_fields = data.get("payment_fields") or []
        for field in payment_fields:
            key = (field.get("key") or "").strip()
            value = (field.get("value") or "").strip()
            if key:
                pf = CounterpartyPaymentField(
                    counterparty_id=cp.id,
                    company_id=company_id,
                    key=key,
                    value=encrypt_field_value(key, value),
                    required=field.get("required", False)
                )
                session.add(pf)
        
        session.commit()
        
        return jsonify({
            "status": "ok",
            "message": "Контрагент создан",
            "data": {"id": cp.id}
        }), 200
        
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка создания контрагента: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: ОБНОВИТЬ КОНТРАГЕНТА
# ============================================
@counterparty_bp.route("/update/<int:counterparty_id>", methods=["POST"])
@token_required
def update_counterparty(counterparty_id):
    """Обновить данные контрагента"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    data = request.get_json(silent=True) or {}
    
    session = get_session()
    try:
        cp = session.query(Counterparty).filter_by(
            id=counterparty_id,
            company_id=company_id
        ).first()
        
        if not cp:
            return jsonify({"status": "error", "message": "Counterparty not found"}), 404
        
        now = int(time.time() * 1000)
        
        # Обновляем основные поля
        if "president" in data:
            cp.president = encrypt_field_value('president', (data["president"] or "").strip())
        if "organization" in data:
            cp.organization = encrypt_field_value('organization', (data["organization"] or "").strip())
        if "phone" in data:
            cp.phone = encrypt_field_value('phone', (data["phone"] or "").strip())
        if "email" in data:
            cp.email = encrypt_field_value('email', (data["email"] or "").strip())
        if "type" in data:
            cp.type = (data["type"] or "").strip()
        if "bin" in data:
            cp.bin = encrypt_field_value('bin', (data["bin"] or "").strip())
        if "address" in data:
            cp.address = encrypt_field_value('address', (data["address"] or "").strip())
        if "website" in data:
            cp.website = encrypt_field_value('website', (data["website"] or "").strip())
        if "notes" in data:
            cp.notes = encrypt_field_value('notes', (data["notes"] or "").strip())
        if "is_active" in data:
            cp.is_active = bool(data["is_active"])
        
        cp.updated_ts_ms = now
        
        # Обновляем кастомные поля (удаляем старые и создаем новые)
        if "custom_fields" in data:
            # Удаляем старые
            session.query(CounterpartyCustomField).filter_by(
                counterparty_id=cp.id,
                company_id=company_id
            ).delete()
            
            # Создаем новые
            for field in data["custom_fields"]:
                key = (field.get("key") or "").strip()
                value = (field.get("value") or "").strip()
                if key:
                    cf = CounterpartyCustomField(
                        counterparty_id=cp.id,
                        company_id=company_id,
                        key=key,
                        value=encrypt_field_value(key, value),
                        required=field.get("required", False)
                    )
                    session.add(cf)
        
        # Обновляем платежные реквизиты
        if "payment_fields" in data:
            # Удаляем старые
            session.query(CounterpartyPaymentField).filter_by(
                counterparty_id=cp.id,
                company_id=company_id
            ).delete()
            
            # Создаем новые
            for field in data["payment_fields"]:
                key = (field.get("key") or "").strip()
                value = (field.get("value") or "").strip()
                if key:
                    pf = CounterpartyPaymentField(
                        counterparty_id=cp.id,
                        company_id=company_id,
                        key=key,
                        value=encrypt_field_value(key, value),
                        required=field.get("required", False)
                    )
                    session.add(pf)
        
        session.commit()
        
        return jsonify({
            "status": "ok",
            "message": "Контрагент обновлен"
        }), 200
        
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка обновления контрагента: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: УДАЛИТЬ КОНТРАГЕНТА
# ============================================
@counterparty_bp.route("/delete/<int:counterparty_id>", methods=["DELETE"])
@token_required
def delete_counterparty(counterparty_id):
    """Удалить контрагента (мягкое удаление)"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    session = get_session()
    try:
        cp = session.query(Counterparty).filter_by(
            id=counterparty_id,
            company_id=company_id
        ).first()
        
        if not cp:
            return jsonify({"status": "error", "message": "Counterparty not found"}), 404
        
        # Мягкое удаление
        cp.is_active = False
        cp.updated_ts_ms = int(time.time() * 1000)
        session.commit()
        
        return jsonify({
            "status": "ok",
            "message": "Контрагент удален"
        }), 200
        
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка удаления контрагента: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: ПОЛУЧИТЬ ТИПЫ КОНТРАГЕНТОВ
# ============================================
@counterparty_bp.route("/types", methods=["GET"])
@token_required
def get_counterparty_types():
    """Получить список доступных типов контрагентов"""
    return jsonify({
        "status": "ok",
        "data": [
            {"value": "supplier", "label": "Поставщик"},
            {"value": "partner", "label": "Партнер"},
            {"value": "distributor", "label": "Дистрибьютор"},
            {"value": "other", "label": "Свой"}
        ]
    }), 200