from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int
    channel_id: int
    database_path: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    admin_id = os.getenv("ADMIN_ID", "").strip()
    raw_channel_id = os.getenv("CHANNEL_ID", "").strip()
    database_path = os.getenv("DATABASE_PATH", "data/bot.sqlite3").strip()

    if not token or not admin_id or not raw_channel_id:
        raise RuntimeError("Заполните BOT_TOKEN, ADMIN_ID и CHANNEL_ID в файле .env")

    if not raw_channel_id.lstrip("-").isdigit():
        raise RuntimeError("CHANNEL_ID должен быть числовым ID канала вида -100...")
    channel_id = int(raw_channel_id)

    return Config(
        bot_token=token,
        admin_id=int(admin_id),
        channel_id=channel_id,
        database_path=database_path,
    )
