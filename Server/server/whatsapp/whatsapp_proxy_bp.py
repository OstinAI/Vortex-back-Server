# -*- coding: utf-8 -*-
from flask import Blueprint, request, Response, jsonify
import os
import requests

from server.whatsapp.whatsapp_proxy import wa_get, wa_post, WA_SERVER_URL

whatsapp_proxy_bp = Blueprint("whatsapp_proxy_bp", __name__)


@whatsapp_proxy_bp.route("/numbers/db", methods=["GET"])
def numbers_db():
    r = wa_get(
        "/api/whatsapp/numbers/db",
        auth_header=request.headers.get("Authorization", ""),
        params=request.args.to_dict()
    )
    return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type", "application/json"))


@whatsapp_proxy_bp.route("/numbers/start", methods=["POST"])
def numbers_start():
    r = wa_post(
        "/api/whatsapp/numbers/start",
        auth_header=request.headers.get("Authorization", ""),
        json_data=request.get_json(silent=True) or {}
    )
    return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type", "application/json"))


@whatsapp_proxy_bp.route("/numbers/stop", methods=["POST"])
def numbers_stop():
    r = wa_post(
        "/api/whatsapp/numbers/stop",
        auth_header=request.headers.get("Authorization", ""),
        json_data=request.get_json(silent=True) or {}
    )
    return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type", "application/json"))


@whatsapp_proxy_bp.route("/chats", methods=["GET"])
def chats():
    r = wa_get(
        "/api/whatsapp/chats",
        auth_header=request.headers.get("Authorization", ""),
        params=request.args.to_dict()
    )
    return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type", "application/json"))


@whatsapp_proxy_bp.route("/messages", methods=["GET"])
def messages():
    r = wa_get(
        "/api/whatsapp/messages",
        auth_header=request.headers.get("Authorization", ""),
        params=request.args.to_dict()
    )
    return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type", "application/json"))


@whatsapp_proxy_bp.route("/wait", methods=["GET"])
def wait():
    r = wa_get(
        "/api/whatsapp/wait",
        auth_header=request.headers.get("Authorization", ""),
        params=request.args.to_dict(),
        timeout=180
    )
    return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type", "application/json"))


@whatsapp_proxy_bp.route("/ack", methods=["POST"])
def ack():
    r = wa_post(
        "/api/whatsapp/ack",
        auth_header=request.headers.get("Authorization", ""),
        json_data=request.get_json(silent=True) or {}
    )
    return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type", "application/json"))


@whatsapp_proxy_bp.route("/send", methods=["POST"])
def send():
    r = wa_post(
        "/api/whatsapp/send",
        auth_header=request.headers.get("Authorization", ""),
        json_data=request.get_json(silent=True) or {}
    )
    return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type", "application/json"))


@whatsapp_proxy_bp.route("/qr", methods=["GET"])
def qr():
    r = wa_get(
        "/api/whatsapp/qr",
        auth_header=request.headers.get("Authorization", ""),
        params=request.args.to_dict(),
        timeout=120
    )
    return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type", "image/png"))

@whatsapp_proxy_bp.route("/status", methods=["GET"])
def status():
    r = wa_get(
        "/api/whatsapp/status",
        auth_header=request.headers.get("Authorization", ""),
        params=request.args.to_dict()
    )
    return Response(
        r.content,
        status=r.status_code,
        content_type=r.headers.get("Content-Type", "application/json")
    )

@whatsapp_proxy_bp.route("/channel", methods=["GET"])
def channel_get():
    r = wa_get(
        "/api/whatsapp/channel",
        auth_header=request.headers.get("Authorization", ""),
        params=request.args.to_dict()
    )
    return Response(
        r.content,
        status=r.status_code,
        content_type=r.headers.get("Content-Type", "application/json")
    )


@whatsapp_proxy_bp.route("/channel", methods=["POST"])
def channel_post():
    r = wa_post(
        "/api/whatsapp/channel",
        auth_header=request.headers.get("Authorization", ""),
        json_data=request.get_json(silent=True) or {}
    )
    return Response(
        r.content,
        status=r.status_code,
        content_type=r.headers.get("Content-Type", "application/json")
    )


@whatsapp_proxy_bp.route("/send_file", methods=["POST"])
def send_file():
    url = f"{WA_SERVER_URL}/api/whatsapp/send_file"

    headers = {}
    auth = request.headers.get("Authorization", "")
    if auth:
        headers["Authorization"] = auth

    files = {}
    if "file" in request.files:
        f = request.files["file"]
        files["file"] = (f.filename, f.stream, f.mimetype or "application/octet-stream")

    data = {
        "phone": request.form.get("phone", ""),
        "to": request.form.get("to", ""),
        "caption": request.form.get("caption", ""),
        "mode": request.form.get("mode", "document"),
    }

    r = requests.post(
        url,
        headers=headers,
        data=data,
        files=files,
        timeout=180
    )

    return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type", "application/json"))

@whatsapp_proxy_bp.route("/internal/send", methods=["POST"])
def internal_send():
    token = request.headers.get("X-Internal-Token", "")
    expected = os.getenv("INTERNAL_AUTOMATOR_TOKEN", "").strip()

    if not expected or token != expected:
        return jsonify({"ok": False, "message": "FORBIDDEN"}), 403

    url = f"{WA_SERVER_URL}/api/whatsapp/internal/send"

    r = requests.post(
        url,
        json=request.get_json(silent=True) or {},
        headers={
            "X-Internal-Token": token
        },
        timeout=30
    )

    return Response(
        r.content,
        status=r.status_code,
        content_type=r.headers.get("Content-Type", "application/json")
    )