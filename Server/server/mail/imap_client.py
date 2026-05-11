# -*- coding: utf-8 -*-
import imaplib
import email
from email.header import decode_header
import base64
import codecs
import time

# ---------------------------------------------------------
# Декодирование русских папок IMAP (Modified UTF-7)
# ---------------------------------------------------------
def decode_imap_utf7(s: str) -> str:
    try:
        return codecs.decode(s, "imap4-utf-7")
    except:
        return s


class MailRuIMAP:

    # ---------------------------------------------------------
    # Карта известных системных папок Mail.ru
    # ---------------------------------------------------------
    KNOWN_FOLDERS = {
        "INBOX": "Входящие",
        "&BCEEPwQwBDw-": "Черновики",
        "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-": "Отправленные",
        "&BCcENQRABD0EPgQyBDgEOgQ4-": "Спам",
        "&BBoEPgRABDcEOAQ9BDA-": "Корзина",
        "INBOX/Social": "Социальные сети",
        "INBOX/Newsletters": "Рассылки"
    }


    # ---------------------------------------------------------
    # ИНИЦИАЛИЗАЦИЯ
    # ---------------------------------------------------------
    def __init__(self, login: str, password: str):
        self.login = login
        self.password = password
        self.conn = imaplib.IMAP4_SSL("imap.mail.ru", 993)
        self.conn.login(login, password)


    # ---------------------------------------------------------
    # СПИСОК ПАПОК
    # ---------------------------------------------------------
    def list_folders(self):
        status, folders = self.conn.list()
        result = []

        if status != "OK":
            return result

        for f in folders:
            try:
                line = f.decode()

                if '"' in line:
                    raw_folder = line.split('"')[-2]
                else:
                    raw_folder = line.split(" ")[-1]

                decoded_name = decode_imap_utf7(raw_folder)
                pretty_name = self.KNOWN_FOLDERS.get(raw_folder, decoded_name)

                result.append({
                    "name": pretty_name,
                    "imap_name": raw_folder
                })

            except Exception as e:
                print("Folder decode error:", e)
                continue

        return result


    # ---------------------------------------------------------
    # ЗАГРУЗКА ПИСЕМ (HEADERS, offset + limit)
    # ---------------------------------------------------------
    def fetch_messages(self, folder, offset=0, limit=50):
        self.conn.select(folder)
        result, data = self.conn.uid("search", None, "ALL")
        if result != "OK" or not data[0]:
            return []

        uids = data[0].split()
        uids = uids[::-1]  # Новые сверху
        selected = uids[offset: offset + limit]

        emails = []
        for uid in selected:
            # Запрашиваем только заголовки (HEADER) для скорости списка
            result, msg_data = self.conn.uid("fetch", uid, "(RFC822.HEADER)")
            if result != "OK" or not msg_data:
                continue

            # Парсим заголовки через библиотеку email
            msg = email.message_from_bytes(msg_data[0][1])

            emails.append({
                "uid": uid.decode(),
                "subject": self.decode_header(msg.get("Subject")),
                "from": self.decode_header(msg.get("From")),
                "to": self.decode_header(msg.get("To")),
                "date": msg.get("Date")
            })
        return emails


    # ---------------------------------------------------------
    # ВСПОМОГАТЕЛЬНОЕ – извлечение заголовка
    # ---------------------------------------------------------
    def _extract_header(self, raw, header_name):
        for line in raw.split("\n"):
            if line.lower().startswith(header_name.lower() + ":"):
                value = line.split(":", 1)[1].strip()
                return self.decode_header(value)
        return ""


    # ---------------------------------------------------------
    # ПОЛНОЕ ПИСЬМО (BODY + HTML + ATTACHMENTS)
    # ---------------------------------------------------------
    def fetch_message_full(self, folder: str, uid: str):
        self.conn.select(folder, readonly=True)
        status, msg_data = self.conn.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not msg_data:
            return None

        msg = email.message_from_bytes(msg_data[0][1])
        
        res = {
            "uid": uid,
            "message_id": msg.get("Message-ID"),
            "from": self.decode_header(msg.get("From")),
            "to": self.decode_header(msg.get("To")),
            "subject": self.decode_header(msg.get("Subject")),
            "date": msg.get("Date"),
            "text": "",
            "html": "",
            "attachments": []
        }

        # Рекурсивно обходим все части письма (даже глубоко вложенные)
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))

            # Если это вложение (файл)
            if "attachment" in content_disposition or part.get_filename():
                filename = self.decode_header(part.get_filename())
                if filename:
                    payload = part.get_payload(decode=True)
                    if payload:
                        cid = (part.get("Content-ID") or "").strip("<>")
                        res["attachments"].append({
                            "filename": filename,
                            "content_id": cid,
                            "data": base64.b64encode(payload).decode()
                        })
            # Если это текстовое содержимое
            else:
                if content_type == "text/html":
                    res["html"] = self.decode_body(part)
                elif content_type == "text/plain" and not res["html"]:
                    res["text"] = self.decode_body(part)

        return res



    # ---------------------------------------------------------
    # УДАЛЕНИЕ ПИСЬМА
    # ---------------------------------------------------------
    def delete_message(self, folder: str, uid: str):
        self.conn.select(folder)
        self.conn.uid("STORE", uid, "+FLAGS", "\\Deleted")
        self.conn.expunge()
        return True


    # ---------------------------------------------------------
    # ПЕРЕМЕЩЕНИЕ В КОРЗИНУ
    # ---------------------------------------------------------
    def move_to_trash(self, uid: str):
        trash_folder = "&BBoEPgRABDcEOAQ9BDA-"

        result = self.conn.uid("COPY", uid, trash_folder)
        if result[0] == "OK":
            self.conn.uid("STORE", uid, "+FLAGS", "\\Deleted")

        return True


    # ---------------------------------------------------------
    # ДЕКОДЕРЫ
    # ---------------------------------------------------------
    @staticmethod
    def decode_header(value):
        if not value:
            return ""
        try:
            # decode_header возвращает список частей [(текст, кодировка), ...]
            parts = decode_header(value)
            decoded_parts = []
            
            for decoded, charset in parts:
                if isinstance(decoded, bytes):
                    # Декодируем каждую часть отдельно
                    decoded_parts.append(decoded.decode(charset or "utf-8", errors="ignore"))
                else:
                    decoded_parts.append(str(decoded))
            
            # Склеиваем все части (Имя + <email>) обратно в одну строку
            return "".join(decoded_parts)
        except Exception:
            return str(value)

    @staticmethod
    def decode_body(part):
        try:
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if payload:
                return payload.decode(charset, errors="ignore")
            return ""
        except:
            return ""

    def get_last_uid(self):
        self.conn.select("INBOX", readonly=True)
        status, data = self.conn.uid("search", None, "ALL")
        if status != "OK" or not data[0]:
            return None
        return int(data[0].split()[-1])


    # ---------------------------------------------------------
    # ЗАГРУЗКА ВСЕХ ПИСЕМ ИЗО ВСЕХ ПАПОК
    # ---------------------------------------------------------
    def fetch_all_messages_with_folders(self):
        result = []

        folders = self.list_folders()
        if not folders:
            return result

        for f in folders:
            folder_name = f["imap_name"]

            try:
                self.conn.select(folder_name, readonly=True)

                status, data = self.conn.uid("search", None, "ALL")
                if status != "OK" or not data or not data[0]:
                    continue

                uids = data[0].split()

                for uid in uids:
                    full = self.fetch_message_full(folder_name, uid.decode())
                    if not full:
                        continue

                    # 🔥 ВОТ ГЛАВНОЕ
                    full["folder"] = folder_name

                    result.append(full)

            except Exception as e:
                print("IMAP folder error:", folder_name, e)
                continue

        return result

   
    # Добавь этот метод внутрь класса MailRuIMAP
    def append_to_sent(self, raw_msg_bytes):
        """
        Записывает готовое письмо в папку 'Отправленные' на сервере Mail.ru.
        """
        # Техническое имя папки "Отправленные" из твоего словаря KNOWN_FOLDERS
        sent_folder = "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"
        
        try:
            # Превращаем текущее время в формат IMAP
            internal_date = imaplib.Time2Internaldate(time.time())
            
            # Команда APPEND: папка, флаги (прочитано), дата, само письмо
            self.conn.append(sent_folder, '\\Seen', internal_date, raw_msg_bytes)
            return True
        except Exception as e:
            print(f"[IMAP APPEND ERROR] Не удалось сохранить в Отправленные: {e}")
            return False

    # ---------------------------------------------------------
    # ДЕКОДЕРЫ (Вставь эти версии в самый конец класса)
    # ---------------------------------------------------------
    @staticmethod
    def decode_header(value):
        if not value:
            return ""
        try:
            # decode_header возвращает список частей [(текст, кодировка), ...]
            parts = decode_header(value)
            decoded_parts = []
            for decoded, charset in parts:
                if isinstance(decoded, bytes):
                    # Если кодировка не указана, используем utf-8 или latin-1
                    decoded_parts.append(decoded.decode(charset or "utf-8", errors="ignore"))
                else:
                    decoded_parts.append(str(decoded))
            return "".join(decoded_parts)
        except Exception:
            return str(value)

    @staticmethod
    def decode_body(part):
        try:
            # get_payload(decode=True) автоматически убирает quoted-printable и base64
            payload = part.get_payload(decode=True)
            if not payload:
                return ""
            
            charset = part.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="ignore")
        except:
            return ""