FROM python:3.10-slim

# Ставим зависимости для системы
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Шаг 1: Копируем ВООБЩЕ ВСЁ, что есть в папке
COPY . .

# Шаг 2: Смотрим, что реально видит Docker (это появится в логах, если упадет)
RUN ls -la

# Шаг 3: Устанавливаем зависимости (используем маску *.txt на случай ошибки в имени)
RUN pip install --no-cache-dir -r requirements*
