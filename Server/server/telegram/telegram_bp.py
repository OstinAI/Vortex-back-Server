# -*- coding: utf-8 -*-
import time
import requests
import threading
import hashlib
from flask import Blueprint, request, jsonify
from utils.security import token_required
from db.connection import get_session
from db.models import (
    Company, 
    TelegramBot, 
    TelegramChat, 
    TelegramMessage, 
    Client, 
    ClientIdentity, 
    CRMChannelRoute, 
    StoredFile,
    ClientAssignment
)
from utils.crypto import encrypt, decrypt

def get_telegram_avatar(bot_token, user_id):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUserProfilePhotos?user_id={user_id}&limit=1"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("ok") and data["result"]["photos"]:
            file_id = data["result"]["photos"][0][-1]["file_id"]
            file_resp = requests.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}")
            file_path = file_resp.json()["result"]["file_path"]
            return f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    except Exception as e:
        print(f"Avatar error: {e}")
    return None

# В самом начале файла, после импортов
_polling_started = False

telegram_bp = Blueprint("telegram", __name__)


def _company_id():
    payload = getattr(request, "user", None) or {}
    return int(payload.get("company_id") or payload.get("companyId") or 0)


# ============================================
# 1. ПОЛУЧИТЬ СТАТУС TELEGRAM БОТА
# ============================================
@telegram_bp.route("/status", methods=["GET"])
@token_required
def get_telegram_status():
    company_id = _company_id()
    
    session = get_session()
    try:
        bot = session.query(TelegramBot).filter_by(company_id=company_id).first()
        
        if bot and bot.is_active:
            # Расшифровываем токен для проверки (но не показываем клиенту)
            try:
                bot_token = decrypt(bot.bot_token)
                # Проверяем, работает ли бот
                resp = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=5)
                if resp.status_code == 200 and resp.json().get("ok"):
                    return jsonify({
                        "ok": True,
                        "is_connected": True,
                        "bot_id": bot.id,
                        "bot_username": bot.bot_username,
                        "greeting_enabled": bot.greeting_enabled,
                        "greeting_text": bot.greeting_text,
                        "crm_sync_enabled": bot.crm_sync_enabled
                    }), 200
            except:
                pass
        
        return jsonify({
            "ok": True,
            "is_connected": False,
            "crm_sync_enabled": True
        }), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        session.close()


# ============================================
# 2. НАСТРОЙКА / ПОДКЛЮЧЕНИЕ БОТА
# ============================================
@telegram_bp.route("/configure", methods=["POST"])
@token_required
def configure_telegram():
    company_id = _company_id()
    data = request.get_json(silent=True) or {}
    
    bot_token = data.get("bot_token", "").strip()
    greeting_enabled = data.get("greeting_enabled", False)
    greeting_text = data.get("greeting_text", "")
    base_url = data.get("base_url", "")
    
    if not bot_token:
        return jsonify({"status": "error", "message": "Bot token required"}), 400
    
    # Проверяем токен через Telegram API
    try:
        resp = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10)
        result = resp.json()
        
        if not result.get("ok"):
            return jsonify({"status": "error", "message": "Invalid bot token"}), 400
        
        bot_username = result["result"]["username"]
        bot_id_api = result["result"]["id"]
    except Exception as e:
        return jsonify({"status": "error", "message": f"Telegram API error: {str(e)}"}), 400
    
    session = get_session()
    try:
        # Ищем существующего бота
        bot = session.query(TelegramBot).filter_by(company_id=company_id).first()
        
        encrypted_token = encrypt(bot_token)
        
        if bot:
            bot.bot_token = encrypted_token
            bot.bot_username = bot_username
            bot.bot_id_api = bot_id_api
            bot.is_active = True
            bot.greeting_enabled = greeting_enabled
            bot.greeting_text = greeting_text
        else:
            bot = TelegramBot(
                company_id=company_id,
                bot_token=encrypted_token,
                bot_username=bot_username,
                bot_id_api=bot_id_api,
                is_active=True,
                greeting_enabled=greeting_enabled,
                greeting_text=greeting_text,
                crm_sync_enabled=True,
                created_ts_ms=int(time.time() * 1000)
            )
            session.add(bot)
            session.flush()
        
        # Настраиваем webhook если есть base_url
        if base_url:
            webhook_url = f"{base_url.rstrip('/')}/api/telegram/webhook/{bot.id}"
            set_webhook_resp = requests.get(
                f"https://api.telegram.org/bot{bot_token}/setWebhook?url={webhook_url}",
                timeout=10
            )
            print(f"Webhook set response: {set_webhook_resp.json()}")
        
        session.commit()
        
        return jsonify({
            "status": "ok",
            "bot_id": bot.id,
            "bot_username": bot_username,
            "message": "Bot configured successfully"
        }), 200
        
    except Exception as e:
        session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# 3. ВКЛЮЧИТЬ/ВЫКЛЮЧИТЬ CRM СИНХРОНИЗАЦИЮ
