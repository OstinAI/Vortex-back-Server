# -*- coding: utf-8 -*-
"""
Модуль управления заявками дистрибьюторов
Путь: server/company/distributor/distributor_bp.py
"""

from flask import Blueprint, request, jsonify
from utils.security import token_required
from db.connection import get_session
from db.models import Company, User, StoredFile
from utils.crypto import encrypt, decrypt
import time
import re

distributor_bp = Blueprint("distributor", __name__, url_prefix="/api/company/distributor")

# ============================================
# НАСТРОЙКИ ШИФРОВАНИЯ
# ============================================

ENCRYPTED_FIELDS = [
    # Личные данные
    'bin',
    'phone',
    'email',
    'address',
    'actual_address',
    'paypal_email',
    'bank_details',
    # Данные компании
    'company_name',
    'president',
    'ownership_form',
    'notes',
    'website',
    'review_comment'
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
# ФУНКЦИЯ ДЛЯ ИСПРАВЛЕНИЯ КОДИРОВКИ
# ============================================
def fix_encoding(text: str) -> str:
    """Исправляет неправильную кодировку текста"""
    if not text:
        return text
    
    # Если текст содержит нормальные русские буквы, возвращаем как есть
    russian_chars = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя'
    if any(c in russian_chars for c in text):
        return text
    
    try:
        # Пробуем перекодировать из latin1 в utf-8
        return text.encode('latin1').decode('utf-8')
    except:
        return text

# ============================================
# API: СОЗДАНИЕ ЗАЯВКИ НА ДИСТРИБЬЮТОРА
# ============================================
@distributor_bp.route("/apply", methods=["POST"])
@token_required
def create_distributor_application():
    """Создать заявку на дистрибьютора"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    user_id = int(payload.get("user_id") or 0) if payload.get("user_id") else None

    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400

    data = request.get_json(silent=True) or {}

    # Проверяем обязательные поля
    required_fields = ['company_name', 'bin', 'president', 'phone', 'email', 'address', 'paypal_email']
    for field in required_fields:
        if not data.get(field):
            return jsonify({
                "status": "error",
                "message": f"Обязательное поле: {field}"
            }), 400

    # Проверяем, не подавал ли уже заявку
    session = get_session()
    try:
        from db.models import DistributorApplication
        existing = session.query(DistributorApplication).filter_by(
            company_id=company_id,
            status='pending'
        ).first()

        if existing:
            return jsonify({
                "status": "error",
                "message": "У вас уже есть активная заявка. Дождитесь рассмотрения."
            }), 400

        now = int(time.time() * 1000)

        # ✅ Исправляем кодировку перед шифрованием
        company_name = fix_encoding(data.get('company_name', '').strip())
        president = fix_encoding(data.get('president', '').strip())
        address = fix_encoding(data.get('address', '').strip())
        actual_address = fix_encoding((data.get('actual_address') or '').strip())
        ownership_form = fix_encoding(data.get('ownership_form', '').strip())
        notes = fix_encoding(data.get('notes', '').strip())
        website = data.get('website', '').strip() or ''

        # Создаем заявку с шифрованием ВСЕХ полей
        application = DistributorApplication(
            company_id=company_id,
            company_name=encrypt_field_value('company_name', company_name),
            bin=encrypt_field_value('bin', data.get('bin', '').strip()),
            president=encrypt_field_value('president', president),
            phone=encrypt_field_value('phone', data.get('phone', '').strip()),
            email=encrypt_field_value('email', data.get('email', '').strip()),
            address=encrypt_field_value('address', address),
            actual_address=encrypt_field_value('actual_address', actual_address),
            website=encrypt_field_value('website', website),
            ownership_form=encrypt_field_value('ownership_form', ownership_form),
            paypal_email=encrypt_field_value('paypal_email', data.get('paypal_email', '').strip()),
            notes=encrypt_field_value('notes', notes),
            status='pending',
            created_ts_ms=now,
            updated_ts_ms=now
        )

        session.add(application)
        session.commit()

        return jsonify({
            "status": "ok",
            "message": "Заявка успешно подана! Мы свяжемся с вами в ближайшее время.",
            "data": {
                "application_id": application.id,
                "status": application.status
            }
        }), 200

    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка создания заявки: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: ПОЛУЧИТЬ СТАТУС ЗАЯВКИ
# ============================================
@distributor_bp.route("/application/status", methods=["GET"])
@token_required
def get_application_status():
    """Получить статус заявки текущей компании"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)

    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400

    session = get_session()
    try:
        from db.models import DistributorApplication
        application = session.query(DistributorApplication).filter_by(
            company_id=company_id
        ).order_by(DistributorApplication.created_ts_ms.desc()).first()

        if not application:
            return jsonify({
                "status": "ok",
                "data": {
                    "has_application": False
                }
            }), 200

        # Расшифровываем данные для ответа
        return jsonify({
            "status": "ok",
            "data": {
                "has_application": True,
                "application_id": application.id,
                "status": application.status,
                "company_name": decrypt_field_value('company_name', application.company_name),
                "president": decrypt_field_value('president', application.president),
                "phone": decrypt_field_value('phone', application.phone),
                "email": decrypt_field_value('email', application.email),
                "created_ts_ms": application.created_ts_ms,
                "review_comment": decrypt_field_value('review_comment', application.review_comment or "")
            }
        }), 200

    except Exception as e:
        print(f"[ERROR] Ошибка получения статуса: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: ПОЛУЧИТЬ ВСЕ ЗАЯВКИ (ДЛЯ АДМИНА/VORTEX)
# ============================================
@distributor_bp.route("/applications/list", methods=["GET"])
@token_required
def list_applications():
    """Получить все заявки на дистрибьюторов (только для Vortex)"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    role = str(payload.get("role") or "")

    session = get_session()
    try:
        # Проверяем, что это компания Vortex или Admin
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404

        is_vortex = "vortex" in company.name.lower()
        is_admin = role in ("Integrator", "Admin")

        if not is_vortex and not is_admin:
            return jsonify({"status": "error", "message": "ACCESS_DENIED"}), 403

        from db.models import DistributorApplication
        applications = session.query(DistributorApplication).order_by(
            DistributorApplication.created_ts_ms.desc()
        ).all()

        result = []
        for app in applications:
            # Получаем компанию-заявителя
            applicant = session.query(Company).filter_by(id=app.company_id).first()

            # Расшифровываем все поля
            result.append({
                "id": app.id,
                "company_id": app.company_id,
                "company_name": decrypt_field_value('company_name', app.company_name),
                "bin": decrypt_field_value('bin', app.bin),
                "president": decrypt_field_value('president', app.president),
                "phone": decrypt_field_value('phone', app.phone),
                "email": decrypt_field_value('email', app.email),
                "address": decrypt_field_value('address', app.address),
                "actual_address": decrypt_field_value('actual_address', app.actual_address or ""),
                "website": decrypt_field_value('website', app.website or ""),
                "ownership_form": decrypt_field_value('ownership_form', app.ownership_form or ""),
                "paypal_email": decrypt_field_value('paypal_email', app.paypal_email),
                "notes": decrypt_field_value('notes', app.notes or ""),
                "status": app.status,
                "applicant_name": applicant.name if applicant else "",
                "created_ts_ms": app.created_ts_ms,
                "review_comment": decrypt_field_value('review_comment', app.review_comment or "")
            })

        return jsonify({
            "status": "ok",
            "data": result,
            "total": len(result)
        }), 200

    except Exception as e:
        print(f"[ERROR] Ошибка получения списка заявок: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: ОДОБРИТЬ/ОТКЛОНИТЬ ЗАЯВКУ
# ============================================
@distributor_bp.route("/application/review/<int:application_id>", methods=["POST"])
@token_required
def review_application(application_id):
    """Одобрить или отклонить заявку (только для Vortex)"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    user_id = int(payload.get("user_id") or 0) if payload.get("user_id") else None
    role = str(payload.get("role") or "")

    data = request.get_json(silent=True) or {}
    action = data.get('action', '')  # 'approve' или 'reject'
    comment = data.get('comment', '').strip()

    if action not in ['approve', 'reject']:
        return jsonify({"status": "error", "message": "Неверное действие"}), 400

    session = get_session()
    try:
        # Проверяем права
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404

        is_vortex = "vortex" in company.name.lower()
        is_admin = role in ("Integrator", "Admin")

        if not is_vortex and not is_admin:
            return jsonify({"status": "error", "message": "ACCESS_DENIED"}), 403

        from db.models import DistributorApplication, Distributor
        application = session.query(DistributorApplication).filter_by(
            id=application_id,
            status='pending'
        ).first()

        if not application:
            return jsonify({"status": "error", "message": "Заявка не найдена или уже обработана"}), 404

        now = int(time.time() * 1000)

        if action == 'approve':
            application.status = 'approved'
            application.reviewed_by_user_id = user_id
            application.reviewed_ts_ms = now
            application.review_comment = encrypt_field_value('review_comment', comment or "Заявка одобрена")

            # Создаем запись дистрибьютора с шифрованием
            distributor = Distributor(
                application_id=application.id,
                company_id=application.company_id,
                company_name=application.company_name,
                bin=application.bin,
                president=application.president,
                phone=application.phone,
                email=application.email,
                address=application.address,
                actual_address=application.actual_address,
                website=application.website,
                ownership_form=application.ownership_form,
                paypal_email=application.paypal_email,
                is_active=True,
                created_ts_ms=now,
                updated_ts_ms=now
            )
            session.add(distributor)

            message = "Заявка одобрена! Вы стали дистрибьютором Vortex."

        else:  # reject
            application.status = 'rejected'
            application.reviewed_by_user_id = user_id
            application.reviewed_ts_ms = now
            application.review_comment = encrypt_field_value('review_comment', comment or "Заявка отклонена")

            message = "Заявка отклонена"

        application.updated_ts_ms = now
        session.commit()

        return jsonify({
            "status": "ok",
            "message": message,
            "data": {
                "application_id": application.id,
                "status": application.status
            }
        }), 200

    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка обработки заявки: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: ПОЛУЧИТЬ СПИСОК ДИСТРИБЬЮТОРОВ (ДЛЯ КОМПАНИЙ)
# ============================================
@distributor_bp.route("/list", methods=["GET"])
@token_required
def get_distributors():
    """Получить список всех активных дистрибьюторов"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)

    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400

    session = get_session()
    try:
        from db.models import Distributor, DistributorCompanyLink, Company

        # Получаем всех активных дистрибьюторов
        distributors = session.query(Distributor).filter_by(
            is_active=True
        ).order_by(Distributor.company_name.asc()).all()

        # Проверяем, привязана ли текущая компания к какому-либо дистрибьютору
        existing_link = session.query(DistributorCompanyLink).filter_by(
            company_id=company_id,
            is_active=True
        ).first()

        result = []
        for d in distributors:
            # ✅ Получаем актуальные данные компании
            company = session.query(Company).filter_by(id=d.company_id).first()
            
            # Если компания существует и у нее другое название - синхронизируем
            if company and company.name != d.company_name:
                # Обновляем название дистрибьютора
                d.company_name = encrypt_field_value('company_name', company.name)
                d.updated_ts_ms = int(time.time() * 1000)
                session.commit()
                print(f"[SYNC] Обновлено название дистрибьютора {d.id}: {company.name}")

            is_linked = False
            if existing_link and existing_link.distributor_id == d.id:
                is_linked = True

            # Расшифровываем данные
            result.append({
                "id": d.id,
                "company_name": decrypt_field_value('company_name', d.company_name),
                "president": decrypt_field_value('president', d.president),
                "phone": decrypt_field_value('phone', d.phone),
                "email": decrypt_field_value('email', d.email),
                "address": decrypt_field_value('address', d.address),
                "website": decrypt_field_value('website', d.website or ""),
                "total_clients": d.total_clients or 0,
                "is_linked": is_linked,
                "created_ts_ms": d.created_ts_ms
            })

        return jsonify({
            "status": "ok",
            "data": result,
            "total": len(result),
            "has_link": existing_link is not None,
            "linked_distributor_id": existing_link.distributor_id if existing_link else None
        }), 200

    except Exception as e:
        print(f"[ERROR] Ошибка получения списка дистрибьюторов: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: ПОЛУЧИТЬ ВСЕ ЗАЯВКИ (ДЛЯ АДМИНА/СТРАНИЦЫ ЗАЯВОК)
# ============================================
@distributor_bp.route("/applications/all", methods=["GET"])
@token_required
def get_all_applications():
    """Получить все заявки с возможностью фильтрации по статусу"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    role = str(payload.get("role") or "")

    session = get_session()
    try:
        from db.models import DistributorApplication, Distributor, DistributorCompanyLink, Company

        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404

        is_vortex = "vortex" in company.name.lower()
        is_admin = role in ("Integrator", "Admin")

        # Если Vortex или Admin - показываем ВСЕ заявки
        if is_vortex or is_admin:
            applications = session.query(DistributorApplication).order_by(
                DistributorApplication.created_ts_ms.desc()
            ).all()
            print(f"[DEBUG] Vortex/Admin: найдено заявок: {len(applications)}")
        else:
            # Иначе показываем только заявки этой компании
            applications = session.query(DistributorApplication).filter_by(
                company_id=company_id
            ).order_by(
                DistributorApplication.created_ts_ms.desc()
            ).all()
            print(f"[DEBUG] Обычная компания {company_id}: найдено заявок: {len(applications)}")

        result = []
        for app in applications:
            # ✅ Получаем актуальные данные компании
            applicant = session.query(Company).filter_by(id=app.company_id).first()
            
            # ✅ Используем актуальное название из таблицы companies, если компания существует
            actual_company_name = applicant.name if applicant else decrypt_field_value('company_name', app.company_name)
            
            # Получаем количество компаний привязанных к этому дистрибьютору (если одобрен)
            linked_count = 0
            if app.status == 'approved':
                distributor = session.query(Distributor).filter_by(
                    application_id=app.id
                ).first()
                if distributor:
                    linked_count = session.query(DistributorCompanyLink).filter_by(
                        distributor_id=distributor.id,
                        is_active=True
                    ).count()

            result.append({
                "id": app.id,
                "company_id": app.company_id,
                # ✅ Используем актуальное название
                "company_name": actual_company_name,
                "bin": decrypt_field_value('bin', app.bin),
                "president": decrypt_field_value('president', app.president),
                "phone": decrypt_field_value('phone', app.phone),
                "email": decrypt_field_value('email', app.email),
                "address": decrypt_field_value('address', app.address),
                "actual_address": decrypt_field_value('actual_address', app.actual_address or ""),
                "website": decrypt_field_value('website', app.website or ""),
                "ownership_form": decrypt_field_value('ownership_form', app.ownership_form or ""),
                "paypal_email": decrypt_field_value('paypal_email', app.paypal_email),
                "notes": decrypt_field_value('notes', app.notes or ""),
                "status": app.status,
                "applicant_name": applicant.name if applicant else "",
                "created_ts_ms": app.created_ts_ms,
                "review_comment": decrypt_field_value('review_comment', app.review_comment or ""),
                "linked_count": linked_count
            })

        print(f"[DEBUG] Возвращаем {len(result)} заявок")
        return jsonify({
            "status": "ok",
            "data": result,
            "total": len(result)
        }), 200

    except Exception as e:
        print(f"[ERROR] Ошибка получения заявок: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()

# ============================================
# API: ОТОЗВАТЬ ОДОБРЕНИЕ ЗАЯВКИ
# ============================================
@distributor_bp.route("/application/revoke/<int:application_id>", methods=["POST"])
@token_required
def revoke_application(application_id):
    """Отозвать одобрение заявки (вернуть в статус pending)"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    user_id = int(payload.get("user_id") or 0) if payload.get("user_id") else None
    role = str(payload.get("role") or "")

    data = request.get_json(silent=True) or {}
    comment = data.get('comment', '').strip()

    session = get_session()
    try:
        from db.models import DistributorApplication, Distributor, DistributorCompanyLink

        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404

        is_vortex = "vortex" in company.name.lower()
        is_admin = role in ("Integrator", "Admin")

        if not is_vortex and not is_admin:
            return jsonify({"status": "error", "message": "ACCESS_DENIED"}), 403

        application = session.query(DistributorApplication).filter_by(
            id=application_id,
            status='approved'
        ).first()

        if not application:
            return jsonify({"status": "error", "message": "Заявка не найдена или не одобрена"}), 404

        # Находим дистрибьютора
        distributor = session.query(Distributor).filter_by(
            application_id=application_id
        ).first()

        now = int(time.time() * 1000)

        if distributor:
            # Отключаем все активные связи этого дистрибьютора
            links = session.query(DistributorCompanyLink).filter_by(
                distributor_id=distributor.id,
                is_active=True
            ).all()
            
            for link in links:
                link.is_active = False
                # Обновляем статистику
                comp = session.query(Company).filter_by(id=link.company_id).first()
                if comp:
                    pass  # ничего не делаем с компанией
            
            # Удаляем дистрибьютора или деактивируем
            distributor.is_active = False
            distributor.updated_ts_ms = now

        # Возвращаем заявку в статус pending
        application.status = 'pending'
        application.reviewed_by_user_id = user_id
        application.reviewed_ts_ms = now
        application.review_comment = encrypt_field_value('review_comment', comment or "Одобрение отозвано")
        application.updated_ts_ms = now

        session.commit()

        return jsonify({
            "status": "ok",
            "message": "Одобрение отозвано, заявка возвращена в ожидание",
            "data": {
                "application_id": application.id,
                "status": application.status
            }
        }), 200

    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка отзыва одобрения: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()
        
        
# ============================================
# API: ПОЛУЧИТЬ ДЕТАЛЬНУЮ ИНФОРМАЦИЮ О ДИСТРИБЬЮТОРЕ
# ============================================
@distributor_bp.route("/details/<int:distributor_id>", methods=["GET"])
@token_required
def get_distributor_details(distributor_id):
    """Получить детальную информацию о дистрибьюторе и его компаниях"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    role = str(payload.get("role") or "")

    session = get_session()
    try:
        from db.models import Distributor, DistributorCompanyLink, Company

        # Проверяем права
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404

        is_vortex = "vortex" in company.name.lower()
        is_admin = role in ("Integrator", "Admin")

        if not is_vortex and not is_admin:
            return jsonify({"status": "error", "message": "ACCESS_DENIED"}), 403

        distributor = session.query(Distributor).filter_by(
            id=distributor_id,
            is_active=True
        ).first()

        if not distributor:
            return jsonify({"status": "error", "message": "Distributor not found"}), 404

        # Получаем привязанные компании
        links = session.query(DistributorCompanyLink).filter_by(
            distributor_id=distributor.id,
            is_active=True
        ).all()

        linked_companies = []
        for link in links:
            comp = session.query(Company).filter_by(id=link.company_id).first()
            if comp:
                linked_companies.append({
                    "id": comp.id,
                    "name": comp.name,
                    "bin": getattr(comp, 'bin', '') or '',
                    "phone": getattr(comp, 'phone', '') or '',
                    "address": getattr(comp, 'address', '') or '',
                    "linked_ts_ms": link.linked_ts_ms
                })

        result = {
            "id": distributor.id,
            "company_id": distributor.company_id,
            "company_name": decrypt_field_value('company_name', distributor.company_name),
            "bin": decrypt_field_value('bin', distributor.bin),
            "president": decrypt_field_value('president', distributor.president),
            "phone": decrypt_field_value('phone', distributor.phone),
            "email": decrypt_field_value('email', distributor.email),
            "address": decrypt_field_value('address', distributor.address),
            "actual_address": decrypt_field_value('actual_address', distributor.actual_address or ""),
            "website": decrypt_field_value('website', distributor.website or ""),
            "ownership_form": decrypt_field_value('ownership_form', distributor.ownership_form or ""),
            "paypal_email": decrypt_field_value('paypal_email', distributor.paypal_email),
            "total_clients": distributor.total_clients or 0,
            "created_ts_ms": distributor.created_ts_ms,
            "linked_companies": linked_companies
        }

        return jsonify({
            "status": "ok",
            "data": result
        }), 200

    except Exception as e:
        print(f"[ERROR] Ошибка получения деталей дистрибьютора: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()
        
        
        
# ============================================
# API: ПРИВЯЗАТЬ КОМПАНИЮ К ДИСТРИБЬЮТОРУ
# ============================================
@distributor_bp.route("/link", methods=["POST"])
@token_required
def link_company_to_distributor():
    """Привязать компанию к дистрибьютору"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)

    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400

    data = request.get_json(silent=True) or {}
    distributor_id = data.get('distributor_id')

    if not distributor_id:
        return jsonify({"status": "error", "message": "Не указан дистрибьютор"}), 400

    session = get_session()
    try:
        from db.models import Distributor, DistributorCompanyLink

        # Проверяем, существует ли дистрибьютор
        distributor = session.query(Distributor).filter_by(
            id=distributor_id,
            is_active=True
        ).first()

        if not distributor:
            return jsonify({"status": "error", "message": "Дистрибьютор не найден"}), 404

        # Проверяем активную связь с другим дистрибьютором
        existing_active = session.query(DistributorCompanyLink).filter_by(
            company_id=company_id,
            is_active=True
        ).first()

        if existing_active:
            if existing_active.distributor_id == distributor_id:
                return jsonify({
                    "status": "ok",
                    "message": "Компания уже привязана к этому дистрибьютору"
                }), 200
            else:
                # Отвязываем от старого
                existing_active.is_active = False

        # ✅ ИСПРАВЛЕНИЕ: Проверяем неактивную связь с ЭТИМ дистрибьютором
        existing_inactive = session.query(DistributorCompanyLink).filter_by(
            distributor_id=distributor_id,
            company_id=company_id,
            is_active=False
        ).first()

        now = int(time.time() * 1000)

        if existing_inactive:
            # Если есть неактивная связь - обновляем её (делаем активной)
            existing_inactive.is_active = True
            existing_inactive.linked_ts_ms = now
            print(f"[INFO] Обновлена существующая связь: distributor_id={distributor_id}, company_id={company_id}")
        else:
            # Создаем новую связь
            link = DistributorCompanyLink(
                distributor_id=distributor_id,
                company_id=company_id,
                linked_ts_ms=now,
                is_active=True
            )
            session.add(link)
            print(f"[INFO] Создана новая связь: distributor_id={distributor_id}, company_id={company_id}")

        # Обновляем статистику дистрибьютора
        distributor.total_clients = (distributor.total_clients or 0) + 1

        session.commit()

        return jsonify({
            "status": "ok",
            "message": "Компания успешно привязана к дистрибьютору",
            "data": {
                "distributor_id": distributor_id,
                "distributor_name": decrypt_field_value('company_name', distributor.company_name)
            }
        }), 200

    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка привязки компании: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: ОТВЯЗАТЬ КОМПАНИЮ ОТ ДИСТРИБЬЮТОРА
# ============================================
@distributor_bp.route("/unlink", methods=["POST"])
@token_required
def unlink_company_from_distributor():
    """Отвязать компанию от дистрибьютора"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)

    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400

    session = get_session()
    try:
        from db.models import DistributorCompanyLink, Distributor

        link = session.query(DistributorCompanyLink).filter_by(
            company_id=company_id,
            is_active=True
        ).first()

        if not link:
            return jsonify({"status": "error", "message": "Компания не привязана к дистрибьютору"}), 404

        distributor_id = link.distributor_id
        link.is_active = False

        # Обновляем статистику дистрибьютора
        distributor = session.query(Distributor).filter_by(id=distributor_id).first()
        if distributor and distributor.total_clients > 0:
            distributor.total_clients = distributor.total_clients - 1

        session.commit()

        return jsonify({
            "status": "ok",
            "message": "Компания отвязана от дистрибьютора"
        }), 200

    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка отвязки компании: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# API: ПОЛУЧИТЬ СТАТИСТИКУ ДИСТРИБЬЮТОРА
# ============================================
@distributor_bp.route("/stats", methods=["GET"])
@token_required
def get_distributor_stats():
    """Получить статистику дистрибьютора"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)

    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400

    session = get_session()
    try:
        from db.models import Distributor, DistributorCompanyLink

        # Проверяем, является ли компания дистрибьютором
        distributor = session.query(Distributor).filter_by(
            company_id=company_id,
            is_active=True
        ).first()

        if not distributor:
            return jsonify({
                "status": "ok",
                "data": {
                    "is_distributor": False
                }
            }), 200

        # Получаем список привязанных компаний
        links = session.query(DistributorCompanyLink).filter_by(
            distributor_id=distributor.id,
            is_active=True
        ).all()

        linked_companies = []
        for link in links:
            comp = session.query(Company).filter_by(id=link.company_id).first()
            if comp:
                linked_companies.append({
                    "id": comp.id,
                    "name": comp.name,
                    "linked_ts_ms": link.linked_ts_ms
                })

        return jsonify({
            "status": "ok",
            "data": {
                "is_distributor": True,
                "distributor_id": distributor.id,
                "company_name": decrypt_field_value('company_name', distributor.company_name),
                "total_clients": distributor.total_clients or 0,
                "total_commission": distributor.total_commission or 0.0,
                "linked_companies": linked_companies,
                "created_ts_ms": distributor.created_ts_ms
            }
        }), 200

    except Exception as e:
        print(f"[ERROR] Ошибка получения статистики: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()
        
# ============================================
# ФУНКЦИЯ СИНХРОНИЗАЦИИ ДАННЫХ ДИСТРИБЬЮТОРА
# ============================================
def sync_distributor_data(company_id: int, session):
    """Синхронизирует данные компании с таблицей дистрибьюторов"""
    try:
        from db.models import Distributor, Company
        
        # Проверяем, является ли компания дистрибьютором
        distributor = session.query(Distributor).filter_by(
            company_id=company_id,
            is_active=True
        ).first()
        
        if not distributor:
            return
        
        # Получаем актуальные данные компании
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return
        
        # Обновляем название дистрибьютора
        if company.name != distributor.company_name:
            # Обновляем название (с шифрованием)
            distributor.company_name = encrypt_field_value('company_name', company.name)
            distributor.updated_ts_ms = int(time.time() * 1000)
            
            # Также обновляем другие поля, если они изменились
            if company.bin:
                distributor.bin = encrypt_field_value('bin', company.bin or '')
            if company.phone:
                distributor.phone = encrypt_field_value('phone', company.phone or '')
            if company.president:
                distributor.president = encrypt_field_value('president', company.president or '')
            if company.address:
                distributor.address = encrypt_field_value('address', company.address or '')
            if company.website:
                distributor.website = encrypt_field_value('website', company.website or '')
            
            print(f"[SYNC] Обновлены данные дистрибьютора ID={distributor.id}: {company.name}")
            session.commit()
            
    except Exception as e:
        print(f"[SYNC] Ошибка синхронизации дистрибьютора: {str(e)}")
        import traceback
        traceback.print_exc()
        
# ============================================
# API: СИНХРОНИЗИРОВАТЬ ДАННЫЕ ДИСТРИБЬЮТОРА
# ============================================
@distributor_bp.route("/sync", methods=["POST"])
@token_required
def sync_distributor():
    """Синхронизировать данные компании с дистрибьютором"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    session = get_session()
    try:
        sync_distributor_data(company_id, session)
        
        return jsonify({
            "status": "ok",
            "message": "Данные дистрибьютора синхронизированы"
        }), 200
        
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка синхронизации: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()