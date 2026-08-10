# server/crm/Automator/__init__.py
# -*- coding: utf-8 -*-
"""
Модуль автоматизации CRM
"""

# Импортируем только то, что нужно
from server.crm.Automator.auto_import import (
    import_company_to_crm,
    is_automation_enabled,
    load_automation_settings,
    save_automation_settings,
    auto_import_all_new_companies,
)

# Импортируем blueprint отдельно
from server.crm.Automator.auto_import_bp import auto_import_bp

__all__ = [
    'import_company_to_crm',
    'is_automation_enabled',
    'load_automation_settings',
    'save_automation_settings',
    'auto_import_all_new_companies',
    'auto_import_bp'
]