# ============================================
@telegram_bp.route("/crm-sync", methods=["POST"])
@token_required
def set_crm_sync():
    company_id = _company_id()
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", True)
    
    session = get_session()
    try:
        bot = session.query(TelegramBot).filter_by(company_id=company_id).first()
        if bot:
            bot.crm_sync_enabled = enabled
            session.commit()
        
        return jsonify({"status": "ok", "crm_sync_enabled": enabled}), 200
    except Exception as e:
        session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# 4. ОТКЛЮЧИТЬ БОТА
# ============================================
@telegram_bp.route("/disconnect", methods=["POST"])
@token_required
def disconnect_telegram():
    company_id = _company_id()
    
    session = get_session()
    try:
        bot = session.query(TelegramBot).filter_by(company_id=company_id).first()
        if bot:
            # Удаляем webhook
            try:
                bot_token = decrypt(bot.bot_token)
                requests.get(f"https://api.telegram.org/bot{bot_token}/deleteWebhook", timeout=10)
            except:
                pass
            
            bot.is_active = False
            session.commit()
        
        return jsonify({"status": "ok", "message": "Bot disconnected"}), 200
    except Exception as e:
        session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# 5. WEBHOOK ДЛЯ ПРИЁМА СООБЩЕНИЙ ОТ TELEGRAM
# ============================================
@telegram_bp.route("/webhook/<int:bot_id>", methods=["POST"])
def telegram_webhook(bot_id):
    """Telegram присылает сюда сообщения"""
    data = request.get_json()
    if not data:
        return "OK", 200
    
    session = get_session()
    try:
        bot = session.query(TelegramBot).filter_by(id=bot_id, is_active=True).first()
        if not bot:
            return "OK", 200
        
        company_id = bot.company_id
        
        message = data.get("message")
        if not message:
            return "OK", 200
        
        chat = message.get("chat", {})
        telegram_chat_id = chat.get("id")
        from_user = message.get("from", {})
        telegram_user_id = from_user.get("id")
        peer_name = from_user.get("first_name", "") + " " + (from_user.get("last_name") or "")
        text = message.get("text", "")
        telegram_msg_id = message.get("message_id")
        
        # Ищем или создаём чат
        tg_chat = session.query(TelegramChat).filter_by(
            company_id=company_id,
            bot_id=bot_id,
            telegram_chat_id=telegram_chat_id
        ).first()
        
        if not tg_chat:
            tg_chat = TelegramChat(
                company_id=company_id,
                bot_id=bot_id,
                telegram_chat_id=telegram_chat_id,
                telegram_user_id=telegram_user_id,
                peer_name=peer_name,
                last_message_ts_ms=int(time.time() * 1000)
            )
            session.add(tg_chat)
            session.flush()
            
            # Если включена CRM синхронизация — ищем или создаём клиента
            if bot.crm_sync_enabled:
                # Ищем клиента по Telegram ID
                identity = session.query(ClientIdentity).filter_by(
                    company_id=company_id,
                    kind="telegram",
                    value=str(telegram_user_id)
                ).first()
                
                if identity:
                    tg_chat.client_id = identity.client_id
                else:
                    # Создаём нового клиента
                    # Находим маршрут для Telegram
                    route = session.query(CRMChannelRoute).filter_by(
                        company_id=company_id, channel="telegram"
                    ).first()
                    
                    client = Client(
                        company_id=company_id,
                        name=peer_name or f"Клиент Telegram",
                        status="active",
                        created_ts_ms=int(time.time() * 1000),
                        pipeline_id=route.pipeline_id if route else None,
                        stage_id=route.stage_id if route else None
                    )
                    session.add(client)
                    session.flush()
                    
                    # Создаём identity
                    session.add(ClientIdentity(
                        company_id=company_id,
                        client_id=client.id,
                        kind="telegram",
                        value=str(telegram_user_id),
                        created_ts_ms=int(time.time() * 1000)
                    ))
                    
                    tg_chat.client_id = client.id
                    
                    # Отправляем приветствие, если включено
                    if bot.greeting_enabled and bot.greeting_text:
                        bot_token = decrypt(bot.bot_token)
                        send_telegram_message(bot_token, telegram_chat_id, bot.greeting_text)
        
        # Обновляем last_message
        tg_chat.last_message_ts_ms = int(time.time() * 1000)
        
        # Сохраняем сообщение
        tg_msg = TelegramMessage(
            company_id=company_id,
            chat_id=tg_chat.id,
            direction="in",
            text=text,
            telegram_msg_id=telegram_msg_id,
            ts_ms=int(time.time() * 1000)
        )
        session.add(tg_msg)
        session.commit()
        
    except Exception as e:
        session.rollback()
        print(f"Telegram webhook error: {e}")
    finally:
        session.close()
    
    return "OK", 200


