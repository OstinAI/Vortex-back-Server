# -*- coding: utf-8 -*-
"""
API для управления автоматическим импортом компаний
"""
from flask import Blueprint, request, jsonify
from utils.security import token_required
from db.connection import get_session
from db.models import Company

from server.crm.Automator.auto_import import (
    load_automation_settings,
    save_automation_settings,
    is_automation_enabled,
    import_company_to_crm,
    auto_import_all_new_companies,
    get_vortex_company_id,
    debug_crm_fields
)

# Создаем Blueprint
auto_import_bp = Blueprint('auto_import', __name__)


@auto_import_bp.route('/auto_import/status', methods=['GET', 'OPTIONS'])
@token_required
def get_auto_import_status():
    """Получить статус автоматизации"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    payload = request.user
    company_id = int(payload.get('company_id') or payload.get('companyId') or 0)
    role = str(payload.get('role') or "")
    
    session = get_session()
    try:
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            session.close()
            return jsonify({'error': 'COMPANY_NOT_FOUND'}), 404
        
        company_name = company.name.lower()
        
        # Разрешаем доступ для компании Vortex или для ролей Integrator/Admin
        is_vortex = "vortex" in company_name
        is_admin = role in ("Integrator", "Admin")
        
        if not is_vortex and not is_admin:
            session.close()
            return jsonify({'error': 'ACCESS_DENIED'}), 403
        
        load_automation_settings()
        from server.crm.Automator.auto_import import AUTO_IMPORT_SETTINGS, _automation_enabled
        
        session.close()
        return jsonify({
            'enabled': _automation_enabled,
            'pipeline_id': AUTO_IMPORT_SETTINGS.get('pipeline_id'),
            'stage_id': AUTO_IMPORT_SETTINGS.get('stage_id')
        }), 200
    except Exception as e:
        session.close()
        return jsonify({'error': str(e)}), 500


@auto_import_bp.route('/auto_import/settings', methods=['POST', 'OPTIONS'])
@token_required
def update_auto_import_settings():
    """Обновить настройки автоматизации"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    payload = request.user
    company_id = int(payload.get('company_id') or payload.get('companyId') or 0)
    role = str(payload.get('role') or "")
    
    session = get_session()
    try:
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            session.close()
            return jsonify({'error': 'COMPANY_NOT_FOUND'}), 404
        
        company_name = company.name.lower()
        
        # Разрешаем доступ для компании Vortex или для ролей Integrator/Admin
        is_vortex = "vortex" in company_name
        is_admin = role in ("Integrator", "Admin")
        
        if not is_vortex and not is_admin:
            session.close()
            return jsonify({'error': 'ACCESS_DENIED'}), 403
        
        data = request.get_json(silent=True) or {}
        
        pipeline_id = data.get('pipeline_id')
        stage_id = data.get('stage_id')
        enabled = data.get('enabled')
        
        print(f'[AUTO_IMPORT_API] Получены настройки: pipeline_id={pipeline_id}, stage_id={stage_id}, enabled={enabled}')
        
        if pipeline_id is not None and stage_id is not None:
            result = save_automation_settings(
                pipeline_id=int(pipeline_id),
                stage_id=int(stage_id),
                enabled=enabled
            )
            if result:
                session.close()
                return jsonify({'status': 'ok', 'message': 'Settings updated'}), 200
            else:
                session.close()
                return jsonify({'error': 'Failed to save settings'}), 500
        else:
            session.close()
            return jsonify({'error': 'pipeline_id and stage_id are required'}), 400
            
    except Exception as e:
        session.close()
        print(f'[AUTO_IMPORT_API] Ошибка: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@auto_import_bp.route('/auto_import/import_all', methods=['POST', 'OPTIONS'])
@token_required
def import_all_companies():
    """Импортировать все новые компании"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    payload = request.user
    company_id = int(payload.get('company_id') or payload.get('companyId') or 0)
    role = str(payload.get('role') or "")
    
    session = get_session()
    try:
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            session.close()
            return jsonify({'error': 'COMPANY_NOT_FOUND'}), 404
        
        company_name = company.name.lower()
        
        is_vortex = "vortex" in company_name
        is_admin = role in ("Integrator", "Admin")
        
        if not is_vortex and not is_admin:
            session.close()
            return jsonify({'error': 'ACCESS_DENIED'}), 403
        
        count = auto_import_all_new_companies()
        session.close()
        return jsonify({'status': 'ok', 'imported': count}), 200
    except Exception as e:
        session.close()
        return jsonify({'error': str(e)}), 500


@auto_import_bp.route('/auto_import/debug_fields', methods=['GET', 'OPTIONS'])
@token_required
def debug_fields():
    """Отладка: показать все поля CRM"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    payload = request.user
    company_id = int(payload.get('company_id') or payload.get('companyId') or 0)
    role = str(payload.get('role') or "")
    
    session = get_session()
    try:
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            session.close()
            return jsonify({'error': 'COMPANY_NOT_FOUND'}), 404
        
        company_name = company.name.lower()
        
        is_vortex = "vortex" in company_name
        is_admin = role in ("Integrator", "Admin")
        
        if not is_vortex and not is_admin:
            session.close()
            return jsonify({'error': 'ACCESS_DENIED'}), 403
        
        vortex_id = get_vortex_company_id()
        fields = debug_crm_fields(vortex_id)
        
        result = []
        for f in fields:
            result.append({
                'id': f.id,
                'key': f.key,
                'title': f.title,
                'type': f.type,
                'required': f.required,
                'enabled': f.is_enabled
            })
        
        session.close()
        return jsonify({
            'status': 'ok',
            'vortex_company_id': vortex_id,
            'fields': result
        }), 200
    except Exception as e:
        session.close()
        return jsonify({'error': str(e)}), 500


@auto_import_bp.route('/auto_import/import_single/<int:company_id>', methods=['POST', 'OPTIONS'])
@token_required
def import_single_company(company_id):
    """Импортировать одну компанию по ID"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    payload = request.user
    user_company_id = int(payload.get('company_id') or payload.get('companyId') or 0)
    role = str(payload.get('role') or "")
    
    session = get_session()
    try:
        company = session.query(Company).filter_by(id=user_company_id).first()
        if not company:
            session.close()
            return jsonify({'error': 'COMPANY_NOT_FOUND'}), 404
        
        company_name = company.name.lower()
        
        is_vortex = "vortex" in company_name
        is_admin = role in ("Integrator", "Admin")
        
        if not is_vortex and not is_admin:
            session.close()
            return jsonify({'error': 'ACCESS_DENIED'}), 403
        
        # Проверяем, существует ли компания для импорта
        target_company = session.query(Company).filter_by(id=company_id).first()
        if not target_company:
            session.close()
            return jsonify({'error': f'Company with ID {company_id} not found'}), 404
        
        session.close()
        
        vortex_id = get_vortex_company_id()
        result = import_company_to_crm(company_id, vortex_id)
        
        return jsonify({
            'status': 'ok' if result else 'error',
            'imported': result,
            'company_id': company_id,
            'company_name': target_company.name
        }), 200
    except Exception as e:
        session.close()
        return jsonify({'error': str(e)}), 500