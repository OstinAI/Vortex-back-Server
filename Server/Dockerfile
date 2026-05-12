FROM python:3.10-slim

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем всё содержимое папки Server в /app
COPY . .

ENV PORT 8080
EXPOSE 8080

# ЗАПУСКАЕМ ВАШ ФАЙЛ app.py
CMD ["python", "server/app.py"]
