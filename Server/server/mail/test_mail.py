# -*- coding: utf-8 -*-
import base64

from server.mail.imap_client import MailRuIMAP
from server.mail.smtp_client import send_mail
from utils.crypto import decrypt
from db.connection import get_session
from db.models import MailAccount, Company


# ===========================================================
#   1. ПОДКЛЮЧЕНИЕ К ПОЧТОВОМУ ЯЩИКУ
# ===========================================================

session = get_session()

company = session.query(Company).filter_by(name="БухПроф").first()
if not company:
    print("❌ Компания не найдена")
    exit()

account = session.query(MailAccount).filter_by(company_id=company.id).first()
if not account:
    print("❌ Почтовый аккаунт не привязан")
    exit()

password = decrypt(account.encrypted_password)
print(f"Используем email: {account.email}")

imap = MailRuIMAP(account.email, password)


# ===========================================================
#   2. ВЫВОД ВСЕХ ПАПОК
# ===========================================================

print("\n=== Список папок ===")
folders = imap.list_folders()

for f in folders:
    print(" -", f)


# ===========================================================
#   3. ВХОДЯЩИЕ (INBOX)
# ===========================================================

target_folder = "INBOX"
print(f"\n=== Папка: {target_folder} ===")

messages = imap.fetch_messages(target_folder, offset=0, limit=20)

print("Найдено писем:", len(messages))
for m in messages:
    print(f"UID={m['uid']} | {m['from']} | {m['subject']}")


# ===========================================================
#   4. ПОЛНОЕ ПИСЬМО ИЗ INBOX
# ===========================================================

if messages:
    uid = messages[0]["uid"]
    print(f"\n=== Полное письмо INBOX UID={uid} ===")

    full_msg = imap.fetch_message_full(target_folder, uid)

    print("Тема:", full_msg["subject"])
    print("От:", full_msg["from"])
    print("Дата:", full_msg["date"])

    print("\nTEXT:")
    print(full_msg["text"][:500])

    print("\nHTML:")
    print(full_msg["html"][:500])

    print("\nВложения:", len(full_msg["attachments"]))


# ===========================================================
#   5. СПАМ
# ===========================================================

spam_folder = None
for f in folders:
    if f["name"] == "Спам":
        spam_folder = f["imap_name"]

if spam_folder:
    print(f"\n=== Папка СПАМ ({spam_folder}) ===")

    spam_messages = imap.fetch_messages(spam_folder, offset=0, limit=20)
    print("Найдено писем:", len(spam_messages))

    for m in spam_messages:
        print(f"UID={m['uid']} | {m['from']} | {m['subject']}")

    if spam_messages:
        uid = spam_messages[0]["uid"]
        print(f"\n=== Полное письмо СПАМ UID={uid} ===")

        full_msg = imap.fetch_message_full(spam_folder, uid)
        print("HTML:")
        print(full_msg["html"][:500])
else:
    print("\n⚠ Папка 'Спам' не найдена")


# ===========================================================
#   6. ОТПРАВКА ПРОСТОГО ПИСЬМА
# ===========================================================

print("\n=== Отправка тестового письма ===")

try:
    send_mail(
        login=account.email,
        password=password,
        to=account.email,
        subject="Тестовое письмо от Vortex",
        html_body="<h1>Vortex Mail работает!</h1><p>Проверка SMTP.</p>"
    )
    print("📨 Письмо отправлено успешно")
except Exception as e:
    print("❌ Ошибка отправки:", e)


# ===========================================================
#   7. ОТПРАВКА ПИСЬМА С ВЛОЖЕНИЕМ
# ===========================================================

print("\n=== Отправка письма с вложением ===")

try:
    attachment_data = base64.b64encode(b"Hello from Vortex").decode()

    send_mail(
        login=account.email,
        password=password,
        to=account.email,
        subject="Vortex: письмо с вложением",
        html_body="<b>Файл во вложении</b>",
        attachments=[
            {
                "filename": "test.txt",
                "data": attachment_data
            }
        ]
    )
    print("📎 Письмо с вложением отправлено")
except Exception as e:
    print("❌ Ошибка отправки с вложением:", e)


# ===========================================================
#   8. ЗАКРЫТИЕ IMAP
# ===========================================================

try:
    imap.conn.logout()
except:
    pass

print("\n✅ ТЕСТ ПОЧТЫ ЗАВЕРШЁН")
