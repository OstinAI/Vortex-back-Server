FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Указываем путь к файлу внутри папки Server
COPY Server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем всё содержимое папки Server в рабочую директорию /app
COPY Server/ .

ENV PORT 8080
EXPOSE 8080

# Теперь Server.py будет лежать прямо в /app, поэтому путь остается таким
CMD ["python", "Server.py"]
