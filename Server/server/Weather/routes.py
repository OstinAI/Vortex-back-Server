from flask import Blueprint, jsonify, request
# .weather_logic — это твой файл с расчетами в этой же папке
from .weather_logic import get_vortex_weather, CITIES 

weather_bp = Blueprint('weather', __name__)

@weather_bp.route("/config", methods=["GET"])
def get_config():
    return jsonify(CITIES)

@weather_bp.route("/current", methods=["GET"])
def current_weather():
    # По умолчанию отдаем Алматы (ID 1)
    text = get_vortex_weather("1") 
    return jsonify({"text": text})

@weather_bp.route("/save", methods=["POST"])
def save_city():
    data = request.get_json()
    city_id = data.get("city_id", "1")
    text = get_vortex_weather(city_id)
    # Здесь можно добавить сохранение в БД, если нужно
    return jsonify({"ok": True, "text": text})