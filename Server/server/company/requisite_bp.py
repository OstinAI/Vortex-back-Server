# -*- coding: utf-8 -*-
from flask import Blueprint, request, jsonify
from utils.security import token_required
from db.connection import get_session
from db.models import Company, CompanyProfileField, User, StoredFile
from utils.crypto import encrypt, decrypt
import re
import time

requisite_bp = Blueprint("requisite", __name__)

# ============================================
# НАСТРОЙКИ ШИФРОВАНИЯ
# ============================================

# Список полей, которые нужно шифровать
ENCRYPTED_FIELDS = [
    'bin', 
    'phone', 
    'postal_address',
    'actual_address',
    'payment_account',
    'payment_holder',
    'company_email',
    'president_email',
    'contact_person_email',
    'ceo_identification',
    'reg_certificate',
    'license_number',
    'contact_person_phone'
]

def should_encrypt(key: str) -> bool:
    """Проверяет, нужно ли шифровать поле"""
    for field in ENCRYPTED_FIELDS:
        if field in key:
            return True
    return False

def encrypt_field_value(key: str, value: str) -> str:
    """Шифрует значение, если поле в списке"""
    if not value or not should_encrypt(key):
        return value
    try:
        return encrypt(value)
    except Exception as e:
        print(f"[WARN] Ошибка шифрования {key}: {e}")
        return value

def decrypt_field_value(key: str, value: str) -> str:
    """Расшифровывает значение, если поле зашифровано"""
    if not value:
        return value
    
    if not should_encrypt(key):
        return value
    
    try:
        # Проверяем, зашифровано ли значение (признак шифрования Fernet)
        if value.startswith('gAAAAA'):
            print(f"[DEBUG] Расшифровываем {key}...")
            result = decrypt(value)
            print(f"[DEBUG] {key} расшифрован успешно")
            return result
        return value
    except Exception as e:
        print(f"[ERROR] Ошибка дешифрования {key}: {str(e)}")
        import traceback
        traceback.print_exc()
        # Возвращаем исходное значение при ошибке
        return value


