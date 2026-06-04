from db.connection import get_session
from db.models import SystemSetting

def get_setting(key: str) -> str | None:
    session = get_session()
    setting = session.query(SystemSetting).filter_by(key=key).first()
    session.close()
    return setting.value if setting else None

def get_google_credentials():
    client_id = get_setting('google_client_id')
    client_secret = get_setting('google_client_secret')
    if not client_id or not client_secret:
        raise ValueError("Google credentials not found in database")
    return client_id, client_secret