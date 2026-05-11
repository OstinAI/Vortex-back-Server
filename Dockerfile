FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Попробуем скопировать всё сразу, чтобы не возникало ошибок с отдельными файлами
COPY . .

# Устанавливаем зависимости из файла, который теперь точно в корне
RUN pip install --no-cache-dir -r requirements.txt

ENV PORT 8080
EXPOSE 8080

# Проверьте, что Server.py лежит в корне репозитория (не в папке)
CMD ["python", "Server.py"]
