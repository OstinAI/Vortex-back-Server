# -*- coding: utf-8 -*-
"""
Автоматический импорт компаний в CRM
"""
import time
import threading
from db.connection import get_session
from db.models import Company, User, Client, CRMFieldDefinition, CRMFieldValue, Note, SystemSetting

# ID компании Vortex - УБЕДИТЕСЬ ЧТО ЭТО ПРАВИЛЬНЫЙ ID
VORTEX_COMPANY_ID = 2

# Настройки
AUTO_IMPORT_SETTINGS = {
    'pipeline_id': None,
    'stage_id': None,
}
_automation_enabled = False


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ensure_system_settings_table():
    """Создать таблицу system_settings если ее нет"""
    session = get_session()
    try:
        from sqlalchemy import text
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS system_settings (
                id SERIAL PRIMARY KEY,
                key VARCHAR(255) UNIQUE NOT NULL,
                value TEXT NOT NULL,
                created_ts_ms BIGINT,
                updated_ts_ms BIGINT
            )
        """))
        session.commit()
        print('[AUTO_IMPORT] ✅ Таблица system_settings создана/существует')
    except Exception as e:
        print(f'[AUTO_IMPORT] Ошибка создания таблицы: {e}')
    finally:
        session.close()


def get_vortex_company_id():
    """Получить ID компании Vortex из БД"""
    session = get_session()
    try:
        vortex = session.query(Company).filter(Company.name.ilike('%vortex%')).first()
        if vortex:
            return vortex.id
        # Если нет компании с именем Vortex, пробуем найти первую компанию
        first = session.query(Company).order_by(Company.id.asc()).first()
        if first:
            return first.id
        return 1
    except Exception as e:
        print(f'[AUTO_IMPORT] Ошибка получения ID Vortex: {e}')
        return 2
    finally:
        session.close()


def load_automation_settings():
    """Загрузка настроек из БД"""
    global AUTO_IMPORT_SETTINGS, _automation_enabled, VORTEX_COMPANY_ID
    
    # Определяем ID компании Vortex
    VORTEX_COMPANY_ID = get_vortex_company_id()
    print(f'[AUTO_IMPORT] ID компании Vortex: {VORTEX_COMPANY_ID}')
    
    _ensure_system_settings_table()
    
    session = get_session()
    try:
        pipeline_setting = session.query(SystemSetting).filter_by(key='auto_import_pipeline_id').first()
        if pipeline_setting:
            AUTO_IMPORT_SETTINGS['pipeline_id'] = int(pipeline_setting.value)
            print(f'[AUTO_IMPORT] Загружена воронка: {AUTO_IMPORT_SETTINGS["pipeline_id"]}')
        else:
            from db.models import Pipeline
            first_pipeline = session.query(Pipeline).filter_by(company_id=VORTEX_COMPANY_ID).first()
            if first_pipeline:
                AUTO_IMPORT_SETTINGS['pipeline_id'] = first_pipeline.id
                setting = SystemSetting(key='auto_import_pipeline_id', value=str(first_pipeline.id),
                                        created_ts_ms=_now_ms(), updated_ts_ms=_now_ms())
                session.merge(setting)
                session.commit()
                print(f'[AUTO_IMPORT] Установлена первая воронка: {first_pipeline.id}')
        
        stage_setting = session.query(SystemSetting).filter_by(key='auto_import_stage_id').first()
        if stage_setting:
            AUTO_IMPORT_SETTINGS['stage_id'] = int(stage_setting.value)
            print(f'[AUTO_IMPORT] Загружен этап: {AUTO_IMPORT_SETTINGS["stage_id"]}')
        else:
            if AUTO_IMPORT_SETTINGS.get('pipeline_id'):
                from db.models import PipelineStage
                first_stage = session.query(PipelineStage).filter_by(
                    pipeline_id=AUTO_IMPORT_SETTINGS['pipeline_id'],
                    is_enabled=True
                ).first()
                if first_stage:
                    AUTO_IMPORT_SETTINGS['stage_id'] = first_stage.id
                    setting = SystemSetting(key='auto_import_stage_id', value=str(first_stage.id),
                                            created_ts_ms=_now_ms(), updated_ts_ms=_now_ms())
                    session.merge(setting)
                    session.commit()
                    print(f'[AUTO_IMPORT] Установлен первый этап: {first_stage.id}')
        
        enabled_setting = session.query(SystemSetting).filter_by(key='auto_import_enabled').first()
        if enabled_setting:
            _automation_enabled = enabled_setting.value.lower() == 'true'
        else:
            if AUTO_IMPORT_SETTINGS.get('pipeline_id') and AUTO_IMPORT_SETTINGS.get('stage_id'):
                _automation_enabled = True
                setting = SystemSetting(key='auto_import_enabled', value='true',
                                        created_ts_ms=_now_ms(), updated_ts_ms=_now_ms())
                session.merge(setting)
                session.commit()
                print('[AUTO_IMPORT] Автоматизация включена по умолчанию')
        
        print(f'[AUTO_IMPORT] Настройки: pipeline_id={AUTO_IMPORT_SETTINGS["pipeline_id"]}, '
              f'stage_id={AUTO_IMPORT_SETTINGS["stage_id"]}, enabled={_automation_enabled}')
        
    except Exception as e:
        print(f'[AUTO_IMPORT] Ошибка загрузки настроек: {e}')
        import traceback
        traceback.print_exc()
    finally:
        session.close()


def save_automation_settings(pipeline_id=None, stage_id=None, enabled=None):
    """Сохранение настроек автоматизации"""
    global AUTO_IMPORT_SETTINGS, _automation_enabled
    
    _ensure_system_settings_table()
    
    session = get_session()
    try:
        if pipeline_id is not None:
            setting = session.query(SystemSetting).filter_by(key='auto_import_pipeline_id').first()
            if setting:
                setting.value = str(pipeline_id)
                setting.updated_ts_ms = _now_ms()
            else:
                setting = SystemSetting(key='auto_import_pipeline_id', value=str(pipeline_id),
                                        created_ts_ms=_now_ms(), updated_ts_ms=_now_ms())
                session.add(setting)
            AUTO_IMPORT_SETTINGS['pipeline_id'] = pipeline_id
        
        if stage_id is not None:
            setting = session.query(SystemSetting).filter_by(key='auto_import_stage_id').first()
            if setting:
                setting.value = str(stage_id)
                setting.updated_ts_ms = _now_ms()
            else:
                setting = SystemSetting(key='auto_import_stage_id', value=str(stage_id),
                                        created_ts_ms=_now_ms(), updated_ts_ms=_now_ms())
                session.add(setting)
            AUTO_IMPORT_SETTINGS['stage_id'] = stage_id
        
        if enabled is not None:
            setting = session.query(SystemSetting).filter_by(key='auto_import_enabled').first()
            if setting:
                setting.value = 'true' if enabled else 'false'
                setting.updated_ts_ms = _now_ms()
            else:
                setting = SystemSetting(key='auto_import_enabled', value='true' if enabled else 'false',
                                        created_ts_ms=_now_ms(), updated_ts_ms=_now_ms())
                session.add(setting)
            _automation_enabled = enabled
        
        session.commit()
        print(f'[AUTO_IMPORT] Настройки сохранены: pipeline_id={AUTO_IMPORT_SETTINGS["pipeline_id"]}, '
              f'stage_id={AUTO_IMPORT_SETTINGS["stage_id"]}, enabled={_automation_enabled}')
        
        return True
    except Exception as e:
        session.rollback()
        print(f'[AUTO_IMPORT] Ошибка сохранения настроек: {e}')
        return False
    finally:
        session.close()


def is_automation_enabled() -> bool:
    """Проверить, включена ли автоматизация"""
    global _automation_enabled
    if AUTO_IMPORT_SETTINGS['pipeline_id'] is None:
        load_automation_settings()
    return _automation_enabled


def get_or_create_crm_field(session, vortex_company_id, field_key, field_title, field_type='text', is_system_admin=False):
    """
    Получить существующее поле CRM или создать новое
    
    Args:
        session: Сессия БД
        vortex_company_id: ID компании Vortex
        field_key: Ключ поля
        field_title: Название поля
        field_type: Тип поля
        is_system_admin: Является ли поле системным административным
    """
    # Ищем по ключу
    field = session.query(CRMFieldDefinition).filter_by(
        company_id=vortex_company_id,
        scope_type='company',
        scope_id=0,
        key=field_key,
        is_enabled=True
    ).first()
    
    if field:
        return field
    
    # Ищем по названию
    field = session.query(CRMFieldDefinition).filter_by(
        company_id=vortex_company_id,
        scope_type='company',
        scope_id=0,
        title=field_title,
        is_enabled=True
    ).first()
    
    if field:
        return field
    
    # Создаем новое поле
    if is_system_admin:
        # 🔐 ДОБАВЛЯЕМ ЭМОДЗИ В НАЗВАНИЕ ПОЛЯ ДЛЯ ВИЗУАЛЬНОЙ ПОМЕТКИ
        display_title = f"🔐 {field_title}"
        display_key = f"admin_{field_key}"
    else:
        display_title = field_title
        display_key = field_key
    
    new_field = CRMFieldDefinition(
        company_id=vortex_company_id,
        scope_type='company',
        scope_id=0,
        key=display_key,
        title=display_title,  # ← Здесь будет 🔐 для системных полей
        type=field_type,
        required=False,
        order_index=0,
        is_enabled=True,
        created_ts_ms=_now_ms()
    )
    session.add(new_field)
    session.flush()
    print(f'[AUTO_IMPORT] Создано поле: {display_title} (key={display_key})')
    return new_field


def set_crm_field_value(session, vortex_company_id, client_id, field, value):
    """Установить значение поля CRM"""
    if not value:
        return
    
    existing_value = session.query(CRMFieldValue).filter_by(
        company_id=vortex_company_id,
        client_id=client_id,
        field_id=field.id
    ).first()
    
    if existing_value:
        existing_value.value_text = str(value)
        existing_value.updated_ts_ms = _now_ms()
    else:
        new_value = CRMFieldValue(
            company_id=vortex_company_id,
            client_id=client_id,
            field_id=field.id,
            value_text=str(value),
            updated_ts_ms=_now_ms()
        )
        session.add(new_value)


def import_company_to_crm(company_id: int, vortex_company_id: int = None):
    """Импорт одной компании в CRM"""
    global VORTEX_COMPANY_ID
    
    if vortex_company_id is None:
        vortex_company_id = VORTEX_COMPANY_ID
    
    if AUTO_IMPORT_SETTINGS['pipeline_id'] is None or AUTO_IMPORT_SETTINGS['stage_id'] is None:
        load_automation_settings()
    
    if not _automation_enabled:
        print(f'[AUTO_IMPORT] Автоматизация отключена, пропускаем компанию {company_id}')
        return False
    
    pipeline_id = AUTO_IMPORT_SETTINGS.get('pipeline_id')
    stage_id = AUTO_IMPORT_SETTINGS.get('stage_id')
    
    if not pipeline_id or not stage_id:
        print(f'[AUTO_IMPORT] Не настроена воронка или этап')
        return False
    
    session = get_session()
    try:
        company = session.query(Company).filter_by(id=company_id).first()
        if not company:
            print(f'[AUTO_IMPORT] Компания {company_id} не найдена')
            return False
        
        company_name = company.name
        print(f'[AUTO_IMPORT] Импорт компании: "{company_name}" (ID={company_id})')
        
        # Проверяем, уже есть ли такая компания в CRM
        existing_client = session.query(Client).filter(
            Client.company_id == vortex_company_id,
            Client.name == f"КОМПАНИЯ {company_name}"
        ).first()
        
        if existing_client:
            print(f'[AUTO_IMPORT] Компания "{company_name}" уже есть в CRM (client_id={existing_client.id})')
            session.close()
            return True
        
        # Получаем администратора
        admin = session.query(User).filter_by(company_id=company_id, role='Admin').first()
        admin_username = admin.username if admin else ''
        admin_full_name = admin.full_name if admin else ''
        admin_email = admin.email if admin else ''
        
        # Получаем поля компании
        company_bin = getattr(company, 'bin', '') or ''
        company_phone = getattr(company, 'phone', '') or ''
        company_website = getattr(company, 'website', '') or ''
        company_address = getattr(company, 'address', '') or ''
        company_slogan = getattr(company, 'slogan', '') or ''
        
        # Создаем клиента
        client = Client(
            company_id=vortex_company_id,
            name=f"КОМПАНИЯ {company_name}",
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            status="active",
            created_ts_ms=_now_ms()
        )
        session.add(client)
        session.flush()
        
        client_id = client.id
        print(f'[AUTO_IMPORT] Создан клиент ID={client_id}')
        
        # ============================================================
        # МАППИНГ ПОЛЕЙ
        # ============================================================
        
        # 🔵 ОБЫЧНЫЕ ПОЛЯ КОМПАНИИ (без пометки)
        fields_to_import = [
            ('company_name', 'Название компании', company_name, 'text', False),
            ('company_slogan', 'Слоган', company_slogan, 'text', False),
            ('company_bin', 'БИН', company_bin, 'text', False),
            ('company_phone', 'Телефон', company_phone, 'text', False),
            ('company_website', 'Веб-сайт', company_website, 'text', False),
            ('company_address', 'Адрес', company_address, 'text', False),
        ]
        
        # 🔐 СИСТЕМНЫЕ АДМИНИСТРАТИВНЫЕ ПОЛЯ (с пометкой 🔐 в названии)
        admin_fields = [
            ('username', 'Логин администратора', admin_username, 'text', True),
            ('full_name', 'Имя администратора', admin_full_name, 'text', True),
            ('email', 'Email администратора', admin_email, 'text', True),
        ]
        
        # Импортируем обычные поля
        for field_key, field_title, field_value, field_type, is_system_admin in fields_to_import:
            if not field_value:
                continue
            
            field = get_or_create_crm_field(
                session, 
                vortex_company_id, 
                field_key, 
                field_title, 
                field_type,
                is_system_admin=False
            )
            set_crm_field_value(session, vortex_company_id, client_id, field, field_value)
        
        # Импортируем системные административные поля (с 🔐 в названии)
        for field_key, field_title, field_value, field_type, is_system_admin in admin_fields:
            if not field_value:
                continue
            
            field = get_or_create_crm_field(
                session, 
                vortex_company_id, 
                field_key, 
                field_title, 
                field_type,
                is_system_admin=True  # 🔐 Создаст поле с названием "🔐 Логин администратора"
            )
            set_crm_field_value(session, vortex_company_id, client_id, field, field_value)
        
        # Заметка с информацией
        note_description = (
            f"Автоматический импорт из компании ID: {company_id}, название: {company_name}\n"
            f"🔐 Поля с эмодзи 🔐 - системные административные"
        )
        note = Note(
            company_id=vortex_company_id,
            client_id=client_id,
            description=note_description,
            type="system",
            created_ts_ms=_now_ms(),
            updated_ts_ms=_now_ms()
        )
        session.add(note)
        
        session.commit()
        session.close()
        
        print(f'[AUTO_IMPORT] ✅ Компания "{company_name}" импортирована в CRM (client_id={client_id})')
        print(f'[AUTO_IMPORT]    🔐 Системные админ-поля отмечены эмодзи 🔐')
        return True
        
    except Exception as e:
        session.rollback()
        session.close()
        print(f'[AUTO_IMPORT] ❌ Ошибка импорта компании {company_id}: {e}')
        import traceback
        traceback.print_exc()
        return False


def debug_crm_fields(vortex_company_id: int = None):
    """Отладка: вывести все поля CRM"""
    if vortex_company_id is None:
        vortex_company_id = VORTEX_COMPANY_ID
    
    session = get_session()
    try:
        fields = session.query(CRMFieldDefinition).filter_by(
            company_id=vortex_company_id,
            scope_type='company',
            scope_id=0,
            is_enabled=True
        ).all()
        
        print(f"\n[DEBUG] Найдено полей CRM: {len(fields)}")
        print("-" * 70)
        print(f"  {'ID':>3} | {'Key':<30} | {'Title'}")
        print("-" * 70)
        for field in fields:
            print(f"  {field.id:>3} | {field.key:<30} | {field.title}")
        print("-" * 70)
        
        return fields
    except Exception as e:
        print(f"[DEBUG] Ошибка: {e}")
        return []
    finally:
        session.close()


def auto_import_all_new_companies():
    """Импортировать все новые компании"""
    global VORTEX_COMPANY_ID
    
    if not _automation_enabled:
        print('[AUTO_IMPORT] Автоматизация отключена')
        return 0
    
    pipeline_id = AUTO_IMPORT_SETTINGS.get('pipeline_id')
    stage_id = AUTO_IMPORT_SETTINGS.get('stage_id')
    
    if not pipeline_id or not stage_id:
        print('[AUTO_IMPORT] Не настроена воронка или этап')
        return 0
    
    session = get_session()
    try:
        companies_data = []
        companies = session.query(Company).order_by(Company.id.asc()).all()
        
        for c in companies:
            companies_data.append({
                'id': c.id,
                'name': c.name
            })
        
        clients = session.query(Client).filter_by(company_id=VORTEX_COMPANY_ID).all()
        
        imported_names = set()
        for client in clients:
            if client.name and client.name.startswith('КОМПАНИЯ '):
                imported_names.add(client.name.replace('КОМПАНИЯ ', '').upper())
        
        session.close()
        
        new_companies = []
        for c_data in companies_data:
            if c_data['name'].upper() not in imported_names:
                new_companies.append(c_data)
        
        if not new_companies:
            print('[AUTO_IMPORT] Новых компаний нет')
            return 0
        
        print(f'[AUTO_IMPORT] Найдено {len(new_companies)} новых компаний')
        
        imported_count = 0
        for c_data in new_companies:
            try:
                if import_company_to_crm(c_data['id'], VORTEX_COMPANY_ID):
                    imported_count += 1
            except Exception as e:
                print(f'[AUTO_IMPORT] Ошибка импорта {c_data["name"]}: {e}')
        
        print(f'[AUTO_IMPORT] Импортировано {imported_count} компаний')
        return imported_count
        
    except Exception as e:
        session.close()
        print(f'[AUTO_IMPORT] Ошибка: {e}')
        import traceback
        traceback.print_exc()
        return 0


# Загружаем настройки при старте
print('[AUTO_IMPORT] Загрузка настроек...')
load_automation_settings()
print(f'[AUTO_IMPORT] Модуль загружен. Автоматизация: {"ВКЛ" if _automation_enabled else "ВЫКЛ"}')