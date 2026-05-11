# -*- coding: utf-8 -*-
import hashlib
import time

from flask import Blueprint, request, jsonify, Response
from utils.security import token_required
from db.connection import get_session
from db.models import Company, StoredFile
import os
import tempfile
import subprocess
import traceback

files_bp = Blueprint("files", __name__)

def _now_ms():
    return int(time.time() * 1000)

def _sha256_hex(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

@files_bp.route("/upload", methods=["POST"])
@token_required
def upload_file():
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    user_id = int(payload.get("user_id") or 0) if payload.get("user_id") else None

    if company_id <= 0:
        return jsonify({"status": "error", "message": "Invalid company"}), 400

    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file"}), 400

    f = request.files["file"]
    filename = (f.filename or "file.bin").strip()
    mime_type = (f.mimetype or "application/octet-stream").strip()

    data = f.read() or b""
    size_bytes = len(data)

    session = get_session()
    try:
        comp = session.query(Company).filter_by(id=company_id).first()
        if not comp:
            return jsonify({"status": "error", "message": "Company not found"}), 404

        limit_bytes = int(comp.storage_limit_mb) * 1024 * 1024
        used = int(comp.storage_used_bytes or 0)

        if used + size_bytes > limit_bytes:
            return jsonify({
                "status": "error",
                "message": "Storage limit exceeded",
                "limit_mb": int(comp.storage_limit_mb),
                "used_bytes": used,
                "file_size_bytes": size_bytes
            }), 413

        row = StoredFile(
            company_id=company_id,
            uploader_user_id=user_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=_sha256_hex(data),
            data=data,
            created_ts_ms=_now_ms()
        )
        session.add(row)

        comp.storage_used_bytes = used + size_bytes

        session.commit()

        return jsonify({
            "status": "ok",
            "file_id": row.id,
            "filename": row.filename,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes
        }), 200

    finally:
        session.close()

@files_bp.route("/download/<int:file_id>", methods=["GET"])
@token_required
def download_file(file_id):
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)

    session = get_session()
    try:
        row = session.query(StoredFile).filter_by(id=file_id, company_id=company_id).first()
        if not row:
            return jsonify({"status": "error", "message": "File not found"}), 404

        # --- optional transcode for WhatsApp PTT (ogg/opus) -> mp3 ---
        transcode = (request.args.get("transcode") or "").strip().lower()
        filename = (row.filename or "file.bin")
        mime = (row.mime_type or "application/octet-stream")

        ext = os.path.splitext(filename)[1].lower()
        is_whatsapp_audio = (mime.startswith("audio/") or ext in (".ogg", ".opus"))

        if transcode == "mp3" and is_whatsapp_audio:
            try:
                with tempfile.TemporaryDirectory() as td:
                    in_path = os.path.join(td, "in" + (ext if ext else ".ogg"))
                    out_path = os.path.join(td, "out.mp3")

                    with open(in_path, "wb") as f:
                        f.write(row.data or b"")

                    FFMPEG = os.path.join(os.path.dirname(__file__), "ffmpeg", "ffmpeg.exe")

                    subprocess.run(
                        [FFMPEG, "-y", "-i", in_path, "-vn", "-codec:a", "libmp3lame", "-q:a", "4", out_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True
                    )


                    with open(out_path, "rb") as f:
                        mp3_bytes = f.read() or b""

                headers = {
                    "Content-Type": "audio/mpeg",
                    "Content-Disposition": f'attachment; filename="{os.path.splitext(filename)[0]}.mp3"'
                }
                return Response(mp3_bytes, headers=headers)
            except Exception as e:

                traceback.print_exc()
                return jsonify({"status": "error", "message": "TRANSCODE_FAILED", "error": str(e)}), 500

        # --- /transcode ---

        from urllib.parse import quote

        safe_name = quote(row.filename)

        headers = {
            "Content-Type": row.mime_type or "application/octet-stream",
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"
        }

        return Response(row.data, headers=headers)


    finally:
        session.close()


@files_bp.route("/quota", methods=["GET"])
@token_required
def quota():
    payload = request.user
    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)

    session = get_session()
    try:
        comp = session.query(Company).filter_by(id=company_id).first()
        if not comp:
            return jsonify({"status": "error", "message": "Company not found"}), 404

        return jsonify({
            "status": "ok",
            "limit_mb": int(comp.storage_limit_mb),
            "used_bytes": int(comp.storage_used_bytes or 0)
        }), 200

    finally:
        session.close()

@files_bp.route("/set_limit", methods=["POST"])
@token_required
def set_limit():
    payload = request.user
    if payload.get("role") not in ("Integrator", "Admin"):
        return jsonify({"status": "error", "message": "Access denied"}), 403

    company_id = int(payload.get("companyId") or payload.get("company_id") or 0)
    data = request.get_json(silent=True) or {}
    new_limit_mb = int(data.get("limit_mb") or 0)

    if new_limit_mb <= 0:
        return jsonify({"status": "error", "message": "Invalid limit_mb"}), 400

    session = get_session()
    try:
        comp = session.query(Company).filter_by(id=company_id).first()
        if not comp:
            return jsonify({"status": "error", "message": "Company not found"}), 404

        comp.storage_limit_mb = new_limit_mb
        session.commit()

        return jsonify({
            "status": "ok",
            "limit_mb": int(comp.storage_limit_mb)
        }), 200

    finally:
        session.close()