# ============================================
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ
# ============================================
def send_telegram_message(bot_token, chat_id, text):
    """Отправка сообщения через Telegram API"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
        return resp.json().get("ok", False)
    except Exception as e:
        print(f"Send error: {e}")
        return False

# Добавьте эти эндпоинты в server/telegram/telegram_bp.py

@telegram_bp.route("/chats", methods=["GET"])
@token_required
def get_telegram_chats():
    company_id = _company_id()
    payload = getattr(request, "user", None) or {}
    user_id = int(payload.get("user_id") or 0)
    role = str(payload.get("role") or "").strip().lower()
    
    session = get_session()
    try:
        chats = session.query(TelegramChat).filter_by(company_id=company_id).order_by(TelegramChat.last_message_ts_ms.desc()).all()
        
        result = []
        for chat in chats:
            # Получаем последнее сообщение
            last_msg = session.query(TelegramMessage).filter_by(chat_id=chat.id).order_by(TelegramMessage.ts_ms.desc()).first()
            
            # Проверяем ответственных у клиента
            responsible_user_ids = []
            has_responsible = False
            
            if chat.client_id:
                assignments = session.query(ClientAssignment).filter_by(
                    client_id=chat.client_id, company_id=company_id
                ).all()
                responsible_user_ids = [int(a.user_id) for a in assignments]
                has_responsible = len(responsible_user_ids) > 0
            
            # Фильтрация по правам
            is_admin = role in ("admin", "integrator", "director")
            is_responsible = user_id in responsible_user_ids
            
            # Если не админ и есть ответственный, но пользователь не ответственный - пропускаем
            if not is_admin and has_responsible and not is_responsible:
                continue
            
            result.append({
                "id": chat.id,
                "telegram_chat_id": chat.telegram_chat_id,
                "telegram_user_id": chat.telegram_user_id,
                "peer_name": chat.peer_name,
                "peer_avatar_url": chat.peer_avatar_url,
                "last_message_ts_ms": chat.last_message_ts_ms,
                "last_message": last_msg.text[:50] if last_msg else "",
                "client_id": chat.client_id,
                "has_responsible": has_responsible
            })
        
        return jsonify({"ok": True, "chats": result}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        session.close()


@telegram_bp.route("/messages/<int:chat_id>", methods=["GET"])
@token_required
def get_telegram_messages(chat_id):
    company_id = _company_id()
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    session = get_session()
    try:
        chat = session.query(TelegramChat).filter_by(id=chat_id, company_id=company_id).first()
        if not chat:
            return jsonify({"ok": False, "error": "Chat not found"}), 404
        
        # Получаем сообщения с пагинацией (от новых к старым)
        messages = session.query(TelegramMessage).filter_by(
            chat_id=chat_id
        ).order_by(TelegramMessage.ts_ms.desc()).offset(offset).limit(limit).all()
        
        # Разворачиваем обратно (от старых к новым для отображения)
        messages.reverse()
        
        result = [{
            "id": msg.id,
            "direction": msg.direction,
            "text": msg.text,
            "file_id": msg.file_id,
            "file_name": msg.file_name,
            "file_mime": msg.file_mime,
            "file_size": None,
            "ts_ms": msg.ts_ms
        } for msg in messages]
        
        # Получаем размеры файлов
        for msg in result:
            if msg["file_id"]:
                file_record = session.query(StoredFile).filter_by(id=msg["file_id"]).first()
                if file_record:
                    msg["file_size"] = file_record.size_bytes
        
        return jsonify({"ok": True, "messages": result}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        session.close()


# ============================================
# 6. СИНХРОНИЗАЦИЯ СООБЩЕНИЙ ИЗ TELEGRAM
# ============================================
@telegram_bp.route("/sync-from-telegram", methods=["POST"])
@token_required
def sync_from_telegram():
    """Принудительная синхронизация сообщений из Telegram"""
    company_id = _company_id()
    
    session = get_session()
    try:
        bot = session.query(TelegramBot).filter_by(company_id=company_id, is_active=True).first()
        if not bot:
            return jsonify({"status": "error", "message": "Bot not found. Please configure bot first."}), 404
        
        bot_token = decrypt(bot.bot_token)
        
        # Получаем обновления
        resp = requests.get(f"https://api.telegram.org/bot{bot_token}/getUpdates", timeout=10)
        data = resp.json()
        
        if not data.get("ok"):
            return jsonify({"status": "error", "message": "Telegram API error", "details": data}), 500
        
        updates = data.get("result", [])
        saved_chats = 0
        saved_messages = 0
        
        for update in updates:
            message = update.get("message")
            if not message:
                continue
            
            chat = message.get("chat", {})
            telegram_chat_id = chat.get("id")
            from_user = message.get("from", {})
            telegram_user_id = from_user.get("id")
            first_name = from_user.get("first_name", "")
            last_name = from_user.get("last_name", "")
            username = from_user.get("username", "")
            peer_name = f"{first_name} {last_name}".strip() or username or f"User_{telegram_user_id}"
            text = message.get("text", "")
            telegram_msg_id = message.get("message_id")
            
            # Ищем или создаём чат
            tg_chat = session.query(TelegramChat).filter_by(
                company_id=company_id,
                bot_id=bot.id,
                telegram_chat_id=telegram_chat_id
            ).first()
            
            if not tg_chat:
                tg_chat = TelegramChat(
                    company_id=company_id,
                    bot_id=bot.id,
                    telegram_chat_id=telegram_chat_id,
                    telegram_user_id=telegram_user_id,
                    peer_name=peer_name,
                    last_message_ts_ms=int(time.time() * 1000)
                )
                session.add(tg_chat)
                session.flush()
                saved_chats += 1
                print(f"✅ New chat created: {peer_name}")
            
            # Проверяем, нет ли уже такого сообщения
            existing = session.query(TelegramMessage).filter_by(
                chat_id=tg_chat.id,
                telegram_msg_id=telegram_msg_id
            ).first()
            
            if not existing and text:
                tg_msg = TelegramMessage(
                    company_id=company_id,
                    chat_id=tg_chat.id,
                    direction="in",
                    text=text,
                    telegram_msg_id=telegram_msg_id,
                    ts_ms=int(time.time() * 1000)
                )
                session.add(tg_msg)
                saved_messages += 1
                print(f"✅ New message: {text[:50]}")
            
            tg_chat.last_message_ts_ms = int(time.time() * 1000)
        
        session.commit()
        
        return jsonify({
            "status": "ok",
            "updates_processed": len(updates),
            "new_chats": saved_chats,
            "new_messages": saved_messages
        }), 200
        
    except Exception as e:
        session.rollback()
        print(f"❌ Sync error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================
# ЗАПУСК ПОЛЛИНГА ДЛЯ АВТОМАТИЧЕСКОГО ПОЛУЧЕНИЯ СООБЩЕНИЙ
# ============================================
# Глобальная переменная для хранения последнего обработанного update_id
_last_processed_update_id = {}

def start_telegram_polling():
    """Запуск polling в фоновом потоке для получения сообщений"""
    global _polling_started
    
    # Защита от дублирования
    if _polling_started:
        print("⚠️ Polling already started, skipping duplicate")
        return
    _polling_started = True
    
    import threading
    
    def poll_worker():
        print("🚀 Telegram polling thread started")
        
        while True:
            try:
                session = get_session()
                bots = session.query(TelegramBot).filter_by(is_active=True).all()
                session.close()
                
                for bot in bots:
                    try:
                        bot_token = decrypt(bot.bot_token)
                        company_id = bot.company_id
                        
                        # Получаем последний обработанный update_id для этого бота
                        last_id = _last_processed_update_id.get(bot.id, 0)
                        
                        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
                        params = {"offset": last_id + 1, "timeout": 30}
                        
                        resp = requests.get(url, params=params, timeout=35)
                        data = resp.json()
                        
                        if data.get("ok"):
                            updates = data.get("result", [])
                            if updates:
                                max_update_id = max((u.get("update_id", 0) for u in updates), default=last_id)
                                
                                for update in updates:
                                    message = update.get("message")
                                    if message:
                                        telegram_msg_id = message.get("message_id")
                                        if not is_message_already_saved(bot.id, telegram_msg_id):
                                            save_telegram_message(bot, company_id, message)
                                
                                if max_update_id > last_id:
                                    _last_processed_update_id[bot.id] = max_update_id
                                    print(f"📌 Updated offset for bot {bot.id} to {max_update_id}")
                        elif data.get("error_code") == 409:
                            # Просто логируем, но не спамим
                            pass
                        else:
                            print(f"⚠️ Telegram API error: {data}")
                            
                    except Exception as e:
                        print(f"❌ Polling error for bot {bot.id}: {e}")
                        
                time.sleep(3)
                
            except Exception as e:
                print(f"❌ Polling loop error: {e}")
                time.sleep(5)
    
    thread = threading.Thread(target=poll_worker, daemon=True)
    thread.start()
    print("✅ Telegram polling started")


def is_message_already_saved(bot_id, telegram_msg_id):
    """Проверяет, сохранено ли уже сообщение"""
    if not telegram_msg_id:
        return True  # Если нет ID, пропускаем
    
    session = get_session()
    try:
        exists = session.query(TelegramMessage).filter_by(
            telegram_msg_id=telegram_msg_id
        ).first()
        return exists is not None
    except Exception as e:
        print(f"Error checking message: {e}")
        return True  # В случае ошибки лучше пропустить
    finally:
        session.close()


def save_telegram_message(bot, company_id, message):
    """Сохраняет сообщение из Telegram в базу данных (с поддержкой файлов и текста)"""
    session = get_session()
    try:
        chat = message.get("chat", {})
        telegram_chat_id = chat.get("id")
        from_user = message.get("from", {})
        telegram_user_id = from_user.get("id")
        first_name = from_user.get("first_name", "")
        last_name = from_user.get("last_name", "")
        username = from_user.get("username", "")
        peer_name = f"{first_name} {last_name}".strip() or username or f"User_{telegram_user_id}"
        
        # Текст может быть в поле "text" или "caption" (для фото/видео)
        text = message.get("text", "") or message.get("caption", "") or ""
        telegram_msg_id = message.get("message_id")
        
        # 🔥 СНАЧАЛА ищем или создаём чат
        tg_chat = session.query(TelegramChat).filter_by(
            company_id=company_id,
            bot_id=bot.id,
            telegram_chat_id=telegram_chat_id
        ).first()
        
        if not tg_chat:
            # Получаем аватар пользователя
            bot_token = decrypt(bot.bot_token)
            peer_avatar_url = get_telegram_avatar(bot_token, telegram_user_id)
            print(f"🖼️ Avatar URL for {telegram_user_id}: {peer_avatar_url}")  # ОТЛАДКА
    
            tg_chat = TelegramChat(
                company_id=company_id,
                bot_id=bot.id,
                telegram_chat_id=telegram_chat_id,
                telegram_user_id=telegram_user_id,
                peer_name=peer_name,
                peer_avatar_url=peer_avatar_url,
                last_message_ts_ms=int(time.time() * 1000)
            )
            session.add(tg_chat)
            session.flush()
            print(f"✅ New chat created: {peer_name} (ID: {tg_chat.id})")
        
            # ========== ДОБАВИТЬ ЭТОТ БЛОК ==========
        # Если включена CRM синхронизация — создаём клиента
        if bot.crm_sync_enabled:
            # Ищем клиента по Telegram ID
            identity = session.query(ClientIdentity).filter_by(
                company_id=company_id,
                kind="telegram",
                value=str(telegram_user_id)
            ).first()
        
            if identity:
                tg_chat.client_id = identity.client_id
            else:
                # Находим маршрут для Telegram
                route = session.query(CRMChannelRoute).filter_by(
                    company_id=company_id, channel="telegram"
                ).first()
            
                client = Client(
                    company_id=company_id,
                    name=peer_name or f"Клиент Telegram",
                    status="active",
                    created_ts_ms=int(time.time() * 1000),
                    pipeline_id=route.pipeline_id if route else None,
                    stage_id=route.stage_id if route else None
                )
                session.add(client)
                session.flush()
            
                # Создаём identity
                session.add(ClientIdentity(
                    company_id=company_id,
                    client_id=client.id,
                    kind="telegram",
                    value=str(telegram_user_id),
                    created_ts_ms=int(time.time() * 1000)
                ))
            
                tg_chat.client_id = client.id
                print(f"✅ New client created: {peer_name} (ID: {client.id}, pipeline: {route.pipeline_id if route else None})")
        # ========================================
        # 🔥 ПРОВЕРЯЕМ, есть ли уже такое сообщение в БД (ПО telegram_msg_id)
        existing = session.query(TelegramMessage).filter_by(
            telegram_msg_id=telegram_msg_id
        ).first()
        
        if existing:
            print(f"⏭️ Message {telegram_msg_id} already exists, skipping")
            # Всё равно обновляем время последнего сообщения в чате
            tg_chat.last_message_ts_ms = int(time.time() * 1000)
            session.commit()
            return
        
        # 🔥 ТОЛЬКО ЕСЛИ СООБЩЕНИЯ НЕТ - обрабатываем файлы
        file_id = None
        file_name = None
        file_mime = None
        stored_file_id = None
        
        # Проверяем тип контента
        if message.get("photo"):
            photos = message.get("photo", [])
            if photos:
                largest_photo = photos[-1]
                file_id = largest_photo.get("file_id")
                file_name = f"photo_{telegram_msg_id}.jpg"
                file_mime = "image/jpeg"
                if not text:
                    text = "📷 Фото"
        elif message.get("video"):
            video = message.get("video", {})
            file_id = video.get("file_id")
            file_name = video.get("file_name", f"video_{telegram_msg_id}.mp4")
            file_mime = "video/mp4"
            if not text:
                text = "🎥 Видео"
        elif message.get("document"):
            doc = message.get("document", {})
            file_id = doc.get("file_id")
            file_name = doc.get("file_name", f"document_{telegram_msg_id}.bin")
            file_mime = doc.get("mime_type", "application/octet-stream")
            if not text:
                text = f"📎 {file_name}"
        elif message.get("audio"):
            audio = message.get("audio", {})
            file_id = audio.get("file_id")
            file_name = audio.get("file_name", f"audio_{telegram_msg_id}.mp3")
            file_mime = "audio/mpeg"
            if not text:
                text = "🎵 Аудио"
        elif message.get("voice"):
            voice = message.get("voice", {})
            file_id = voice.get("file_id")
            file_name = f"voice_{telegram_msg_id}.ogg"
            file_mime = "audio/ogg"
            if not text:
                text = "🎤 Голосовое сообщение"
        elif message.get("sticker"):
            sticker = message.get("sticker", {})
            file_id = sticker.get("file_id")
            file_name = f"sticker_{telegram_msg_id}.webp"
            file_mime = "image/webp"
            if not text:
                text = "🎨 Стикер"
        
        # Скачиваем файл ТОЛЬКО если он есть
        if file_id:
            try:
                bot_token = decrypt(bot.bot_token)
                stored_file_id = download_and_save_file(bot_token, file_id, file_name, file_mime, company_id, session)
            except Exception as e:
                print(f"❌ Error downloading file: {e}")
        
        # Сохраняем сообщение
        tg_msg = TelegramMessage(
            company_id=company_id,
            chat_id=tg_chat.id,
            direction="in",
            text=text,
            file_id=stored_file_id,
            file_name=file_name,
            file_mime=file_mime,
            telegram_msg_id=telegram_msg_id,
            ts_ms=int(time.time() * 1000)
        )
        session.add(tg_msg)
        print(f"✅ New message saved: text='{text[:50] if text else '[empty]'}', file={file_name}")
        
        tg_chat.last_message_ts_ms = int(time.time() * 1000)
        session.commit()
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error saving message: {e}")
    finally:
        session.close()

# ============================================
# СКАЧИВАНИЕ И СОХРАНЕНИЕ ФАЙЛА ИЗ TELEGRAM
# ============================================
def download_and_save_file(bot_token, file_id, file_name, mime_type, company_id, session):
    """Скачивает файл из Telegram и сохраняет в БД"""
    try:
        # Получаем путь к файлу
        get_file_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
        resp = requests.get(get_file_url, timeout=10)
        file_info = resp.json()
        
        if not file_info.get("ok"):
            print(f"❌ Failed to get file info: {file_info}")
            return None
        
        file_path = file_info["result"]["file_path"]
        
        # Скачиваем файл
        download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        file_resp = requests.get(download_url, timeout=30)
        
        if file_resp.status_code != 200:
            print(f"❌ Failed to download file: {file_resp.status_code}")
            return None
        
        file_data = file_resp.content
        size_bytes = len(file_data)
        
        # Генерируем SHA256
        sha256_hash = hashlib.sha256(file_data).hexdigest()
        
        # Сохраняем в StoredFile
        stored_file = StoredFile(
            company_id=company_id,
            uploader_user_id=None,
            filename=file_name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256_hash,
            data=file_data,
            created_ts_ms=int(time.time() * 1000)
        )
        session.add(stored_file)
        session.flush()
        
        # Обновляем лимит хранилища компании
        comp = session.query(Company).filter_by(id=company_id).first()
        if comp:
            comp.storage_used_bytes = (comp.storage_used_bytes or 0) + size_bytes
        
        print(f"✅ File saved: {file_name} ({size_bytes} bytes)")
        return stored_file.id
        
    except Exception as e:
        print(f"❌ Error downloading file: {e}")
        return None


# ============================================
# ОБНОВЛЁННАЯ ОТПРАВКА СООБЩЕНИЙ (С ПОДДЕРЖКОЙ ФАЙЛОВ)
# ============================================
@telegram_bp.route("/send", methods=["POST"])
@token_required
def send_telegram_message_api():
    """Отправка сообщения в Telegram (с поддержкой файлов)"""
    company_id = _company_id()
    
    # Проверяем, пришёл ли файл
    if request.files:
        # Отправка с файлом
        chat_id = request.form.get("chat_id")
        text = request.form.get("text", "")
        file = request.files.get("file")
        
        if not chat_id:
            return jsonify({"status": "error", "message": "chat_id required"}), 400
        
        session = get_session()
        try:
            tg_chat = session.query(TelegramChat).filter_by(id=chat_id, company_id=company_id).first()
            if not tg_chat:
                return jsonify({"status": "error", "message": "Chat not found"}), 404
            
            bot = session.query(TelegramBot).filter_by(id=tg_chat.bot_id, company_id=company_id, is_active=True).first()
            if not bot:
                return jsonify({"status": "error", "message": "Bot not active"}), 404
            
            bot_token = decrypt(bot.bot_token)
            
            # Отправляем файл
            if file:
                file_data = file.read()
                files = {"document": (file.filename, file_data, file.mimetype)}
                url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
                data = {"chat_id": tg_chat.telegram_chat_id, "caption": text}
                resp = requests.post(url, files=files, data=data, timeout=30)
                result = resp.json()
    
                if result.get("ok"):
                    # Получаем file_id из ответа Telegram для фотографий/документов/видео
                    sent_file_id = None
                    if result["result"].get("document"):
                        sent_file_id = result["result"]["document"]["file_id"]
                    elif result["result"].get("photo"):
                        sent_file_id = result["result"]["photo"][-1]["file_id"]
                    elif result["result"].get("video"):
                        sent_file_id = result["result"]["video"]["file_id"]
        
                    # Скачиваем и сохраняем файл в БД
                    if sent_file_id:
                        stored_file_id = download_and_save_file(bot_token, sent_file_id, file.filename, file.mimetype, company_id, session)
            
                        # Сохраняем исходящее сообщение с file_id
                        tg_msg = TelegramMessage(
                            company_id=company_id,
                            chat_id=tg_chat.id,
                            direction="out",
                            text=text or file.filename,
                            file_id=stored_file_id,
                            file_name=file.filename,
                            file_mime=file.mimetype,
                            telegram_msg_id=result["result"].get("message_id"),
                            ts_ms=int(time.time() * 1000)
                        )
                        session.add(tg_msg)
                        tg_chat.last_message_ts_ms = int(time.time() * 1000)
                        session.commit()
            
                        return jsonify({"status": "ok", "message": "Sent"}), 200
            else:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                resp = requests.post(url, json={"chat_id": tg_chat.telegram_chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
            
            result = resp.json()
            
            if result.get("ok"):
                # Сохраняем исходящее сообщение
                tg_msg = TelegramMessage(
                    company_id=company_id,
                    chat_id=tg_chat.id,
                    direction="out",
                    text=text or (file.filename if file else ""),
                    file_name=file.filename if file else None,
                    file_mime=file.mimetype if file else None,
                    telegram_msg_id=result["result"].get("message_id"),
                    ts_ms=int(time.time() * 1000)
                )
                session.add(tg_msg)
                tg_chat.last_message_ts_ms = int(time.time() * 1000)
                session.commit()
                
                return jsonify({"status": "ok", "message": "Sent"}), 200
            else:
                return jsonify({"status": "error", "message": result.get("description", "Send failed")}), 500
                
        except Exception as e:
            session.rollback()
            return jsonify({"status": "error", "message": str(e)}), 500
        finally:
            session.close()
    
    else:
        # Обычное текстовое сообщение
        data = request.get_json(silent=True) or {}
        chat_id = data.get("chat_id")
        text = data.get("text", "").strip()
        
        if not chat_id or not text:
            return jsonify({"status": "error", "message": "chat_id and text required"}), 400
        
        session = get_session()
        try:
            tg_chat = session.query(TelegramChat).filter_by(id=chat_id, company_id=company_id).first()
            if not tg_chat:
                return jsonify({"status": "error", "message": "Chat not found"}), 404
            
            bot = session.query(TelegramBot).filter_by(id=tg_chat.bot_id, company_id=company_id, is_active=True).first()
            if not bot:
                return jsonify({"status": "error", "message": "Bot not active"}), 404
            
            bot_token = decrypt(bot.bot_token)
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": tg_chat.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML"
            }, timeout=10)
            
            result = resp.json()
            
            if result.get("ok"):
                tg_msg = TelegramMessage(
                    company_id=company_id,
                    chat_id=tg_chat.id,
                    direction="out",
                    text=text,
                    telegram_msg_id=result["result"].get("message_id"),
                    ts_ms=int(time.time() * 1000)
                )
                session.add(tg_msg)
                tg_chat.last_message_ts_ms = int(time.time() * 1000)
                session.commit()
                
                return jsonify({"status": "ok", "message": "Sent"}), 200
            else:
                return jsonify({"status": "error", "message": result.get("description", "Send failed")}), 500
            
        except Exception as e:
            session.rollback()
            return jsonify({"status": "error", "message": str(e)}), 500
        finally:
            session.close()