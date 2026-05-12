FROM python:3.10-slim

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Копируем requirements.txt из корня контекста сборки
COPY requirements.txt .

# 2. Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# 3. Копируем содержимое папки Server в текущую директорию (/app)
COPY Server/ .

ENV PORT 8080
EXPOSE 8080

# Убедитесь, что Server.py действительно оказался в корне /app
CMD ["python", "Server.py"]
