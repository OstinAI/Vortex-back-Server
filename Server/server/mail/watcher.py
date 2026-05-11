# -*- coding: utf-8 -*-
import time
import threading
from collections import defaultdict, deque
#

_LOCK = threading.Lock()
ACTIVE_COMPANIES = set()
NEW_UIDS = defaultdict(lambda: defaultdict(deque))
_watcher_started = False

def mark_company_online(company_id: int):
    with _LOCK:
        ACTIVE_COMPANIES.add(int(company_id))

def start_watcher():
    global _watcher_started
    if _watcher_started: return
    _watcher_started = True
    t = threading.Thread(target=watcher_loop, daemon=True)
    t.start()

def watcher_loop():
    while True:
        with _LOCK:
            companies = list(ACTIVE_COMPANIES)
        
        if not companies:
            time.sleep(5)
            continue

        for cid in companies:
            try:
                poll_company_mail(cid)
            except Exception as e:
                print(f"[WATCHER] Error for company {cid}: {e}")
        time.sleep(2) # Интервал между проверками всех компаний

def poll_company_mail(company_id: int):
    from db.connection import get_session
    from db.models import MailAccount
    from utils.crypto import decrypt
    from server.mail.imap_client import MailRuIMAP
    from server.mail.store import save_message, list_uids, delete_message
    #

    session = get_session()
    acc = session.query(MailAccount).filter_by(company_id=company_id).first()
    if not acc: return

    imap = MailRuIMAP(acc.email, decrypt(acc.encrypted_password))
    
    try:
        folders = imap.list_folders()
        for f in folders:
            folder = f.get("imap_name")
            if not folder: continue

            try:
                imap.conn.select(folder)
                status, data = imap.conn.uid("search", None, "ALL")
                if status != "OK" or not data[0]: continue

                # Все UID с сервера (строки)
                all_imap_uids = [u.decode() for u in data[0].split()]
                # UID, которые уже есть на диске
                stored_uids_list = list_uids(company_id, folder)
                stored_uids = set(stored_uids_list)

                # 🔥 ИСПРАВЛЕННАЯ ЛОГИКА "БЕЗ ИСТОРИИ"
                if not stored_uids:
                    # Если папка пустая - качаем только последние 5
                    print(f"[WATCHER] First sync for {folder}. Keeping last 5.")
                    new_uids = all_imap_uids[-5:]
                else:
                    # Если на диске уже есть письма, находим самый большой UID
                    max_stored = max(int(u) for u in stored_uids)
                    # Берем только те письма, у которых UID больше нашего максимума
                    # Это гарантирует, что мы не полезем качать 5000 старых писем
                    new_uids = [u for u in all_imap_uids if int(u) > max_stored]

                # Сортируем по возрастанию, чтобы качать по порядку появления
                new_uids = sorted(new_uids, key=lambda x: int(x))
                
                for uid in new_uids:
                    msg = imap.fetch_message_full(folder, uid)
                    if not msg: continue
                    
                    msg["folder"] = folder
                    save_message(company_id, folder, uid, msg)

                    with _LOCK:
                        NEW_UIDS[company_id][folder].append(uid)

                # Удаление (теперь безопасно, так как мы знаем актуальный список)
                imap_uids_set = set(all_imap_uids)
                for uid in (stored_uids - imap_uids_set):
                    delete_message(company_id, folder, uid)

            except Exception as e:
                print(f"[WATCHER] Folder {folder} error: {e}")
                continue
    finally:
        try:
            imap.conn.logout()
        except:
            pass