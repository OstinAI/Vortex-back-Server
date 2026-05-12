FROM python:3.10-slim

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Теперь Docker ищет файл прямо в контексте (которым является папка Server)
COPY requirements.txt .

# 2. Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# 3. Копируем ВСЁ содержимое текущей папки (Server/) в /app
# Больше не пишем COPY Server/ ., так как мы уже "внутри" неё
COPY . .

ENV PORT 8080
EXPOSE 8080

# Убедись, что файл называется Server.py (с большой буквы, как на скрине)
CMD ["python", "Server.py"]
