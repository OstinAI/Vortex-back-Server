# -*- coding: utf-8 -*-
import logging
import os

from flask import Flask, jsonify, send_from_directory
from db.connection import init_db
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

from flask_cors import CORS  # <-- ДОБАВИТЬ ЭТО
from server.extensions import socketio  # Импорт из нового файла
from server.Weather.routes import weather_bp

# ✅ proxy blueprint
from server.whatsapp.whatsapp_proxy_bp import whatsapp_proxy_bp

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)


def create_app():
    app = Flask(__name__)
    CORS(app)

    # Привязываем сокеты к приложению
    socketio.init_app(app)

    init_db()

    # ✅ ОДИНАКОВЫЙ JWT СЕКРЕТ С WA-СЕРВЕРОМ
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "CHANGE_ME")
    app.config["JWT_ALGORITHM"] = os.getenv("JWT_ALGORITHM", "HS256")

    app.register_blueprint(login_bp,     url_prefix="/api/auth")
    app.register_blueprint(update_bp,    url_prefix="/api/update")
    app.register_blueprint(employees_bp, url_prefix="/api/employees")
    app.register_blueprint(upload_bp,    url_prefix="/api/upload")
    app.register_blueprint(mail_bp,      url_prefix="/api/mail")

    # ✅ только proxy
    app.register_blueprint(whatsapp_proxy_bp, url_prefix="/api/whatsapp")

    app.register_blueprint(files_bp, url_prefix="/api/files")
    app.register_blueprint(departments_bp, url_prefix="/api/departments")
    app.register_blueprint(crm_clients_bp,   url_prefix="/api/crm")
    app.register_blueprint(crm_settings_bp,  url_prefix="/api/crm")
    app.register_blueprint(crm_fields_bp, url_prefix="/api/crm")
    app.register_blueprint(crm_card_bp,   url_prefix="/api/crm")
    app.register_blueprint(pipelines_bp, url_prefix="/api/crm")
    app.register_blueprint(routing_bp, url_prefix="/api/crm")
    app.register_blueprint(tasks_bp, url_prefix="/api/tasks")
    app.register_blueprint(notes_bp, url_prefix="/api/notes")
    app.register_blueprint(inventory_bp, url_prefix="/api/inventory")
    app.register_blueprint(regions_bp, url_prefix="/api/regions")
    app.register_blueprint(automator_bp, url_prefix="/api/crm")
    app.register_blueprint(weather_bp, url_prefix='/api/weather')

    start_watcher()
    start_automator_worker()

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    @app.route("/uploads/<path:path>")
    def serve_uploads(path):
        return send_from_directory(upload_dir, path)

    return app

if __name__ == '__main__':
    app = create_app()
    # ✅ ВАЖНО: Заменяем app.run на socketio.run
    # Без этого сокеты не будут работать в режиме реального времени
    socketio.run(
        app,
        host='0.0.0.0',
        port=5000,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True
    )