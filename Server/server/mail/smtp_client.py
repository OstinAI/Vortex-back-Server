# -*- coding: utf-8 -*-
import smtplib
import mimetypes # Добавлено для определения типа файла
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate
from email.header import Header # Добавлено для кодирования имен

def send_mail(login, password, to, subject, html_body, attachments=None):
    msg = MIMEMultipart()
    msg["From"] = login
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)

    msg.attach(MIMEText(html_body, "html"))

    # Вложения
    if attachments:
        for attach in attachments:
            filename = attach.get("filename", "file.bin")
            data = attach.get("data", b"")

            if isinstance(data, str):
                try:
                    import base64
                    data = base64.b64decode(data)
                except:
                    data = data.encode("utf-8", errors="ignore")

            # 🔥 1. Определяем тип файла (pdf, xlsx и т.д.)
            ctype, encoding = mimetypes.guess_type(filename)
            if ctype is None or encoding is not None:
                ctype = "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)

            part = MIMEBase(maintype, subtype)
            part.set_payload(data)
            encoders.encode_base64(part)

            # 🔥 2. Правильно кодируем имя файла для Mail.ru
            # Это предотвращает появление "Untitled.bin"
            encoded_filename = Header(filename, 'utf-8').encode()
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=encoded_filename
            )
            msg.attach(part)

    smtp = smtplib.SMTP_SSL("smtp.mail.ru", 465)
    smtp.login(login, password)
    smtp.send_message(msg)
    smtp.quit()

    return msg.as_bytes()