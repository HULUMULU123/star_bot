import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    api_token: str = os.getenv("API_TOKEN", "")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    db_path: str = os.getenv("DB_PATH", "stars.db")
    test_mode: bool = os.getenv("TEST_MODE", "0") == "1"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    def validate(self) -> None:
        if not self.bot_token:
            raise RuntimeError("BOT_TOKEN is required")
        if not self.api_token:
            raise RuntimeError("API_TOKEN is required")
