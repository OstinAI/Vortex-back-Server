# -*- coding: utf-8 -*-
import os
import base64
import hashlib

# Стандартное количество итераций PBKDF2
DEFAULT_ITERATIONS = 350000


# ===========================================================
# 1) ЛЁГКИЙ ХЕШ КЛИЕНТА (SHA256 → Base64)
# ===========================================================
def make_client_hash(password: str) -> str:
    """
    Превращает пароль в лёгкий хеш:
    SHA256 → Base64.
    Используется перед PBKDF2.
    """
    if password is None:
        password = ""

    sha = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(sha).decode("utf-8")


# ===========================================================
# 2) Солёный серверный хеш PBKDF2
# ===========================================================
def generate_salt(length: int = 16) -> str:
    """
    Генерация соли, возвращаем base64-строку.
    """
    return base64.b64encode(os.urandom(length)).decode('utf-8')


def hash_password(client_hash: str, salt: str = None, iterations: int = DEFAULT_ITERATIONS):
    """
    Хеширование client_hash через PBKDF2-HMAC-SHA256.

    client_hash — это результат make_client_hash()

    Возвращает tuple:
      (password_hash, salt, iterations)
    """
    if salt is None:
        salt = generate_salt()

    dk = hashlib.pbkdf2_hmac(
        'sha256',
        client_hash.encode('utf-8'),
        salt.encode('utf-8'),
        iterations
    )
    password_hash = base64.b64encode(dk).decode('utf-8')
    return password_hash, salt, iterations


# ===========================================================
# 3) Проверка пароля
# ===========================================================
def verify_password(client_hash: str, stored_hash: str, salt: str, iterations: int) -> bool:
    """
    Проверяет пароль:
      1) делаем PBKDF2 от client_hash
      2) сравниваем со stored_hash
    """
    new_hash, _, _ = hash_password(client_hash, salt=salt, iterations=iterations)
    return new_hash == stored_hash
