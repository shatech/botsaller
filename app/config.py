import os
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str = "7777777777:CHANGE_ME_BOT_TOKEN"
    BOT_WEBHOOK_URL: str = ""
    MINIAPP_URL: str = ""

    # Database: MySQL or SQLite
    DATABASE_URL: str = "sqlite+aiosqlite:///./botsaller.db"

    # Security & Admin Web Panel
    SECRET_KEY: str = "super-secret-key-change-this-in-production-simorix-2026"
    ADMIN_DEFAULT_USERNAME: str = "admin"
    ADMIN_DEFAULT_PASSWORD: str = "admin123"
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8000

    # Crypto Settings
    COLD_WALLET_TRC20: str = "TXYZ1234567890ExampleTRC20Address"
    COLD_WALLET_BEP20: str = "0x1234567890abcdef1234567890abcdef12345678"
    TRONSCAN_API_KEY: str = ""
    BSCSCAN_API_KEY: str = ""
    CRYPTO_CHECK_INTERVAL_SECONDS: int = 30

    # Storage
    UPLOAD_DIR: str = "./uploads"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def resolve_paths(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Resolve UPLOAD_DIR to absolute path
        if not os.path.isabs(self.UPLOAD_DIR):
            self.UPLOAD_DIR = os.path.abspath(os.path.join(base_dir, self.UPLOAD_DIR))

        # Resolve relative SQLite paths to absolute to prevent directory mismatch
        sqlite_prefix = "sqlite+aiosqlite:///"
        if self.DATABASE_URL.startswith(sqlite_prefix):
            db_path = self.DATABASE_URL[len(sqlite_prefix):]
            if db_path.startswith("./"):
                db_path = db_path[2:]
            # If not an absolute Unix path (starts with /) and not a Windows drive path (X:)
            is_win_abs = len(db_path) > 1 and db_path[1] == ":"
            if not db_path.startswith("/") and not is_win_abs:
                abs_db_path = os.path.abspath(os.path.join(base_dir, db_path)).replace("\\", "/")
                if abs_db_path.startswith("/"):
                    self.DATABASE_URL = f"sqlite+aiosqlite://{abs_db_path}"
                else:
                    self.DATABASE_URL = f"{sqlite_prefix}{abs_db_path}"
        return self


settings = Settings()
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


