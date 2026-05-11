# -*- coding: utf-8 -*-
import time
from flask import Blueprint, request, jsonify

from utils.security import token_required
from utils.crypto import encrypt, decrypt
from db.connection import get_session
from db.models import MailAccount

from .imap_client import MailRuIMAP
from .smtp_client import send_mail
from .store import (
    save_message, save_attachments, load_message, list_uids
)

# ВАЖНО: watcher должен содержать эти имена
from server.mail.watcher import mark_company_online, start_watcher, NEW_UIDS, _LOCK

mail_bp = Blueprint("mail", __name__)

from flask import send_from_directory
import os
from .store import ATT_DIR, _safe_folder_name

from email.utils import formatdate

@mail_bp.route("/attachment/<int:company_id>/<path:folder>/<uid>/<filename>")
@token_required
def get_attachment_file(company_id, folder, uid, filename):
    # Путь к папке с файлами
    folder_path = os.path.join(
        ATT_DIR, 
        str(company_id), 
        _safe_folder_name(folder), 
        str(uid)
    )
    return send_from_directory(folder_path, filename)

# ============================================================
# 0) СПИСОК ИНТЕГРАЦИЙ
# ============================================================
@mail_bp.route("/list", methods=["GET"])
@token_required
def list_integrations():
    session = get_session()
    user = request.user

    accounts = session.query(MailAccount).filter_by(company_id=user["company_id"]).all()

    return jsonify({
        "status": "ok",
        "items": [
            {"provider": acc.provider, "title": acc.provider.capitalize()}
            for acc in accounts
        ]
    })


# ============================================================
# 1) ONLINE — отмечаем компанию онлайн и запускаем watcher
# ============================================================
@mail_bp.route("/online", methods=["POST"])
@token_required
def online():
    user = request.user
    
    # 2. ОБЯЗАТЕЛЬНО ВЫЗОВИ ФУНКЦИЮ ЗДЕСЬ
    # Это запустит фоновый поток watcher_loop
    start_watcher() 
    
    mark_company_online(int(user["company_id"]))
    return jsonify({"status": "ok"})


# ============================================================
# 2) FOLDERS — папки из IMAP (как в Mail.ru: name + imap_name)
# ============================================================
@mail_bp.route("/folders", methods=["GET"])
@token_required
def folders():
    user = request.user
    company_id = int(user["company_id"])

    session = get_session()
    acc = session.query(MailAccount).filter_by(company_id=company_id).first()
    if not acc:
        return jsonify({"status": "ok", "folders": []})

    try:
        imap = MailRuIMAP(acc.email, decrypt(acc.encrypted_password))
        f = imap.list_folders()
        try:
            imap.conn.logout()
        except:
            pass

        # гарантируем, что INBOX первым (если вдруг не пришёл)
        if f:
            idx = next((i for i, x in enumerate(f) if x.get("imap_name") == "INBOX"), None)
            if idx is None:
                f.insert(0, {"name": "Входящие", "imap_name": "INBOX"})
            elif idx != 0:
                inbox = f.pop(idx)
                f.insert(0, inbox)
        else:
            f = [{"name": "Входящие", "imap_name": "INBOX"}]

        return jsonify({"status": "ok", "folders": f})

    except Exception as e:
        # даже если IMAP упал — вернём хотя бы INBOX
        return jsonify({
            "status": "ok",
            "folders": [{"name": "Входящие", "imap_name": "INBOX"}],
            "warning": str(e)
        })


# ============================================================
# 3) SYNC — клиент присылает have[] UID по папке,
#          сервер возвращает недостающие письма этой папки.
# ============================================================
@mail_bp.route("/sync", methods=["POST"])
@token_required
def sync():
    data = request.json or {}
    have = data.get("have", [])
    folder = data.get("folder", "INBOX")

    user = request.user
    company_id = int(user["company_id"])

    # Получаем список UID, которые реально лежат на диске
    server_uids = list_uids(company_id, folder)
    
    # Письма, которых нет у клиента
    new_uids = [u for u in server_uids if u not in have]
    
    # Письма, которые удалены на сервере, но есть у клиента
    deleted_uids = [u for u in have if u not in server_uids]

    messages = []
    # Сортируем от новых к старым и отдаем до 100 штук за раз
    new_uids_sorted = sorted(new_uids, key=lambda x: int(x), reverse=True)[:100]

    for uid in new_uids_sorted:
        msg = load_message(company_id, folder, uid)
        if msg:
            msg["folder"] = folder
            messages.append(msg)

    return jsonify({
        "status": "ok",
        "folder": folder,
        "messages": messages,
        "deleted_uids": deleted_uids
    })

