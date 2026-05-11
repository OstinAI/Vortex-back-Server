# -*- coding: utf-8 -*-
import asyncio
import time

from db.connection import get_session
from db.models import WhatsAppMessage, WhatsAppNumber
from server.whatsapp.utils import normalize_phone


# сколько времени держим "лок", если отправка не удалась (чтобы можно было повторить)
_GREET_LOCK_TTL_MS = 5 * 60 * 1000  # 5 минут


def get_greeting_settings(company_id, phone):
    s = get_session()
    try:
        row = (
            s.query(WhatsAppNumber)
            .filter_by(company_id=int(company_id), phone=phone)
            .first()
        )
        if not row:
            return False, ""
        return bool(getattr(row, "greeting_enabled", False)), (getattr(row, "greeting_text", "") or "")
    finally:
        s.close()


def set_greeting_settings(company_id, phone, enabled, text):
    s = get_session()
    try:
        row = (
            s.query(WhatsAppNumber)
            .filter_by(company_id=int(company_id), phone=phone)
            .first()
        )
        if not row:
            return False, "NUMBER_NOT_FOUND"

        row.greeting_enabled = bool(enabled)
        row.greeting_text = (text or "")
        s.commit()
        return True, "SAVED"
    except Exception as e:
        s.rollback()
        return False, str(e)
    finally:
        s.close()


def _now_ms():
    return int(time.time() * 1000)


def _peer_key(peer_raw: str) -> str:
    """
    Единый ключ клиента:
    - если это телефон -> нормализованный
    - если это имя -> оставляем как есть
    """
    peer_raw = (peer_raw or "").strip()
    if not peer_raw:
        return ""
    peer_norm = normalize_phone(peer_raw)  # может быть "" если это имя
    return peer_norm if peer_norm else peer_raw


def maybe_send_greeting(company_id, phone, peer_phone):
    wa_phone = normalize_phone(phone)
    if not wa_phone:
        return

    peer_raw = (peer_phone or "").strip()
    if not peer_raw:
        return

    peer_key = _peer_key(peer_raw)
    if not peer_key:
        return

    # 1) настройки
    enabled, greeting = get_greeting_settings(company_id, wa_phone)
    if not enabled or not greeting:
        return

    now_ms = _now_ms()

    # 2) антидубль: ставим "лок" в БД ДО отправки
    #    (иначе при 2 вызовах подряд out ещё не успевает записаться и приветствие уходит дважды)
    s = get_session()
    try:
        q = (
            s.query(WhatsAppMessage)
            .filter(WhatsAppMessage.company_id == int(company_id))
            .filter(WhatsAppMessage.wa_phone == wa_phone)
            .filter(WhatsAppMessage.direction == "out")
            .filter(WhatsAppMessage.peer_phone == peer_key)
        )

        # Если уже есть "sent" — точно не шлём
        sent = q.filter(getattr(WhatsAppMessage, "status", None) == "sent").first() if hasattr(WhatsAppMessage, "status") else None
        if sent:
            return

        # Если есть queued-сообщение (лок) свежее TTL — не шлём
        if hasattr(WhatsAppMessage, "status") and hasattr(WhatsAppMessage, "ts_ms"):
            queued = (
                q.filter(WhatsAppMessage.status == "queued")
                 .order_by(WhatsAppMessage.ts_ms.desc())
                 .first()
            )
            if queued and (now_ms - int(queued.ts_ms or 0) < _GREET_LOCK_TTL_MS):
                return

        # Ставим лок записью out/queued (даже если потом send упадёт, TTL разрешит повтор)
        m = WhatsAppMessage(
            company_id=int(company_id),
            wa_phone=wa_phone,
            peer_phone=peer_key,
            direction="out",
            text=greeting,
            ts_ms=now_ms
        )
        # если в модели есть status — используем
        if hasattr(m, "status"):
            m.status = "queued"

        s.add(m)
        s.commit()
    except Exception:
        s.rollback()
        return
    finally:
        s.close()

    # 3) отправка — отправляем на peer_key (единый ключ)
    from server.whatsapp.manager import wa_manager
    session = wa_manager.get(company_id, wa_phone)
    if not session:
        return

    try:
        if session._loop and session._loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(
                session.send_text(peer_key, greeting),
                session._loop
            )
            fut.result(timeout=30)
    except Exception:
        # лок уже стоит; повтор разрешится после TTL
        pass