# ============================================
# ПОЛУЧЕНИЕ РЕКВИЗИТОВ КОМПАНИИ
# ============================================
@requisite_bp.route("/requisite", methods=["GET"])
@token_required
def get_company_requisite():
    """Получить реквизиты компании"""
    try:
        payload = request.user
        company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
        
        if company_id <= 0:
            return jsonify({"status": "error", "message": "Invalid company"}), 400
        
        session = get_session()
        try:
            company = session.query(Company).filter_by(id=company_id).first()
            if not company:
                return jsonify({"status": "error", "message": "Company not found"}), 404
            
            fields = session.query(CompanyProfileField).filter_by(company_id=company_id).all()
            admins = session.query(User).filter_by(company_id=company_id, role='Admin').all()
            
            logo_path = ""
            if company.logo_file_id:
                logo_path = f"/api/files/{company.logo_file_id}"
            
            admins_list = []
            for admin in admins:
                admins_list.append({
                    "full_name": admin.full_name or "",
                    "email": admin.email or "",
                    "phone": admin.phone or "",
                    "username": admin.username or ""
                })
            
            # ✅ Функция безопасного получения значения с расшифровкой
            def safe_decrypt(key: str, value: str) -> str:
                try:
                    return decrypt_field_value(key, value)
                except Exception as e:
                    print(f"[WARN] Ошибка при расшифровке поля {key}: {str(e)}")
                    return value  # Возвращаем исходное значение при ошибке
            
            # ✅ Расшифровываем данные компании с безопасной обработкой
            data = {
                "id": company.id,
                "name": company.name,
                "bin": safe_decrypt('bin', company.bin or ""),
                "phone": safe_decrypt('phone', company.phone or ""),
                "address": company.address or "",  # address не шифруется
                "website": company.website or "",
                "slogan": company.slogan or "",
                "president": company.president or "",
                "postal_address": safe_decrypt('postal_address', company.postal_address or ""),
                "company_email": safe_decrypt('company_email', company.company_email or ""),
                "president_email": safe_decrypt('president_email', company.president_email or ""),
                "reg_certificate": safe_decrypt('reg_certificate', company.reg_certificate or ""),
                "reg_date": company.reg_date.strftime('%Y-%m-%d') if company.reg_date else "",
                "ownership_form": company.ownership_form or "",
                "foundation_date": company.foundation_date.strftime('%Y-%m-%d') if company.foundation_date else "",
                "oked_code": company.oked_code or "",
                "kbk_code": company.kbk_code or "",
                "license_number": safe_decrypt('license_number', company.license_number or ""),
                "license_date": company.license_date.strftime('%Y-%m-%d') if company.license_date else "",
                "actual_address": safe_decrypt('actual_address', company.actual_address or ""),
                "instagram": company.instagram or "",
                "facebook": company.facebook or "",
                "linkedin": company.linkedin or "",
                "youtube": company.youtube or "",
                "tiktok": company.tiktok or "",
                "ceo_identification": safe_decrypt('ceo_identification', company.ceo_identification or ""),
                "contact_person": company.contact_person or "",
                "contact_person_phone": safe_decrypt('contact_person_phone', company.contact_person_phone or ""),
                "contact_person_email": safe_decrypt('contact_person_email', company.contact_person_email or ""),
                "logo_path": logo_path,
                "stamp_path": company.stamp_path or "",
                "signature_path": company.signature_path or "",
                "qr_code_path": company.qr_code_path or "",
                "is_active": company.is_active,
                "storage_limit_mb": company.storage_limit_mb,
                "storage_used_bytes": company.storage_used_bytes,
                "admins": admins_list,
                "custom_fields": [
                    {
                        "key": f.key,
                        "value": safe_decrypt(f.key, f.value),
                        "required": f.required
                    }
                    for f in fields
                ]
            }
            
            return jsonify({"status": "ok", "data": data}), 200
            
        except Exception as e:
            print(f"[ERROR] Ошибка в get_company_requisite: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": f"Internal error: {str(e)}"}), 500
        finally:
            session.close()
            
    except Exception as e:
        print(f"[ERROR] Ошибка в get_company_requisite (внешняя): {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"External error: {str(e)}"}), 500


# ============================================
# ОБНОВЛЕНИЕ ОСНОВНЫХ РЕКВИЗИТОВ КОМПАНИИ
# ============================================
@requisite_bp.route("/requisite/update", methods=["POST"])
@token_required
def update_company_requisites():
    """Обновить основные реквизиты компании"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    data = request.get_json(silent=True) or {}
    
    session = get_session()
    try:
        from db.models import DistributorApplication
        
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404
        
        # Обновляем поля компании
        fields_to_update = [
            'name', 'bin', 'phone', 'website', 'address', 'slogan',
            'president', 'postal_address', 'company_email', 'president_email',
            'reg_certificate', 'ownership_form', 'oked_code', 'kbk_code',
            'license_number', 'actual_address', 'instagram', 'facebook',
            'linkedin', 'youtube', 'tiktok', 'ceo_identification',
            'contact_person', 'contact_person_phone', 'contact_person_email',
            'logo_path', 'stamp_path', 'signature_path', 'qr_code_path'
        ]
        
        for field in fields_to_update:
            if field in data:
                value = data[field]
                if should_encrypt(field):
                    value = encrypt_field_value(field, value)
                setattr(company, field, value)
        
        # Обработка дат
        from datetime import datetime
        if 'reg_date' in data:
            company.reg_date = datetime.strptime(data['reg_date'], '%Y-%m-%d').date() if data['reg_date'] else None
        if 'foundation_date' in data:
            company.foundation_date = datetime.strptime(data['foundation_date'], '%Y-%m-%d').date() if data['foundation_date'] else None
        if 'license_date' in data:
            company.license_date = datetime.strptime(data['license_date'], '%Y-%m-%d').date() if data['license_date'] else None
        
        session.commit()
        
        # ✅ Обновляем заявки этой компании (если есть активные)
        try:
            # Обновляем название в заявках, которые в статусе pending
            pending_applications = session.query(DistributorApplication).filter_by(
                company_id=company_id,
                status='pending'
            ).all()
            
            for app in pending_applications:
                app.company_name = encrypt_field_value('company_name', company.name)
                app.updated_ts_ms = int(time.time() * 1000)
                print(f"[REQUISITE] Обновлена заявка {app.id}: название {company.name}")
            
            # Также обновляем одобренные заявки (если название изменилось)
            approved_applications = session.query(DistributorApplication).filter_by(
                company_id=company_id,
                status='approved'
            ).all()
            
            for app in approved_applications:
                app.company_name = encrypt_field_value('company_name', company.name)
                app.updated_ts_ms = int(time.time() * 1000)
                print(f"[REQUISITE] Обновлена одобренная заявка {app.id}: название {company.name}")
            
            session.commit()
            
        except Exception as e:
            print(f"[REQUISITE] Ошибка обновления заявок: {str(e)}")
            # Не прерываем выполнение
        
        # ✅ Синхронизация с дистрибьютором
        try:
            from server.company.distributor.distributor_bp import sync_distributor_data
            sync_distributor_data(company_id, session)
            print(f"[REQUISITE] Дистрибьютор синхронизирован после обновления компании {company_id}")
        except Exception as e:
            print(f"[REQUISITE] Ошибка синхронизации дистрибьютора: {str(e)}")
        
        return jsonify({
            "status": "ok",
            "message": "Реквизиты компании обновлены"
        }), 200
        
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка обновления: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# СОХРАНЕНИЕ ПЛАТЕЖНЫХ РЕКВИЗИТОВ
# ============================================
@requisite_bp.route("/requisite/payment", methods=["POST"])
@token_required
def save_payment_requisites():
    """Сохранить платежные реквизиты компании"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    data = request.get_json(silent=True) or {}
    
    group_index = data.get('group_index')
    action = data.get('action', 'save')
    delete_qr = data.get('_delete_qr', False)
    
    print(f"[DEBUG] Получены данные: {data}")
    print(f"[DEBUG] group_index: {group_index}, action: {action}, delete_qr: {delete_qr}")
    
    session = get_session()
    try:
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404
        
        payment_keys = ['payment_holder', 'payment_bank', 'payment_bik', 
                       'payment_account', 'payment_kbe', 'payment_kno',
                       'payment_link', 'payment_currency', 'payment_qr']
        
        saved_count = 0
        updated_count = 0
        deleted_qr_count = 0
        
        # ✅ Если action == 'add' - создаем НОВУЮ группу
        if action == 'add':
            if group_index is not None:
                target_group = int(group_index)
                
                # Проверяем, существует ли уже группа с таким индексом
                existing_fields = []
                for key in payment_keys:
                    if target_group == 0:
                        field_key = key
                    else:
                        field_key = f"{key}_{target_group}"
                    
                    field = session.query(CompanyProfileField).filter_by(
                        company_id=company_id,
                        key=field_key
                    ).first()
                    if field:
                        existing_fields.append(field_key)
                
                # Если группа уже существует - обновляем её
                if existing_fields:
                    print(f"[DEBUG] Группа {target_group} уже существует, обновляем")
                    
                    # ✅ Проверяем, нужно ли удалить QR
                    if delete_qr:
                        for key in payment_keys:
                            if key == 'payment_qr':
                                if target_group == 0:
                                    qr_key = key
                                else:
                                    qr_key = f"{key}_{target_group}"
                                
                                qr_field = session.query(CompanyProfileField).filter_by(
                                    company_id=company_id,
                                    key=qr_key
                                ).first()
                                
                                if qr_field:
                                    import re
                                    match = re.search(r'/api/files/public/(\d+)', qr_field.value)
                                    if match:
                                        file_id = int(match.group(1))
                                        file_record = session.query(StoredFile).filter_by(
                                            id=file_id,
                                            company_id=company_id
                                        ).first()
                                        if file_record:
                                            company.storage_used_bytes = max(0, company.storage_used_bytes - file_record.size_bytes)
                                            session.delete(file_record)
                                            print(f"[DEBUG] Удален QR файл: {file_id}")
                                    
                                    session.delete(qr_field)
                                    deleted_qr_count += 1
                                    print(f"[DEBUG] Удалено поле QR: {qr_key}")
                        
                        session.commit()
                        return jsonify({
                            "status": "ok",
                            "message": f"QR код удален",
                            "deleted_qr": deleted_qr_count
                        }), 200
                    
                    for key, value in data.items():
                        if key in ['group_index', 'action', '_delete_qr']:
                            continue
                        
                        if not value or not str(value).strip():
                            continue
                        
                        # Проверяем, относится ли ключ к платежным реквизитам
                        is_payment = False
                        for pk in payment_keys:
                            if key == pk or key.startswith(pk + '_'):
                                is_payment = True
                                break
                        
                        if not is_payment:
                            continue
                        
                        # Пропускаем payment_qr с значением 'qr_uploaded' или '__DELETE__'
                        if key == 'payment_qr' and value in ['qr_uploaded', '__DELETE__']:
                            print(f"[DEBUG] Пропускаем payment_qr (специальное значение)")
                            continue
                        
                        import re
                        if re.match(r'payment_\w+_\d+', key):
                            actual_key = key
                        else:
                            if target_group == 0:
                                actual_key = key
                            else:
                                actual_key = f"{key}_{target_group}"
                        
                        existing = session.query(CompanyProfileField).filter_by(
                            company_id=company_id,
                            key=actual_key
                        ).first()
                        
                        # ✅ Шифруем значение при сохранении
                        encrypted_value = encrypt_field_value(actual_key, str(value).strip())
                        
                        if existing:
                            existing.value = encrypted_value
                            updated_count += 1
                            print(f"[DEBUG] Обновлено поле: {actual_key} = {value}")
                        else:
                            new_field = CompanyProfileField(
                                company_id=company_id,
                                key=actual_key,
                                value=encrypted_value,
                                required=False
                            )
                            session.add(new_field)
                            saved_count += 1
                            print(f"[DEBUG] Создано поле: {actual_key} = {value}")
                    
                    session.commit()
                    return jsonify({
                        "status": "ok",
                        "message": f"Обновлено {updated_count} полей, создано {saved_count}",
                        "updated_count": updated_count,
                        "saved_count": saved_count,
                        "group_index": target_group
                    }), 200
                
                # Если группа не существует - создаем новую
                print(f"[DEBUG] Создаем НОВУЮ группу с индексом: {target_group}")
                for key, value in data.items():
                    if key in ['group_index', 'action', '_delete_qr']:
                        continue
                    
                    if not value or not str(value).strip():
                        continue
                    
                    is_payment = False
                    for pk in payment_keys:
                        if key == pk or key.startswith(pk + '_'):
                            is_payment = True
                            break
                    
                    if not is_payment:
                        continue
                    
                    if key == 'payment_qr' and value in ['qr_uploaded', '__DELETE__']:
                        print(f"[DEBUG] Пропускаем payment_qr (специальное значение)")
                        continue
                    
                    import re
                    if re.match(r'payment_\w+_\d+', key):
                        actual_key = key
                    else:
                        if target_group == 0:
                            actual_key = key
                        else:
                            actual_key = f"{key}_{target_group}"
                    
                    # ✅ Шифруем значение при сохранении
                    encrypted_value = encrypt_field_value(actual_key, str(value).strip())
                    
                    new_field = CompanyProfileField(
                        company_id=company_id,
                        key=actual_key,
                        value=encrypted_value,
                        required=False
                    )
                    session.add(new_field)
                    saved_count += 1
                    print(f"[DEBUG] Добавлено новое поле: {actual_key} = {value}")
                
                session.commit()
                return jsonify({
                    "status": "ok",
                    "message": f"Создано {saved_count} полей",
                    "saved_count": saved_count,
                    "group_index": target_group
                }), 200
            
            # Если group_index не передан - находим следующий доступный
            else:
                all_fields = session.query(CompanyProfileField).filter_by(company_id=company_id).all()
                max_idx = -1
                has_group_0 = False
                
                for field in all_fields:
                    if field.key in payment_keys:
                        has_group_0 = True
                        continue
                    match = re.match(r'payment_\w+_(\d+)', field.key)
                    if match:
                        idx = int(match.group(1))
                        if idx > max_idx:
                            max_idx = idx
                
                if has_group_0:
                    new_group_index = max(1, max_idx + 1)
                else:
                    new_group_index = 0
                
                print(f"[DEBUG] Создаем новую группу с индексом: {new_group_index}")
                
                for key, value in data.items():
                    if key in ['group_index', 'action', '_delete_qr']:
                        continue
                    
                    if not value or not str(value).strip():
                        continue
                    
                    is_payment = False
                    for pk in payment_keys:
                        if key == pk or key.startswith(pk + '_'):
                            is_payment = True
                            break
                    
                    if not is_payment:
                        continue
                    
                    if key == 'payment_qr' and value in ['qr_uploaded', '__DELETE__']:
                        print(f"[DEBUG] Пропускаем payment_qr (специальное значение)")
                        continue
                    
                    if new_group_index == 0:
                        actual_key = key
                    else:
                        actual_key = f"{key}_{new_group_index}"
                    
                    # ✅ Шифруем значение при сохранении
                    encrypted_value = encrypt_field_value(actual_key, str(value).strip())
                    
                    new_field = CompanyProfileField(
                        company_id=company_id,
                        key=actual_key,
                        value=encrypted_value,
                        required=False
                    )
                    session.add(new_field)
                    saved_count += 1
                    print(f"[DEBUG] Добавлено новое поле: {actual_key} = {value}")
                
                session.commit()
                return jsonify({
                    "status": "ok",
                    "message": f"Создано {saved_count} полей",
                    "saved_count": saved_count,
                    "group_index": new_group_index
                }), 200
        
        # ✅ Если action != 'add' - обновляем существующую группу
        else:
            if group_index is not None:
                target_group = int(group_index)
                print(f"[DEBUG] Обновление группы с индексом: {target_group}")
                
                # ✅ Проверяем, нужно ли удалить QR
                if delete_qr:
                    for key in payment_keys:
                        if key == 'payment_qr':
                            if target_group == 0:
                                qr_key = key
                            else:
                                qr_key = f"{key}_{target_group}"
                            
                            qr_field = session.query(CompanyProfileField).filter_by(
                                company_id=company_id,
                                key=qr_key
                            ).first()
                            
                            if qr_field:
                                import re
                                match = re.search(r'/api/files/public/(\d+)', qr_field.value)
                                if match:
                                    file_id = int(match.group(1))
                                    file_record = session.query(StoredFile).filter_by(
                                        id=file_id,
                                        company_id=company_id
                                    ).first()
                                    if file_record:
                                        company.storage_used_bytes = max(0, company.storage_used_bytes - file_record.size_bytes)
                                        session.delete(file_record)
                                        print(f"[DEBUG] Удален QR файл: {file_id}")
                                
                                session.delete(qr_field)
                                deleted_qr_count += 1
                                print(f"[DEBUG] Удалено поле QR: {qr_key}")
                    
                    session.commit()
                    return jsonify({
                        "status": "ok",
                        "message": f"QR код удален",
                        "deleted_qr": deleted_qr_count
                    }), 200
                
                for key, value in data.items():
                    if key in ['group_index', 'action', '_delete_qr']:
                        continue
                    
                    if not value or not str(value).strip():
                        continue
                    
                    # Проверяем, относится ли ключ к платежным реквизитам
                    is_payment = False
                    for pk in payment_keys:
                        if key == pk or key.startswith(pk + '_'):
                            is_payment = True
                            break
                    
                    if not is_payment:
                        continue
                    
                    # Пропускаем payment_qr с значением '__DELETE__'
                    if key == 'payment_qr' and value == '__DELETE__':
                        print(f"[DEBUG] Пропускаем payment_qr (будет удален отдельно)")
                        continue
                    
                    # ✅ Правильно определяем ключ для БД
                    import re
                    if re.match(r'payment_\w+_\d+', key):
                        actual_key = key
                        print(f"[DEBUG] Ключ уже с индексом: {actual_key}")
                    else:
                        if target_group == 0:
                            actual_key = key
                        else:
                            actual_key = f"{key}_{target_group}"
                        print(f"[DEBUG] Добавляем индекс к ключу: {actual_key}")
                    
                    existing = session.query(CompanyProfileField).filter_by(
                        company_id=company_id,
                        key=actual_key
                    ).first()
                    
                    # ✅ Шифруем значение при сохранении
                    encrypted_value = encrypt_field_value(actual_key, str(value).strip())
                    
                    if existing:
                        existing.value = encrypted_value
                        updated_count += 1
                        print(f"[DEBUG] Обновлено поле: {actual_key} = {value}")
                    else:
                        new_field = CompanyProfileField(
                            company_id=company_id,
                            key=actual_key,
                            value=encrypted_value,
                            required=False
                        )
                        session.add(new_field)
                        saved_count += 1
                        print(f"[DEBUG] Создано поле: {actual_key} = {value}")
                
                session.commit()
                return jsonify({
                    "status": "ok",
                    "message": f"Обновлено {updated_count} полей, создано {saved_count}",
                    "updated_count": updated_count,
                    "saved_count": saved_count,
                    "group_index": target_group
                }), 200
            else:
                # Обновление группы 0
                print(f"[DEBUG] Обновление группы 0")
                
                # ✅ Проверяем, нужно ли удалить QR
                if delete_qr:
                    qr_field = session.query(CompanyProfileField).filter_by(
                        company_id=company_id,
                        key='payment_qr'
                    ).first()
                    
                    if qr_field:
                        import re
                        match = re.search(r'/api/files/public/(\d+)', qr_field.value)
                        if match:
                            file_id = int(match.group(1))
                            file_record = session.query(StoredFile).filter_by(
                                id=file_id,
                                company_id=company_id
                            ).first()
                            if file_record:
                                company.storage_used_bytes = max(0, company.storage_used_bytes - file_record.size_bytes)
                                session.delete(file_record)
                                print(f"[DEBUG] Удален QR файл: {file_id}")
                        
                        session.delete(qr_field)
                        deleted_qr_count += 1
                        print(f"[DEBUG] Удалено поле QR: payment_qr")
                    
                    session.commit()
                    return jsonify({
                        "status": "ok",
                        "message": f"QR код удален",
                        "deleted_qr": deleted_qr_count
                    }), 200
                
                for key, value in data.items():
                    if key in ['group_index', 'action', '_delete_qr']:
                        continue
                    
                    if not value or not str(value).strip():
                        continue
                    
                    is_payment = False
                    for pk in payment_keys:
                        if key == pk or key.startswith(pk + '_'):
                            is_payment = True
                            break
                    
                    if not is_payment:
                        continue
                    
                    if key == 'payment_qr' and value == '__DELETE__':
                        print(f"[DEBUG] Пропускаем payment_qr (будет удален отдельно)")
                        continue
                    
                    # ✅ Шифруем значение при сохранении
                    encrypted_value = encrypt_field_value(key, str(value).strip())
                    
                    existing = session.query(CompanyProfileField).filter_by(
                        company_id=company_id,
                        key=key
                    ).first()
                    
                    if existing:
                        existing.value = encrypted_value
                        updated_count += 1
                        print(f"[DEBUG] Обновлено поле: {key} = {value}")
                    else:
                        new_field = CompanyProfileField(
                            company_id=company_id,
                            key=key,
                            value=encrypted_value,
                            required=False
                        )
                        session.add(new_field)
                        saved_count += 1
                        print(f"[DEBUG] Создано поле: {key} = {value}")
                
                session.commit()
                return jsonify({
                    "status": "ok",
                    "message": f"Обновлено {updated_count} полей, создано {saved_count}",
                    "updated_count": updated_count,
                    "saved_count": saved_count,
                    "group_index": 0
                }), 200
        
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка сохранения: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# УДАЛЕНИЕ ПЛАТЕЖНОГО РЕКВИЗИТА
# ============================================
@requisite_bp.route("/requisite/payment/<field_key>", methods=["DELETE"])
@token_required
def delete_payment_requisite(field_key):
    """Удалить платежный реквизит по ключу"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    session = get_session()
    try:
        field = session.query(CompanyProfileField).filter_by(
            company_id=company_id,
            key=field_key
        ).first()
        
        if not field:
            return jsonify({"status": "error", "message": "Field not found"}), 404
        
        session.delete(field)
        session.commit()
        
        return jsonify({
            "status": "ok",
            "message": f"Поле '{field_key}' удалено"
        }), 200
        
    except Exception as e:
        session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# УДАЛЕНИЕ ВСЕХ ПЛАТЕЖНЫХ РЕКВИЗИТОВ ГРУППЫ
# ============================================
@requisite_bp.route("/requisite/payment/group/<int:group_index>", methods=["DELETE"])
@token_required
def delete_payment_group(group_index):
    """Удалить все платежные реквизиты группы"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    session = get_session()
    try:
        deleted_count = 0
        deleted_files = []
        
        # Находим все поля группы
        if group_index == 0:
            payment_keys = [
                'payment_holder', 'payment_bank', 'payment_bik', 
                'payment_account', 'payment_kbe', 'payment_kno',
                'payment_link', 'payment_currency', 'payment_qr'
            ]
            payment_keys_with_suffix = [
                f'{key}_0' for key in payment_keys
            ]
            
            fields = session.query(CompanyProfileField).filter(
                CompanyProfileField.company_id == company_id,
                CompanyProfileField.key.in_(payment_keys + payment_keys_with_suffix)
            ).all()
        else:
            fields = session.query(CompanyProfileField).filter(
                CompanyProfileField.company_id == company_id,
                CompanyProfileField.key.like(f'payment_%_{group_index}')
            ).all()
        
        print(f"[DEBUG] Удаление группы {group_index}, найдено полей: {len(fields)}")
        
        # ✅ Собираем все QR файлы для удаления
        qr_file_ids = []
        for field in fields:
            if field.key.startswith('payment_qr'):
                import re
                match = re.search(r'/api/files/public/(\d+)', field.value)
                if match:
                    file_id = int(match.group(1))
                    qr_file_ids.append(file_id)
                    print(f"[DEBUG] Найден QR файл для удаления: {file_id}")
        
        # ✅ Удаляем поля
        for field in fields:
            print(f"[DEBUG] Удаляем поле: {field.key}")
            session.delete(field)
            deleted_count += 1
        
        # ✅ Удаляем файлы QR из StoredFile
        for file_id in qr_file_ids:
            file_record = session.query(StoredFile).filter_by(
                id=file_id,
                company_id=company_id
            ).first()
            if file_record:
                company = session.query(Company).filter_by(id=company_id).first()
                if company:
                    company.storage_used_bytes = max(0, company.storage_used_bytes - file_record.size_bytes)
                
                session.delete(file_record)
                deleted_files.append(file_id)
                print(f"[DEBUG] Удален файл QR: {file_id}")
            else:
                print(f"[DEBUG] Файл {file_id} не найден в StoredFile")
        
        session.commit()
        
        return jsonify({
            "status": "ok",
            "message": f"Удалено {deleted_count} полей и {len(deleted_files)} файлов",
            "deleted_count": deleted_count,
            "deleted_files": deleted_files
        }), 200
        
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка удаления: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# ПОЛУЧЕНИЕ ВСЕХ ПЛАТЕЖНЫХ РЕКВИЗИТОВ
# ============================================
@requisite_bp.route("/requisite/payment/all", methods=["GET"])
@token_required
def get_all_payment_requisites():
    """Получить все платежные реквизиты компании"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    session = get_session()
    try:
        fields = session.query(CompanyProfileField).filter_by(company_id=company_id).all()
        
        payment_keys = ['payment_holder', 'payment_bank', 'payment_bik', 
                       'payment_account', 'payment_kbe', 'payment_kno',
                       'payment_link', 'payment_currency', 'payment_qr']
        payment_fields = []
        
        for field in fields:
            key = field.key
            is_payment = any(key == pk or key.startswith(pk + '_') for pk in payment_keys)
            if is_payment:
                # ✅ Расшифровываем значение
                decrypted_value = decrypt_field_value(key, field.value)
                payment_fields.append({
                    "key": field.key,
                    "value": decrypted_value,
                    "required": field.required
                })
        
        # Группируем по индексам
        groups = {}
        for field in payment_fields:
            key = field['key']
            match = re.match(r'payment_(\w+)_(\d+)', key)
            if match:
                field_type = match.group(1)
                group_index = match.group(2)
                if group_index not in groups:
                    groups[group_index] = {}
                groups[group_index][field_type] = field['value']
            else:
                if '0' not in groups:
                    groups['0'] = {}
                field_type = key.replace('payment_', '')
                groups['0'][field_type] = field['value']
        
        return jsonify({
            "status": "ok",
            "data": {
                "groups": groups,
                "total_groups": len(groups),
                "fields": payment_fields
            }
        }), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# ПОЛУЧЕНИЕ ГРУПП ПЛАТЕЖНЫХ РЕКВИЗИТОВ
# ============================================
@requisite_bp.route("/requisite/payment/groups", methods=["GET"])
@token_required
def get_payment_groups():
    """Получить все группы платежных реквизитов"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    session = get_session()
    try:
        fields = session.query(CompanyProfileField).filter_by(company_id=company_id).all()
        
        payment_keys = [
            'payment_holder', 'payment_bank', 'payment_bik', 
            'payment_account', 'payment_kbe', 'payment_kno',
            'payment_link', 'payment_currency', 'payment_qr'
        ]
        groups = {}
        
        for field in fields:
            key = field.key
            is_payment = any(key == pk or key.startswith(pk + '_') for pk in payment_keys)
            
            if is_payment:
                import re
                match = re.match(r'payment_(\w+)_(\d+)', key)
                if match:
                    field_type = match.group(1)
                    group_index = int(match.group(2))
                    if group_index not in groups:
                        groups[group_index] = {}
                    # ✅ Расшифровываем значение
                    groups[group_index][field_type] = decrypt_field_value(key, field.value)
                else:
                    if 0 not in groups:
                        groups[0] = {}
                    field_type = key.replace('payment_', '')
                    groups[0][field_type] = decrypt_field_value(key, field.value)
        
        return jsonify({
            "status": "ok",
            "data": {
                "groups": groups,
                "total_groups": len(groups)
            }
        }), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# ЗАГРУЗКА ЛОГОТИПА КОМПАНИИ
# ============================================
@requisite_bp.route("/requisite/upload-logo", methods=["POST"])
@token_required
def upload_company_logo():
    """Загрузить логотип компании в БД"""
    import hashlib
    import time
    
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    user_id = int(payload.get("user_id") or 0) if payload.get("user_id") else None
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    if 'logo' not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400
    
    file = request.files['logo']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No file selected"}), 400
    
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
    extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if extension not in allowed_extensions:
        return jsonify({"status": "error", "message": "Неподдерживаемый формат файла"}), 400
    
    session = get_session()
    try:
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404
        
        file_data = file.read()
        file_size = len(file_data)
        
        limit_bytes = int(company.storage_limit_mb) * 1024 * 1024
        used = int(company.storage_used_bytes or 0)
        
        if used + file_size > limit_bytes:
            return jsonify({
                "status": "error",
                "message": "Storage limit exceeded",
                "limit_mb": int(company.storage_limit_mb),
                "used_bytes": used,
                "file_size_bytes": file_size
            }), 413
        
        old_logo_file_id = company.logo_file_id
        old_logo_size = 0
        
        if old_logo_file_id:
            old_logo = session.query(StoredFile).filter_by(
                id=old_logo_file_id,
                company_id=company_id
            ).first()
            if old_logo:
                old_logo_size = old_logo.size_bytes
                company.logo_file_id = None
                company.storage_used_bytes = used - old_logo_size
                session.flush()
        
        sha256 = hashlib.sha256(file_data).hexdigest()
        
        stored_file = StoredFile(
            company_id=company_id,
            uploader_user_id=user_id,
            filename=file.filename,
            mime_type=file.mimetype or "image/png",
            size_bytes=file_size,
            sha256=sha256,
            data=file_data,
            created_ts_ms=int(time.time() * 1000)
        )
        session.add(stored_file)
        session.flush()
        
        company.logo_file_id = stored_file.id
        company.storage_used_bytes = (used - old_logo_size) + file_size
        
        if old_logo_file_id:
            old_logo = session.query(StoredFile).filter_by(
                id=old_logo_file_id,
                company_id=company_id
            ).first()
            if old_logo:
                session.delete(old_logo)
        
        session.commit()
        
        logo_url = f"/api/files/{stored_file.id}"
        
        return jsonify({
            "status": "ok",
            "message": "Логотип загружен",
            "data": {
                "logo_path": logo_url,
                "file_id": stored_file.id,
                "filename": stored_file.filename,
                "size_bytes": stored_file.size_bytes
            }
        }), 200
        
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка загрузки логотипа: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# ЗАГРУЗКА QR КОДА ДЛЯ СЧЕТА
# ============================================
@requisite_bp.route("/requisite/payment/upload-qr", methods=["POST"])
@token_required
def upload_payment_qr():
    """Загрузить QR код для платежного реквизита"""
    import hashlib
    import time
    import re
    
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    user_id = int(payload.get("user_id") or 0) if payload.get("user_id") else None
    
    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400
    
    if 'qr' not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400
    
    file = request.files['qr']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No file selected"}), 400
    
    group_index = request.form.get('group_index', '0')
    if not group_index:
        group_index = '0'
    
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if extension not in allowed_extensions:
        return jsonify({"status": "error", "message": "Неподдерживаемый формат файла"}), 400
    
    session = get_session()
    try:
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404
        
        # ✅ Если group_index == 'new' - определяем следующий индекс
        if group_index == 'new':
            all_fields = session.query(CompanyProfileField).filter_by(company_id=company_id).all()
            max_idx = -1
            has_group_0 = False
            payment_keys = ['payment_holder', 'payment_bank', 'payment_bik', 
                           'payment_account', 'payment_kbe', 'payment_kno',
                           'payment_link', 'payment_currency', 'payment_qr']
            
            for field in all_fields:
                if field.key in payment_keys:
                    has_group_0 = True
                    continue
                match = re.match(r'payment_\w+_(\d+)', field.key)
                if match:
                    idx = int(match.group(1))
                    if idx > max_idx:
                        max_idx = idx
            
            if has_group_0:
                new_index = max(1, max_idx + 1)
            else:
                new_index = 0
            
            group_index = str(new_index)
            print(f"[DEBUG] new -> создаем новую группу с индексом: {group_index}")
        
        # ✅ Проверяем, есть ли уже QR для этой группы
        key = f"payment_qr_{group_index}" if group_index != '0' else "payment_qr"
        existing_qr = session.query(CompanyProfileField).filter_by(
            company_id=company_id,
            key=key
        ).first()
        
        old_file_id = None
        old_file_size = 0
        
        # ✅ Если есть старый QR - получаем его file_id и удаляем
        if existing_qr and existing_qr.value:
            import re
            match = re.search(r'/api/files/public/(\d+)', existing_qr.value)
            if match:
                old_file_id = int(match.group(1))
                old_file = session.query(StoredFile).filter_by(
                    id=old_file_id,
                    company_id=company_id
                ).first()
                if old_file:
                    old_file_size = old_file.size_bytes
                    session.delete(old_file)
                    print(f"[DEBUG] Удален старый QR файл: {old_file_id}")
                else:
                    print(f"[DEBUG] Старый файл {old_file_id} не найден в StoredFile")
        
        # Читаем данные нового файла
        file_data = file.read()
        file_size = len(file_data)
        
        # Проверяем лимит хранилища
        limit_bytes = int(company.storage_limit_mb) * 1024 * 1024
        used = int(company.storage_used_bytes or 0)
        
        if used + file_size - old_file_size > limit_bytes:
            return jsonify({
                "status": "error",
                "message": "Storage limit exceeded",
                "limit_mb": int(company.storage_limit_mb),
                "used_bytes": used,
                "file_size_bytes": file_size,
                "old_file_size": old_file_size
            }), 413
        
        sha256 = hashlib.sha256(file_data).hexdigest()
        
        stored_file = StoredFile(
            company_id=company_id,
            uploader_user_id=user_id,
            filename=file.filename,
            mime_type=file.mimetype or "image/png",
            size_bytes=file_size,
            sha256=sha256,
            data=file_data,
            created_ts_ms=int(time.time() * 1000)
        )
        session.add(stored_file)
        session.flush()
        
        qr_path = f"/api/files/public/{stored_file.id}"
        
        if existing_qr:
            existing_qr.value = qr_path
            print(f"[DEBUG] Обновлен QR: {key} -> {qr_path}")
        else:
            new_qr = CompanyProfileField(
                company_id=company_id,
                key=key,
                value=qr_path,
                required=False
            )
            session.add(new_qr)
            print(f"[DEBUG] Создан QR: {key} -> {qr_path}")
        
        company.storage_used_bytes = used + file_size - old_file_size
        
        session.commit()
        
        return jsonify({
            "status": "ok",
            "message": "QR код загружен",
            "data": {
                "qr_path": qr_path,
                "file_id": stored_file.id,
                "filename": stored_file.filename,
                "size_bytes": stored_file.size_bytes,
                "group_index": group_index,
                "old_file_deleted": old_file_id is not None
            }
        }), 200
        
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Ошибка загрузки QR: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()