# ============================================================
# 4) WAIT — long-poll на новые UID в конкретной папке
#     НЕ качает письма, только выдаёт UID.
# ============================================================
@mail_bp.route("/wait", methods=["GET"])
@token_required
def wait_new():
    user = request.user
    company_id = int(user["company_id"])

    folder = request.args.get("folder", "INBOX")
    last_uid = int(request.args.get("last_uid", "0"))
    timeout = int(request.args.get("timeout", "25"))

    start = time.time()

    while time.time() - start < timeout:
        with _LOCK:
            q = NEW_UIDS[company_id][folder]

            # выбросим всё <= last_uid
            while q and int(q[0]) <= last_uid:
                q.popleft()

            if q:
                out = []
                while q and len(out) < 50:
                    out.append(int(q.popleft()))

                return jsonify({
                    "status": "ok",
                    "folder": folder,
                    "new_uids": out
                })

        time.sleep(1)

    return jsonify({
        "status": "timeout",
        "folder": folder,
        "new_uids": []
    })


# ============================================================
# 5) MESSAGE — одно письмо; если в storage нет — докачаем с IMAP 1 раз
# ============================================================
# Изменил <folder> на <path:folder>
@mail_bp.route("/message/<path:folder>/<uid>", methods=["GET"])
@token_required
def message_full(folder, uid):
    user = request.user
    company_id = int(user["company_id"])

    # 1. Проверяем кэш на диске
    cached = load_message(company_id, folder, uid)
    if cached:
        cached["folder"] = folder
        return jsonify({"status": "ok", "message": cached})

    session = get_session()
    acc = session.query(MailAccount).filter_by(company_id=company_id).first()
    if not acc:
        return jsonify({"status": "error", "message": "Mail not configured"}), 404

    try:
        imap = MailRuIMAP(acc.email, decrypt(acc.encrypted_password))
        msg = imap.fetch_message_full(folder, uid)

        try:
            imap.conn.logout()
        except:
            pass

        if not msg:
            return jsonify({"status": "error", "message": "not_found"}), 404

        att = msg.get("attachments", [])
        save_attachments(company_id, folder, uid, att)

        msg["attachments"] = att
        msg["folder"] = folder

        save_message(company_id, folder, uid, msg)
        return jsonify({"status": "ok", "message": msg})

    except Exception as e:
        print(f"[SERVER ERROR MESSAGE_FULL] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================
# 6) SEND — отправка письма
# ============================================================
@mail_bp.route("/send", methods=["POST"])
@token_required
def send_email():
    data = request.json or {}
    
    # 1. Сначала определяем все входящие переменные из запроса
    to = _extract_email(data.get("to"))
    subject = data.get("subject", "")
    body = data.get("body", "")
    attachments = data.get("attachments", [])

    if not to:
        return jsonify({"status": "error", "message": "to is empty"}), 400

    # 2. Получаем данные пользователя и компании
    session = get_session()
    user = request.user
    company_id = int(user["company_id"])

    # 3. Получаем почтовый аккаунт (переменная acc)
    acc = session.query(MailAccount).filter_by(company_id=company_id).first()
    if not acc:
        return jsonify({"status": "error", "message": "Mail not configured"}), 404

    # 4. Расшифровываем пароль (переменная smtp_password)
    smtp_password = decrypt(acc.encrypted_password)

    # 5. ОТПРАВЛЯЕМ ЧЕРЕЗ SMTP И ПОЛУЧАЕМ БАЙТЫ ПИСЬМА
    try:
        raw_msg_bytes = send_mail(
            acc.email,
            smtp_password,
            to=to,
            subject=subject,
            html_body=body,
            attachments=attachments
        )
    except Exception as e:
        return jsonify({"status": "error", "message": f"SMTP Error: {str(e)}"}), 500

    # 6. СОХРАНЯЕМ КОПИЮ НА СЕРВЕРЕ MAIL.RU ЧЕРЕЗ IMAP
    try:
        imap = MailRuIMAP(acc.email, smtp_password)
        imap.append_to_sent(raw_msg_bytes)
        try:
            imap.conn.logout()
        except:
            pass
    except Exception as e:
        print(f"[IMAP APPEND ERROR] {e}")

    # 7. СОХРАНЯЕМ КОПИЮ ЛОКАЛЬНО В CRM
    try:
        uid = _next_local_uid(company_id, SENT_FOLDER)
        msg_obj = _make_sent_message(acc.email, to, subject, body)
        msg_obj["uid"] = uid
        msg_obj["folder"] = SENT_FOLDER
        
        save_message(company_id, SENT_FOLDER, uid, msg_obj)
        
        if attachments:
            save_attachments(company_id, SENT_FOLDER, uid, attachments)
    except Exception as e:
        print(f"[LOCAL SAVE ERROR] {e}")

    return jsonify({"status": "ok", "message": "Email sent and saved"})

@mail_bp.route("/reply", methods=["POST"])
@token_required
def reply_email():
    data = request.json or {}
    folder = data.get("folder", "INBOX")
    uid = str(data.get("uid", ""))
    body = data.get("body", "")
    attachments = data.get("attachments", [])

    if not uid:
        return jsonify({"status": "error", "message": "uid is empty"}), 400

    user = request.user
    company_id = int(user["company_id"])

    # берем оригинал
    orig = load_message(company_id, folder, uid)
    if not orig:
        return jsonify({"status": "error", "message": "original not found"}), 404

    to = _extract_email(orig.get("from"))
    if not to:
        return jsonify({"status": "error", "message": "original from is empty"}), 400

    subject = orig.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject

    session = get_session()
    acc = session.query(MailAccount).filter_by(company_id=company_id).first()
    if not acc:
        return jsonify({"status": "error", "message": "Mail not configured"}), 404

    smtp_password = decrypt(acc.encrypted_password)

    # 1. Отправляем и получаем байты
    raw_msg_bytes = send_mail(
        acc.email,
        smtp_password,
        to=to,
        subject=subject,
        html_body=body,
        attachments=attachments
    )

    # 2. Копия на Mail.ru
    try:
        imap = MailRuIMAP(acc.email, smtp_password)
        imap.append_to_sent(raw_msg_bytes)
        try: imap.conn.logout()
        except: pass
    except Exception as e:
        print(f"IMAP Append Error: {e}")

    # 3. Сохранить в CRM
    try:
        new_uid = _next_local_uid(company_id, SENT_FOLDER)
        msg = _make_sent_message(acc.email, to, subject, body)
        msg["uid"] = new_uid
        msg["folder"] = SENT_FOLDER
        save_message(company_id, SENT_FOLDER, new_uid, msg)
    except:
        pass

    return jsonify({"status": "ok", "message": "Reply sent"})

# Вспомогательная функция (убедитесь, что она внизу файла)
def _make_sent_message(from_login, to, subject, body_html):
    return {
        "uid": "",
        "from": from_login,
        "to": to, # Поле 'to' нужно для отображения в списке
        "subject": subject or "",
        "date": formatdate(localtime=True), 
        "text": "",
        "html": body_html or "",
        "attachments": []
    }

# ============================================================
# 7) SETUP — привязка почты
# ============================================================
@mail_bp.route("/setup", methods=["POST"])
@token_required
def setup_mail():
    data = request.json or {}
    login = data.get("login")
    password = data.get("password")

    if not login or not password:
        return jsonify({"status": "error", "message": "Login or password is empty"}), 400

    session = get_session()
    user = request.user

    acc = session.query(MailAccount).filter_by(company_id=user["company_id"]).first()
    encrypted_password = encrypt(password)

    if acc:
        acc.email = login
        acc.encrypted_password = encrypted_password
        acc.provider = "mailru"
    else:
        acc = MailAccount(
            company_id=user["company_id"],
            email=login,
            encrypted_password=encrypted_password,
            provider="mailru"
        )
        session.add(acc)

    session.commit()
    return jsonify({"status": "ok", "message": "Mail account saved"})


# ============================================================
# 8) REMOVE — удалить интеграцию
# ============================================================
@mail_bp.route("/remove", methods=["DELETE"])
@token_required
def remove_mail():
    session = get_session()
    user = request.user
    company_id = int(user["company_id"])

    # 1. Ищем аккаунт
    acc = session.query(MailAccount).filter_by(company_id=company_id).first()
    if not acc:
        return jsonify({"status": "error", "message": "Mail not configured"}), 404

    try:
        # 2. Удаляем из БД
        session.delete(acc)
        session.commit()

        # 3. КРИТИЧЕСКИЙ ШАГ: Удаляем компанию из оперативной памяти Watcher-а
        # Импортируем блокировку и список активных компаний напрямую из watcher
        from server.mail.watcher import ACTIVE_COMPANIES, _LOCK
        with _LOCK:
            if company_id in ACTIVE_COMPANIES:
                ACTIVE_COMPANIES.remove(company_id)
        
        # 4. Опционально: очистка файлов (рекомендую)
        # Если хочешь удалять и файлы писем, вызови здесь метод из store.py
        from .store import delete_all_company_data
        delete_all_company_data(company_id)

        return jsonify({"status": "ok", "message": "Mail integration removed"})
        
    except Exception as e:
        session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

# =========================
# HELPERS (ADD)
# =========================
SENT_FOLDER = "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"  # Mail.ru "Отправленные"

def _extract_email(s):
    if not s:
        return ""
    s = str(s).strip()
    if "<" in s and ">" in s:
        return s.split("<", 1)[1].split(">", 1)[0].strip()
    return s

def _next_local_uid(company_id, folder):
    # UID для локального storage, чтобы письмо появилось в "Отправленные"
    base = int(time.time() * 1000)
    try:
        have = set(list_uids(company_id, folder))
    except:
        have = set()
    uid = str(base)
    while uid in have:
        base += 1
        uid = str(base)
    return uid

def _make_sent_message(from_login, to, subject, body_html):
    return {
        "uid": "",
        "from": from_login,
        "subject": subject or "",
        "date": time.strftime("%a, %d %b %Y %H:%M:%S %z"),
        "text": "",
        "html": body_html or "",
        "attachments": []
    }

@mail_bp.route("/forward", methods=["POST"])
@token_required
def forward_email():
    data = request.json or {}
    folder = data.get("folder", "INBOX")
    uid = str(data.get("uid", ""))
    to = _extract_email(data.get("to"))
    extra_body = data.get("body", "")
    attachments = data.get("attachments", [])

    if not uid:
        return jsonify({"status": "error", "message": "uid is empty"}), 400
    if not to:
        return jsonify({"status": "error", "message": "to is empty"}), 400

    user = request.user
    company_id = int(user["company_id"])

    orig = load_message(company_id, folder, uid)
    if not orig:
        return jsonify({"status": "error", "message": "original not found"}), 404

    subject = orig.get("subject", "")
    if not subject.lower().startswith("fw:") and not subject.lower().startswith("fwd:"):
        subject = "Fw: " + subject

    orig_from = orig.get("from", "")
    orig_date = orig.get("date", "")
    orig_html = orig.get("html", "") or orig.get("text", "")

    body = (
        (extra_body or "") +
        "<hr/>"
        "<div><b>Forwarded message</b></div>"
        f"<div><b>From:</b> {orig_from}</div>"
        f"<div><b>Date:</b> {orig_date}</div>"
        f"<div><b>Subject:</b> {orig.get('subject','')}</div>"
        "<br/>" +
        (orig_html or "")
    )

    session = get_session()
    acc = session.query(MailAccount).filter_by(company_id=company_id).first()
    if not acc:
        return jsonify({"status": "error", "message": "Mail not configured"}), 404

    smtp_password = decrypt(acc.encrypted_password)

    send_mail(
        acc.email,
        smtp_password,
        to=to,
        subject=subject,
        html_body=body,
        attachments=attachments
    )

    # сохранить в "Отправленные"
    try:
        new_uid = _next_local_uid(company_id, SENT_FOLDER)
        msg = _make_sent_message(acc.email, to, subject, body)
        msg["uid"] = new_uid
        msg["folder"] = SENT_FOLDER
        save_message(company_id, SENT_FOLDER, new_uid, msg)
    except:
        pass

    return jsonify({"status": "ok", "message": "Forward sent"})
