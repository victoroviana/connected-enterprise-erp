import os
from datetime import timedelta

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "t", "yes", "y", "sim"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "SQLALCHEMY_DATABASE_URI", "sqlite:///app.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = _env_bool(
        "SQLALCHEMY_TRACK_MODIFICATIONS", False
    )

    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    MAIL_SERVER = os.getenv("MAIL_SERVER")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "0") or 0)
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", False)
    MAIL_USE_SSL = _env_bool("MAIL_USE_SSL", False)
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER")
    MAIL_SENDER = os.getenv("MAIL_SENDER")  # alternativa explícita
    MAIL_REPLY_TO = os.getenv("MAIL_REPLY_TO")
    MAIL_ENABLED = _env_bool("MAIL_ENABLED", True)
    MAIL_BASE_URL = os.getenv("MAIL_BASE_URL")

    GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    GOOGLE_DELEGATED_USER = os.getenv("GOOGLE_DELEGATED_USER")
    GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
    GOOGLE_MEET_TIMEZONE = os.getenv("GOOGLE_MEET_TIMEZONE", "America/Sao_Paulo")
    GOOGLE_MEET_DURATION_MINUTES = int(os.getenv("GOOGLE_MEET_DURATION_MINUTES", "180") or 180)
    GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    GOOGLE_OAUTH_REFRESH_TOKEN = os.getenv("GOOGLE_OAUTH_REFRESH_TOKEN")
    GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    GOOGLE_OAUTH_TOKEN_URI = os.getenv(
        "GOOGLE_OAUTH_TOKEN_URI", "https://oauth2.googleapis.com/token"
    )
    SATISFACAO_URL_BASE = os.getenv(
        "SATISFACAO_URL_BASE",
        "https://example.com/pesquisa.php?id={id}",
    )

    # Limite de upload de arquivos — igual ao limite do Outlook (20 MB por anexo)
    MAX_CONTENT_MB: int = int(os.getenv("MAX_CONTENT_MB", "20"))  # 20 MB por arquivo
    MAX_CONTENT_LENGTH: int = int(os.getenv("MAX_CONTENT_LENGTH_MB", "25")) * 1024 * 1024  # 25 MB margem HTTP

    UPLOADS_DIR: str = os.getenv("UPLOADS_DIR", "uploads")

    # Configurações de SMTP específicas para Assistência Técnica
    ASSISTENCIA_SMTP_HOST = os.getenv("ASSISTENCIA_SMTP_HOST")
    ASSISTENCIA_SMTP_PORT = int(os.getenv("ASSISTENCIA_SMTP_PORT") or 0) or None
    ASSISTENCIA_SMTP_USERNAME = os.getenv("ASSISTENCIA_SMTP_USERNAME")
    ASSISTENCIA_SMTP_PASSWORD = os.getenv("ASSISTENCIA_SMTP_PASSWORD")
    ASSISTENCIA_SMTP_USE_TLS = _env_bool("ASSISTENCIA_SMTP_USE_TLS", False)
    ASSISTENCIA_SMTP_USE_SSL = _env_bool("ASSISTENCIA_SMTP_USE_SSL", False)
    ASSISTENCIA_FROM_EMAIL = os.getenv("ASSISTENCIA_FROM_EMAIL")
    ASSISTENCIA_FROM_NAME = os.getenv("ASSISTENCIA_FROM_NAME")
    ASSISTENCIA_EMAIL_TO = os.getenv("ASSISTENCIA_EMAIL_TO")
    ASSISTENCIA_REPLY_TO = os.getenv("ASSISTENCIA_REPLY_TO")

