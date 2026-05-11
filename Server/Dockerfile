FROM python:3.10-slim

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем содержимое папки Server в текущую папку /app
COPY Server/ .

# Теперь требования будут лежать прямо в /app
RUN pip install --no-cache-dir -r requirements.txt

ENV PORT 8080
EXPOSE 8080

CMD ["python", "Server.py"]
