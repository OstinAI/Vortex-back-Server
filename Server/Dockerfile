FROM python:3.10-slim

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# --no-cache-dir гарантирует, что мы скачаем свежую версию eventlet
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PORT 8080

# ВАЖНО: 'server.app:app' означает: папка server, файл app, объект app
CMD exec gunicorn --bind :$PORT --workers 1 --worker-class eventlet --threads 8 'server.app:app'
