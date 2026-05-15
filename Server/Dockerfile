FROM python:3.10-slim

# Устанавливаем системные зависимости для Playwright и компиляции
RUN apt-get update && apt-get install -y \
    build-essential \
    libnss3 \
    libnspr4 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/Server

# Копируем твой обновленный список зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Установка браузеров для Playwright (так как он есть в твоем списке)
RUN playwright install --with-deps chromium

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PORT 8080

# Запуск через gunicorn с использованием eventlet
# Убираем --worker-class eventlet и оставляем надежные потоки
# Заходим в самую глубокую папку, где лежит app.py
# Теперь Gunicorn сам вызовет функцию и инициализирует приложение
CMD exec gunicorn --worker-class eventlet --workers 1 --bind :$PORT "server.app:create_app()"
