from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.bot.handlers import start, catalog, order_wizard, wallet, portfolio

bot = Bot(token=settings.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Register routers
dp.include_router(start.router)
dp.include_router(catalog.router)
dp.include_router(portfolio.router)
dp.include_router(order_wizard.router)
dp.include_router(wallet.router)


def get_bot_instance() -> Bot:
    return bot


def get_dispatcher_instance() -> Dispatcher:
    return dp

