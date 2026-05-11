from cryptography.fernet import Fernet
import os

KEY_FILE = "secret.key"


def _load_key():
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        return key
    return open(KEY_FILE, "rb").read()


fernet = Fernet(_load_key())


def encrypt(text: str) -> str:
    return fernet.encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    return fernet.decrypt(token.encode()).decode()
