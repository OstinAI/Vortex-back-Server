# -*- coding: utf-8 -*-
import os
from flask import Blueprint, request, jsonify
from utils.security import token_required
from db.connection import get_session
from db.models import User

upload_bp = Blueprint("upload", __name__)

# ======================================================
# 🔥 САМОЕ ГЛАВНОЕ: правильный путь
# FILES -> WebDoc/server/uploads
# ======================================================

BASE_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(BASE_DIR, exist_ok=True)

@upload_bp.route("/avatar/<int:user_id>", methods=["POST"])
@token_required
def upload_avatar(user_id):
    session = get_session()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({"status": "error", "message": "User not found"}), 404

        if "file" not in request.files:
            return jsonify({"status": "error", "message": "No file"}), 400

        file = request.files["file"]

        # /server/uploads/avatars/<company_id>/
        save_dir = os.path.join(BASE_DIR, "avatars", str(user.company_id))
        os.makedirs(save_dir, exist_ok=True)

        filename = f"user_{user_id}.png"
        save_path = os.path.join(save_dir, filename)

        # Debug path print
        print("UPLOAD BASE_DIR:", BASE_DIR)
        print("UPLOAD SAVE_DIR:", save_dir)
        print("UPLOAD SAVE_PATH:", save_path)

        file.save(save_path)

        # Путь, который WPF будет использовать
        user.avatar_path = f"/uploads/avatars/{user.company_id}/{filename}"
        session.commit()

        return jsonify({
            "status": "ok",
            "avatar_path": user.avatar_path
        })

    finally:
        session.close()


@upload_bp.route("/resume/<int:user_id>", methods=["POST"])
@token_required
def upload_resume(user_id):
    session = get_session()
    try:
        user = session.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({"status": "error", "message": "User not found"}), 404

        if "file" not in request.files:
            return jsonify({"status": "error", "message": "No file"}), 400

        file = request.files["file"]

        # проверяем что PDF
        if not file.filename.lower().endswith(".pdf"):
            return jsonify({"status": "error", "message": "Only PDF allowed"}), 400

        # директория для резюме
        save_dir = os.path.join(BASE_DIR, "resumes", str(user.company_id))
        os.makedirs(save_dir, exist_ok=True)

        filename = f"resume_{user_id}.pdf"
        save_path = os.path.join(save_dir, filename)

        file.save(save_path)

        user.resume_path = f"/uploads/resumes/{user.company_id}/{filename}"
        session.commit()

        return jsonify({
            "status": "ok",
            "resume_path": user.resume_path
        })

    finally:
        session.close()
