import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from apps.bot.handlers import commands, match_callbacks, onboarding
from apps.bot.handlers import settings as settings_handler
from apps.shared.config import settings

log = logging.getLogger(__name__)

bot = Bot(
    token=settings.telegram_bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
storage = RedisStorage.from_url(settings.redis_url)
dp = Dispatcher(storage=storage)

dp.include_router(onboarding.router)
dp.include_router(settings_handler.router)
dp.include_router(commands.router)
dp.include_router(match_callbacks.router)


async def on_startup(bot: Bot) -> None:
    secret = settings.telegram_webhook_secret or None
    await bot.set_webhook(
        url=settings.telegram_webhook_url,
        secret_token=secret,
        drop_pending_updates=True,
    )
    log.info("Webhook registered: %s", settings.telegram_webhook_url)


async def on_shutdown(bot: Bot) -> None:
    await bot.delete_webhook()
    log.info("Webhook removed")


dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    secret = settings.telegram_webhook_secret or None
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=secret,
    ).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
