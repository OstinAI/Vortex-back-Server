# -*- coding: utf-8 -*-
from flask_socketio import SocketIO

# Создаем объект СОКЕТА. Важно: именно здесь он рождается!
socketio = SocketIO(cors_allowed_origins="*")