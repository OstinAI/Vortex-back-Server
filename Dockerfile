# Используем официальный образ Python
FROM python:3.10-slim

# Устанавливаем системные зависимости (если нужны для библиотек)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую папку в контейнере
WORKDIR /app

# Копируем файл зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все остальные файлы проекта
COPY . .

# Указываем порт, который ожидает Google Cloud Run (8080)
ENV PORT 8080
EXPOSE 8080

# Команда для запуска вашего сервера
# Замените Server.py на whatsapp_proxy.py, если основной файл другой
CMD ["python", "Server.py"]
