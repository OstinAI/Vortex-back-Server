# -*- coding: utf-8 -*-
from flask import Flask, Blueprint, request, jsonify, send_from_directory
import os

app = Flask(__name__)

# ======================================================
#                НАСТРОЙКИ
# ======================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPDATE_DIR = os.path.join(BASE_DIR, "updates")

os.makedirs(UPDATE_DIR, exist_ok=True)

# ======================================================
#          ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ======================================================

def clean_version(v: str) -> str:
    """
    Убираем BOM, пробелы, v/V
    """
    if not v:
        return ""
    return (
        v.replace("\ufeff", "")
         .replace("\u00a0", "")
         .replace("v", "")
         .replace("V", "")
         .strip()
    )


def parse_version(v: str):
    """
    '1.0.10' -> [1,0,10]
    """
    try:
        return [int(x) for x in clean_version(v).split(".")]
    except:
        return [0]


def is_newer(server: str, client: str) -> bool:
    """
    True если server > client
    """
    s = parse_version(server)
    c = parse_version(client)

    max_len = max(len(s), len(c))
    s += [0] * (max_len - len(s))
    c += [0] * (max_len - len(c))

    return s > c


def read_version(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return clean_version(f.read())


# ======================================================
#                 UPDATE API
# ======================================================

update_bp = Blueprint("update", __name__, url_prefix="/api/update")


@update_bp.route("/check", methods=["POST"])
def check_update():
    """
    POST /api/update/check

    JSON:
    {
        "company": "БухПроф",
        "current_version": "1.0.3"
    }
    """
    data = request.get_json(silent=True) or {}

    company = (data.get("company") or "").strip()
    current_version = clean_version(data.get("current_version") or "")

    if not company or not current_version:
        return jsonify({
            "status": "error",
            "message": "Missing company or version"
        }), 400

    # пути
    company_txt = os.path.join(UPDATE_DIR, f"{company}.txt")
    universal_txt = os.path.join(UPDATE_DIR, "version.txt")

    latest_version = None
    zip_file = None

    # приоритет: компания
    if os.path.exists(company_txt):
        latest_version = read_version(company_txt)
        zip_file = f"{company}.zip"

    # иначе универсальная
    elif os.path.exists(universal_txt):
        latest_version = read_version(universal_txt)
        zip_file = "universal.zip"

    else:
        return jsonify({
            "status": "error",
            "message": "No update data on server"
        }), 404

    # DEBUG (оставь)
    print("---- UPDATE CHECK ----")
    print("Company:", company)
    print("Client :", current_version)
    print("Server :", latest_version)
    print("----------------------")

    if not latest_version:
        return jsonify({
            "status": "error",
            "message": "Invalid server version"
        }), 500

    # сравнение
    if not is_newer(latest_version, current_version):
        return jsonify({
            "status": "up_to_date",
            "latest_version": latest_version
        })

    return jsonify({
        "status": "update_available",
        "latest_version": latest_version,
        "file": zip_file
    })


@update_bp.route("/download/<filename>", methods=["GET"])
def download_update(filename):
    """
    GET /api/update/download/universal.zip
    """
    return send_from_directory(
        UPDATE_DIR,
        filename,
        as_attachment=True
    )


# ======================================================
#              HEALTH CHECK
# ======================================================

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ======================================================
#              РЕГИСТРАЦИЯ
# ======================================================

app.register_blueprint(update_bp)


# ======================================================
#                  RUN
# ======================================================

if __name__ == "__main__":
    print("UPDATE DIR:", UPDATE_DIR)
    app.run(host="0.0.0.0", port=5000, debug=True)
