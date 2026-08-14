# -*- coding: utf-8 -*-
"""
Модуль для получения списка всех компаний (только для компании ID=1)
Путь: server/company/list_of_companies/list_of_companies.py
"""

from flask import Blueprint, request, jsonify
from utils.security import token_required
from db.connection import get_session
from db.models import Company, User, Client
from utils.crypto import decrypt

list_of_companies_bp = Blueprint("list_of_companies", __name__, url_prefix="/api/admin")

# ============================================
# ПОЛУЧИТЬ СПИСОК ВСЕХ КОМПАНИЙ
# ============================================
@list_of_companies_bp.route("/companies/all", methods=["GET"])
@token_required
def get_all_companies():
    """Получить список всех компаний (только для компании ID=1)"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    # Только компания с ID=1 имеет доступ
    if company_id != 1:
        return jsonify({"status": "error", "message": "ACCESS_DENIED"}), 403
    
    session = get_session()
    try:
        companies = session.query(Company).order_by(Company.id.asc()).all()
        
        result = []
        for comp in companies:
            # Получаем количество пользователей
            users_count = session.query(User).filter_by(company_id=comp.id).count()
            # Получаем количество клиентов
            clients_count = session.query(Client).filter_by(company_id=comp.id).count()
            
            # Расшифровываем данные
            def safe_decrypt(value):
                if not value:
                    return ""
                try:
                    if value.startswith('gAAAAA'):
                        return decrypt(value)
                    return value
                except:
                    return value
            
            result.append({
                "id": comp.id,
                "name": comp.name,
                "bin": safe_decrypt(comp.bin) if comp.bin else "",
                "phone": safe_decrypt(comp.phone) if comp.phone else "",
                "address": comp.address or "",
                "website": comp.website or "",
                "president": comp.president or "",
                "is_active": comp.is_active,
                "users_count": users_count,
                "clients_count": clients_count,
                "reg_date": comp.reg_date.strftime('%Y-%m-%d') if comp.reg_date else "",
                "ownership_form": comp.ownership_form or "",
                "email": safe_decrypt(comp.company_email) if comp.company_email else "",
                "created_ts_ms": int(comp.id)  # заглушка
            })
        
        return jsonify({
            "status": "ok",
            "data": result,
            "total": len(result)
        }), 200
        
    except Exception as e:
        print(f"[ERROR] Ошибка получения списка компаний: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()



# ============================================
# ПОЛУЧИТЬ ДЕТАЛИ КОМПАНИИ
# ============================================
@list_of_companies_bp.route("/company/<int:target_company_id>/details", methods=["GET"])
@token_required
def get_company_details(target_company_id):
    """Получить детальную информацию о компании (только для компании ID=1)"""
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    
    if company_id != 1:
        return jsonify({"status": "error", "message": "ACCESS_DENIED"}), 403
    
    session = get_session()
    try:
        company = session.query(Company).filter_by(id=target_company_id).first()
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404
        
        users_count = session.query(User).filter_by(company_id=company.id).count()
        clients_count = session.query(Client).filter_by(company_id=company.id).count()
        
        # Расшифровываем данные
        def safe_decrypt(value):
            if not value:
                return ""
            try:
                if value.startswith('gAAAAA'):
                    return decrypt(value)
                return value
            except:
                return value
        
        result = {
            "id": company.id,
            "name": company.name,
            "bin": safe_decrypt(company.bin) if company.bin else "",
            "phone": safe_decrypt(company.phone) if company.phone else "",
            "address": company.address or "",
            "website": company.website or "",
            "president": company.president or "",
            "is_active": company.is_active,
            "users_count": users_count,
            "clients_count": clients_count,
            "reg_date": company.reg_date.strftime('%Y-%m-%d') if company.reg_date else "",
            "ownership_form": company.ownership_form or "",
            "email": safe_decrypt(company.company_email) if company.company_email else "",
            "storage_limit_mb": company.storage_limit_mb,
            "storage_used_bytes": company.storage_used_bytes
        }
        
        return jsonify({
            "status": "ok",
            "data": result
        }), 200
        
    except Exception as e:
        print(f"[ERROR] Ошибка получения деталей компании: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()