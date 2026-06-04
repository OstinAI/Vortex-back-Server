# -*- coding: utf-8 -*-
import os
import requests
from flask import Blueprint, request, jsonify, redirect, current_app, session
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta

# Абсолютные импорты относительно корня запуска приложения Vortex
from db.connection import get_session
from db.models import User
from utils.security import token_required
from utils.crypto import encrypt, decrypt
from server.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

google_calendar_bp = Blueprint('google_calendar', __name__)

# Отключаем HTTPS только для локальной разработки (в продакшене убрать)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'


if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set")

GOOGLE_CLIENT_CONFIG = {
    "web": {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

SCOPES = ['https://www.googleapis.com/auth/calendar.events']


def refresh_google_token(user):
    """Обновляет истёкший токен Google"""
    if not user.google_refresh_token:
        return None

    decrypted_refresh_token = decrypt(user.google_refresh_token)

    credentials = Credentials(
        token=None,
        refresh_token=decrypted_refresh_token,
        token_uri=GOOGLE_CLIENT_CONFIG["web"]["token_uri"],
        client_id=GOOGLE_CLIENT_CONFIG["web"]["client_id"],
        client_secret=GOOGLE_CLIENT_CONFIG["web"]["client_secret"]
    )

    from google.auth.transport.requests import Request
    credentials.refresh(Request())

    # Сохраняем новый refresh_token если он изменился
    if credentials.refresh_token and credentials.refresh_token != decrypted_refresh_token:
        user.google_refresh_token = encrypt(credentials.refresh_token)
        session_db = get_session()
        session_db.add(user)
        session_db.commit()
        session_db.close()

    return credentials


def get_google_credentials_for_user(user):
    if not user.google_refresh_token:
        return None
    
    decrypted_refresh_token = decrypt(user.google_refresh_token)
    
    credentials = Credentials(
        token=None,
        refresh_token=decrypted_refresh_token,
        token_uri=GOOGLE_CLIENT_CONFIG["web"]["token_uri"],
        client_id=GOOGLE_CLIENT_CONFIG["web"]["client_id"],
        client_secret=GOOGLE_CLIENT_CONFIG["web"]["client_secret"]
    )
    
    # Обновляем токен если истёк
    from google.auth.transport.requests import Request
    if credentials.expired:
        try:
            credentials.refresh(Request())
            print("✅ Токен успешно обновлён")
        except Exception as e:
            print(f"❌ Ошибка обновления токена: {e}")
            return None
    
    return credentials


# ==========================================
# 1. СТАРТ ИНТЕГРАЦИИ (Вызывается из ЛК сотрудника)
# ==========================================
@google_calendar_bp.route('/initiate', methods=['GET'])
@token_required
def initiate():
    current_user_info = request.user
    user_id = int(current_user_info.get("user_id"))
    
    session_db = get_session()
    user = session_db.query(User).filter_by(id=user_id).first()
    
    redirect_uri = f"{request.url_root.rstrip('/')}/api/v1/google/callback"
    flow = Flow.from_client_config(GOOGLE_CLIENT_CONFIG, scopes=SCOPES, redirect_uri=redirect_uri)
    
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=str(user_id)
    )
    
    if user:
        user.oauth_verifier = flow.code_verifier 
        session_db.commit()
    
    session_db.close()
    
    return jsonify({"status": "ok", "url": auth_url}), 200


# ==========================================
# 2. GOOGLE CALLBACK (Куда перенаправляет Google)
# ==========================================
@google_calendar_bp.route('/callback', methods=['GET'])
def callback():
    user_id = request.args.get('state')
    if not user_id:
        return jsonify({"status": "error", "message": "Missing state"}), 400

    session_db = get_session()
    user = session_db.query(User).filter_by(id=int(user_id)).first()
    
    if not user or not user.oauth_verifier:
        session_db.close()
        return jsonify({"status": "error", "message": "Verifier not found. Restart integration."}), 400
    
    code_verifier = user.oauth_verifier
    
    redirect_uri = f"{request.url_root.rstrip('/')}/api/v1/google/callback"
    flow = Flow.from_client_config(GOOGLE_CLIENT_CONFIG, scopes=SCOPES, redirect_uri=redirect_uri)
    flow.code_verifier = code_verifier
    
    try:
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials
        
        user.google_refresh_token = encrypt(credentials.refresh_token)
        user.google_calendar_connected = True
        user.oauth_verifier = None 
        
        session_db.commit()
        session_db.close()
        
        return """
            <html>
                <script>
                    if (window.opener) {
                        window.opener.postMessage('google_auth_success', '*');
                    }
                    window.close();
                </script>
                <body>
                    <h3>Интеграция успешно настроена! Закрытие окна...</h3>
                </body>
            </html>
        """, 200
        
    except Exception as e:
        session_db.close()
        print(f"!!! DEBUG ERROR: {e}") 
        return jsonify({"status": "error", "details": str(e)}), 500


# ==========================================
# 3. СОЗДАНИЕ ВСТРЕЧИ (CRUD: Create)
# ==========================================
@google_calendar_bp.route('/event', methods=['POST'])
@token_required
def create_event():
    current_user_info = request.user
    data = request.get_json(silent=True) or {}
    
    print("=" * 50)
    print("🔵 ПОЛУЧЕН ЗАПРОС НА СОЗДАНИЕ СОБЫТИЯ В GOOGLE")
    print(f"📋 Данные: {data}")
    print(f"👤 Пользователь: {current_user_info.get('user_id')}")
    
    summary = data.get('summary', 'Встреча Vortex CRM')
    description = data.get('description', '')
    minutes_duration = int(data.get('duration', 30))
    color_id = data.get('colorId', '5')

    session_db = get_session()
    user = session_db.query(User).filter_by(id=current_user_info["user_id"]).first()
    session_db.close()
    
    if not user:
        print("❌ Пользователь не найден в БД")
        return jsonify({"status": "error", "message": "User not found"}), 404
    
    print(f"🔑 У пользователя google_refresh_token: {bool(user.google_refresh_token)}")
    
    creds = get_google_credentials_for_user(user)
    if not creds:
        print("❌ Нет Google токена у пользователя. Нужно переподключить интеграцию!")
        return jsonify({"status": "error", "message": "Интеграция с Google не настроена"}), 400

    try:
        print("🔄 Создаём сервис Google Calendar...")
        service = build('calendar', 'v3', credentials=creds)

        # Берём время из задачи, если передано
        if data.get('start_ts_ms'):
            # 🔥 ИСПРАВЛЕНО: используем UTC вместо локального времени
            start_time = datetime.utcfromtimestamp(data['start_ts_ms'] / 1000).isoformat() + 'Z'
            print(f"📅 start_ts_ms: {data['start_ts_ms']}")
            print(f"📅 UTC время для Google: {start_time}")
        else:
            start_time = datetime.utcnow().isoformat() + 'Z'
            print(f"📅 Текущее UTC время: {start_time}")

        end_time = (datetime.fromisoformat(start_time.replace('Z', '')) + timedelta(minutes=minutes_duration)).isoformat() + 'Z'

        event_body = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_time, 'timeZone': 'UTC'},
            'end': {'dateTime': end_time, 'timeZone': 'UTC'},
            'colorId': color_id
        }
        
        print(f"📅 Событие: {event_body}")

        event = service.events().insert(calendarId='primary', body=event_body).execute()
        print(f"✅ УСПЕХ! Событие создано: {event.get('htmlLink')}")
        print("=" * 50)
        
        return jsonify({"status": "ok", "event_id": event.get('id'), "html_link": event.get('htmlLink')}), 201

    except Exception as e:
        print(f"❌ ОШИБКА GOOGLE API: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 50)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# 4. РЕДАКТИРОВАНИЕ ВСТРЕЧИ (CRUD: Update)
# ==========================================
@google_calendar_bp.route('/event/<event_id>', methods=['PUT'])
@token_required
def update_event(event_id):
    current_user_info = request.user
    data = request.get_json(silent=True) or {}
    
    print(f"📥 Получен PUT запрос для обновления события {event_id}")
    print(f"📥 Данные: {data}")
    
    session_db = get_session()
    user = session_db.query(User).filter_by(id=current_user_info["user_id"]).first()
    session_db.close()
    
    creds = get_google_credentials_for_user(user)
    if not creds:
        return jsonify({"status": "error", "message": "Интеграция с Google не настроена"}), 400

    try:
        service = build('calendar', 'v3', credentials=creds)
        event = service.events().get(calendarId='primary', eventId=event_id).execute()

        # Обновляем поля
        if 'summary' in data: 
            event['summary'] = data['summary']
        if 'description' in data: 
            event['description'] = data['description']
        if 'colorId' in data: 
            event['colorId'] = data['colorId']
        
        # 🔥 ОБНОВЛЯЕМ ВРЕМЯ, если передано start_ts_ms
        if 'start_ts_ms' in data and data['start_ts_ms']:
            from datetime import datetime, timedelta
            start_time = datetime.utcfromtimestamp(data['start_ts_ms'] / 1000).isoformat() + 'Z'
            duration = data.get('duration', 30)
            end_time = (datetime.fromisoformat(start_time.replace('Z', '')) + timedelta(minutes=duration)).isoformat() + 'Z'
            
            event['start'] = {'dateTime': start_time, 'timeZone': 'UTC'}
            event['end'] = {'dateTime': end_time, 'timeZone': 'UTC'}
            print(f"🕐 Обновляем время: {start_time} -> {end_time}")

        updated_event = service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
        print(f"✅ Событие {event_id} обновлено в Google")
        return jsonify({"status": "ok", "updated_summary": updated_event.get('summary')}), 200

    except Exception as e:
        print(f"❌ Ошибка Google API: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# 5. УДАЛЕНИЕ ВСТРЕЧИ (CRUD: Delete)
# ==========================================
@google_calendar_bp.route('/event/<event_id>', methods=['DELETE'])
@token_required
def delete_event(event_id):
    current_user_info = request.user
    
    session_db = get_session()
    user = session_db.query(User).filter_by(id=current_user_info["user_id"]).first()
    session_db.close()
    
    creds = get_google_credentials_for_user(user)
    if not creds:
        return jsonify({"status": "error", "message": "Интеграция с Google не настроена"}), 400

    try:
        service = build('calendar', 'v3', credentials=creds)
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        return jsonify({"status": "ok", "message": "Событие успешно удалено из Google"}), 200

    except Exception as e:
        print(f"Google API Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# 6. ОТКЛЮЧЕНИЕ ИНТЕГРАЦИИ (Revoke)
# ==========================================
@google_calendar_bp.route('/revoke', methods=['POST'])
@token_required
def revoke_integration():
    current_user_info = request.user
    
    session_db = get_session()
    user = session_db.query(User).filter_by(id=current_user_info["user_id"]).first()
    
    if not user:
        session_db.close()
        return jsonify({"status": "error", "message": "User not found"}), 404

    try:
        if user.google_refresh_token:
            decrypted_token = decrypt(user.google_refresh_token)
            requests.post('https://oauth2.googleapis.com/revoke',
                          params={'token': decrypted_token},
                          headers={'content-type': 'application/x-www-form-urlencoded'})
        
        user.google_refresh_token = None
        user.google_calendar_connected = False
        user.oauth_verifier = None
        
        session_db.commit()
        session_db.close()
        
        return jsonify({"status": "ok", "message": "Интеграция полностью отключена"}), 200
        
    except Exception as e:
        session_db.rollback()
        session_db.close()
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# 7. СТАТУС ИНТЕГРАЦИИ
# ==========================================     
@google_calendar_bp.route('/status', methods=['GET'])
@token_required
def check_status():
    current_user_info = request.user
    
    session_db = get_session()
    user = session_db.query(User).filter_by(id=current_user_info["user_id"]).first()
    connected = bool(user and user.google_refresh_token)
    session_db.close()
    
    return jsonify({"connected": connected}), 200

