import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from api.routes import create_api_app
from bot.handlers import setup_handlers
from config.logger import log_extra, setup_logging
from config.settings import Settings
from db.database import Database


async def run_bot(bot: Bot, dp: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    logging.getLogger(__name__).info("bot started", extra=log_extra(mode="polling"))
    await dp.start_polling(bot)


async def main() -> None:
    settings = Settings()
    settings.validate()
    setup_logging(settings.log_level)

    db = Database(settings.db_path)
    await db.init()
    logging.getLogger(__name__).info("db ready", extra=log_extra(path=str(db.path)))

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    setup_handlers(dp, db, settings)

    api_app = create_api_app(settings, db, bot)
    api_config = uvicorn.Config(api_app, host=settings.host, port=settings.port, log_level="info")
    api_server = uvicorn.Server(api_config)

    bot_task = asyncio.create_task(run_bot(bot, dp))
    api_task = asyncio.create_task(api_server.serve())

    try:
        await asyncio.gather(bot_task, api_task)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(main())
