# -*- coding: utf-8 -*-
import os
import json
import base64
import shutil

BASE_DIR = os.path.dirname(__file__)
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
MSG_DIR = os.path.join(STORAGE_DIR, "messages")
ATT_DIR = os.path.join(STORAGE_DIR, "attachments")

os.makedirs(MSG_DIR, exist_ok=True)
os.makedirs(ATT_DIR, exist_ok=True)


def _safe_folder_name(folder: str) -> str:
    """
    Делает имя папки безопасным для Windows.
    """
    if not folder:
        return "INBOX"
    s = folder.strip()
    s = s.replace("\\", "_").replace("/", "_").replace(":", "_")
    return s


def _msg_folder(company_id: int, folder: str) -> str:
    folder = _safe_folder_name(folder)
    path = os.path.join(MSG_DIR, str(company_id), folder)
    os.makedirs(path, exist_ok=True)
    return path


def _att_folder(company_id: int, folder: str, uid: str) -> str:
    folder = _safe_folder_name(folder)
    path = os.path.join(ATT_DIR, str(company_id), folder, str(uid))
    os.makedirs(path, exist_ok=True)
    return path


def list_folders(company_id: int):
    base = os.path.join(MSG_DIR, str(company_id))
    if not os.path.exists(base):
        return []
    out = []
    for name in os.listdir(base):
        p = os.path.join(base, name)
        if os.path.isdir(p):
            out.append(name)
    out.sort()
    return out


def list_uids(company_id: int, folder: str):
    path = _msg_folder(company_id, folder)
    uids = []
    for fn in os.listdir(path):
        if fn.endswith(".json"):
            uids.append(fn[:-5])
    return uids


def save_message(company_id: int, folder: str, uid: str, msg: dict):
    """
    Сохраняет письмо JSON: storage/messages/{company_id}/{folder}/{uid}.json
    """
    path = os.path.join(_msg_folder(company_id, folder), f"{uid}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(msg, f, ensure_ascii=False, indent=2)


def load_message(company_id: int, folder: str, uid: str):
    """
    Загружает письмо JSON
    """
    path = os.path.join(_msg_folder(company_id, folder), f"{uid}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_attachments(company_id: int, folder: str, uid: str, attachments: list):
    """
    Сохраняет вложения: storage/attachments/{company_id}/{folder}/{uid}/{filename}
    В msg лучше хранить только список filenames (без base64).
    """
    if not attachments:
        return []

    saved_files = []
    folder_path = _att_folder(company_id, folder, uid)

    for a in attachments:
        try:
            filename = a.get("filename", "file.bin")
            data_b64 = a.get("data", "")
            if not data_b64:
                continue

            data = base64.b64decode(data_b64)
            full_path = os.path.join(folder_path, filename)

            with open(full_path, "wb") as f:
                f.write(data)

            saved_files.append(filename)
        except:
            continue

    return saved_files


def delete_by_message_id(company_id, folder, message_id):
    path = _msg_folder(company_id, folder)

    if not message_id:
        return

    # нормализация message_id
    target = str(message_id).strip().lower()

    if not os.path.isdir(path):
        return

    for fname in os.listdir(path):
        if not fname.endswith(".json"):
            continue

        full = os.path.join(path, fname)
        try:
            with open(full, "r", encoding="utf-8") as f:
                data = json.load(f)

            mid = data.get("message_id")
            if not mid:
                continue

            if str(mid).strip().lower() == target:
                os.remove(full)
        except Exception:
            pass


def delete_message(company_id: int, folder: str, uid: str):
    """
    Удаляет письмо и его вложения из storage:
      - storage/messages/{company_id}/{folder}/{uid}.json
      - storage/attachments/{company_id}/{folder}/{uid}/...
    """
    # 1) удалить json письма
    msg_path = os.path.join(_msg_folder(company_id, folder), f"{uid}.json")
    try:
        if os.path.exists(msg_path):
            os.remove(msg_path)
    except Exception:
        pass

    # 2) удалить папку вложений
    att_path = os.path.join(_att_folder(company_id, folder, uid))
    try:
        if os.path.isdir(att_path):
            # рекурсивно удалить каталог
            for root, dirs, files in os.walk(att_path, topdown=False):
                for name in files:
                    try:
                        os.remove(os.path.join(root, name))
                    except Exception:
                        pass
                for name in dirs:
                    try:
                        os.rmdir(os.path.join(root, name))
                    except Exception:
                        pass
            try:
                os.rmdir(att_path)
            except Exception:
                pass
    except Exception:
        pass

def delete_all_company_data(company_id: int):
    """
    Полностью удаляет все данные почты компании (все папки, письма и вложения).
    Используется при удалении интеграции.
    """
    # Путь к корневой папке сообщений компании
    msg_path = os.path.join(MSG_DIR, str(company_id))
    # Путь к корневой папке вложений компании
    att_path = os.path.join(ATT_DIR, str(company_id))

    for path in [msg_path, att_path]:
        try:
            if os.path.exists(path):
                # shutil.rmtree удаляет дерево директорий целиком
                shutil.rmtree(path)
        except Exception as e:
            print(f"Error while deleting company data at {path}: {e}")