# Используем официальный образ Python
FROM python:3.10-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую папку в контейнере
WORKDIR /app

# Исправляем путь: берем файл из папки Server
COPY Server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем всё содержимое папки Server прямо в /app
COPY Server/ .

# Указываем порт
ENV PORT 8080
EXPOSE 8080

# Запускаем сервер (так как мы скопировали содержимое Server/ в /app, 
# файл Server.py будет лежать прямо в корне /app)
CMD ["python", "Server.py"]
