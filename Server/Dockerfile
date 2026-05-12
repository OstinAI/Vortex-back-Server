FROM python:3.10-slim

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Копируем файл зависимостей из КОРНЯ репозитория
COPY requirements.txt .

# 2. Устанавливаем их
RUN pip install --no-cache-dir -r requirements.txt

# 3. Копируем всё из папки Server
COPY Server/ .

ENV PORT 8080
EXPOSE 8080

CMD ["python", "Server.py"]
