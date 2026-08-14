# -*- coding: utf-8 -*-
import logging
import os
import threading
import time

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from server.extensions import socketio

# ✅ Импортируем модели ДО создания приложения
from db.connection import init_db, engine
from db.models import Base

# Импорты блюпринтов
from login.login import login_bp
from server.update import update_bp
from server.employees import employees_bp
from server.upload import upload_bp
from server.mail.mail_bp import mail_bp
from server.mail.watcher import start_watcher
from server.files import files_bp
from server.department.department_bp import departments_bp
from server.crm.Automator.worker import start_automator_worker
from server.crm.clients_bp import crm_clients_bp
from server.crm.settings_bp import crm_settings_bp
from server.crm.fields_bp import crm_fields_bp
from server.crm.card_bp import crm_card_bp
from server.crm.pipelines_bp import pipelines_bp
from server.crm.routing_bp import routing_bp
from server.tasks.tasks_bp import tasks_bp
from server.notes.notes_bp import notes_bp
from server.warehouse.inventory_bp import inventory_bp
from server.department.regions_bp import regions_bp
from server.crm.Automator.automator_bp import automator_bp
from server.Weather.routes import weather_bp
from server.telegram.telegram_bp import telegram_bp
from server.whatsapp.whatsapp_proxy_bp import whatsapp_proxy_bp

from server.crm.Automator.auto_import_bp import auto_import_bp
from server.company.requisite_bp import requisite_bp
from server.company.counterparty.counterparty_bp import counterparty_bp
from server.company.distributor.distributor_bp import distributor_bp
from server.company.list_of_companies.list_of_companies import list_of_companies_bp

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)


def create_tables_async(app):
    """Фоновое создание таблиц (не блокирует запуск)"""
    def _create():
        try:
            with app.app_context():
                logging.info("🔄 Starting database initialization...")
                init_db()
                Base.metadata.create_all(bind=engine)
                logging.info("✅ Database tables created successfully")
        except Exception as e:
            logging.error(f"❌ Database initialization error: {e}")
            import traceback
            traceback.print_exc()
    
    thread = threading.Thread(target=_create)
    thread.daemon = True
    thread.start()
    logging.info("🚀 Database initialization started in background")


def create_app():
    app = Flask(__name__)
    CORS(app)
    socketio.init_app(app)

    # ✅ JWT настройки (ДО блюпринтов)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "CHANGE_ME")
    app.config["JWT_ALGORITHM"] = os.getenv("JWT_ALGORITHM", "HS256")

    # ✅ Инициализация БД в фоновом режиме
    create_tables_async(app)

    # Регистрация блюпринтов
    app.register_blueprint(login_bp, url_prefix="/api/auth")
    app.register_blueprint(update_bp, url_prefix="/api/update")
    app.register_blueprint(employees_bp, url_prefix="/api/employees")
    app.register_blueprint(upload_bp, url_prefix="/api/upload")
    app.register_blueprint(mail_bp, url_prefix="/api/mail")
    app.register_blueprint(whatsapp_proxy_bp, url_prefix="/api/whatsapp")
    app.register_blueprint(files_bp, url_prefix="/api/files")
    app.register_blueprint(departments_bp, url_prefix="/api/departments")
    app.register_blueprint(crm_clients_bp, url_prefix="/api/crm")
    app.register_blueprint(crm_settings_bp, url_prefix="/api/crm")
    app.register_blueprint(crm_fields_bp, url_prefix="/api/crm")
    app.register_blueprint(crm_card_bp, url_prefix="/api/crm")
    app.register_blueprint(pipelines_bp, url_prefix="/api/crm")
    app.register_blueprint(routing_bp, url_prefix="/api/crm")
    app.register_blueprint(tasks_bp, url_prefix="/api/tasks")
    app.register_blueprint(notes_bp, url_prefix="/api/notes")
    app.register_blueprint(inventory_bp, url_prefix="/api/inventory")
    app.register_blueprint(regions_bp, url_prefix="/api/regions")
    app.register_blueprint(automator_bp, url_prefix="/api/crm")
    app.register_blueprint(weather_bp, url_prefix='/api/weather')
    app.register_blueprint(telegram_bp, url_prefix="/api/telegram")

    app.register_blueprint(auto_import_bp, url_prefix="/api")
    app.register_blueprint(requisite_bp, url_prefix="/api/company")
    app.register_blueprint(counterparty_bp)
    app.register_blueprint(distributor_bp)
    app.register_blueprint(list_of_companies_bp)

    # Запуск фоновых сервисов (тоже в потоках)
    try:
        start_watcher()
        logging.info("✅ Mail watcher started")
    except Exception as e:
        logging.error(f"❌ Mail watcher error: {e}")

    try:
        start_automator_worker()
        logging.info("✅ Automator worker started")
    except Exception as e:
        logging.error(f"❌ Automator worker error: {e}")

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "message": "Server is running"}), 200

    # Эндпоинт для проверки статуса БД
    @app.route("/api/db-status", methods=["GET"])
    def db_status():
        try:
            from db.connection import get_session
            session = get_session()
            result = session.execute("SELECT 1").fetchone()
            session.close()
            if result:
                return jsonify({"status": "ok", "message": "Database connected"}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # Создание директории для загрузок
    upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    @app.route("/uploads/<path:path>")
    def serve_uploads(path):
        return send_from_directory(upload_dir, path)

    # Обработка 404
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"status": "error", "message": "Endpoint not found"}), 404

    return app


  
app = create_app()

if __name__ == '__main__':
    # Считываем порт, который дал Google Cloud. Если его нет — используем 8080.
    run_port = int(os.environ.get("PORT", 8080))
    
    # Передаем этот порт в socketio.run
    socketio.run(
        app,
        host='0.0.0.0', 
        port=run_port,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True
    )
