import os
import asyncio
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func

from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.models import StaffUser, Setting, Translation, Category, CategoryFormField, PortfolioItem
from app.services.auth_service import AuthService, NotAuthenticatedException
from app.services.crypto_verifier import CryptoVerifierService
from app.services.i18n_service import i18n, DEFAULT_FA_STRINGS
from app.bot.dispatcher import get_bot_instance, get_dispatcher_instance
from app.web.routers import auth, admin, support, webapp


async def seed_initial_data():
    try:
        async with AsyncSessionLocal() as session:
            # 1. Seed Super Admin
            admin_res = await session.execute(
                select(StaffUser).where(StaffUser.username == settings.ADMIN_DEFAULT_USERNAME)
            )
            if not admin_res.scalar_one_or_none():
                pw_hash = AuthService.get_password_hash(settings.ADMIN_DEFAULT_PASSWORD)
                super_admin = StaffUser(
                    username=settings.ADMIN_DEFAULT_USERNAME,
                    password_hash=pw_hash,
                    role="super_admin",
                    is_active=True
                )
                session.add(super_admin)
                print(f"[Seed] Created default super_admin: {settings.ADMIN_DEFAULT_USERNAME}")

            # 2. Seed Default Settings
            default_settings = {
                "cold_wallet_trc20": settings.COLD_WALLET_TRC20,
                "cold_wallet_bep20": settings.COLD_WALLET_BEP20,
                "trongrid_api_key": settings.TRONSCAN_API_KEY,
                "bscscan_api_key": settings.BSCSCAN_API_KEY,
                "operator_chat_id": "",
                "support_username": "@SimorixSupport",
                "min_deposit": "1.0"
            }
            for k, v in default_settings.items():
                existing = (await session.execute(select(Setting).where(Setting.setting_key == k))).scalar_one_or_none()
                if not existing:
                    session.add(Setting(setting_key=k, setting_value=str(v)))

            # 3. Seed Default Translations
            for k, v in DEFAULT_FA_STRINGS.items():
                existing_tr = (await session.execute(
                    select(Translation).where(Translation.lang_code == "en", Translation.trans_key == k)
                )).scalar_one_or_none()
                if not existing_tr:
                    session.add(Translation(lang_code="en", trans_key=k, trans_value=v))

            await session.commit()
            await i18n.load_from_db(session)

        # 4. Synchronize the 5 Products, Form Fields, and Samples
        from seed_kyc import seed_kyc_data
        await seed_kyc_data()
    except Exception as e:
        print(f"[Seed Error] seed_initial_data encountered an issue: {e}")
        traceback.print_exc()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    print("[Lifespan] Initializing database...")
    try:
        await init_db()
    except Exception as e:
        print(f"[Lifespan Error] init_db failed: {e}")
        traceback.print_exc()

    try:
        await seed_initial_data()
    except Exception as e:
        print(f"[Lifespan Error] seed_initial_data failed: {e}")
        traceback.print_exc()

    bot = get_bot_instance()
    dp = get_dispatcher_instance()

    # Background tasks
    crypto_task = asyncio.create_task(CryptoVerifierService.run_verifier_loop(bot))
    polling_task = None

    try:
        if settings.BOT_WEBHOOK_URL:
            webhook_endpoint = f"{settings.BOT_WEBHOOK_URL.rstrip('/')}/webhook"
            print(f"[Lifespan] Setting bot webhook: {webhook_endpoint}")
            await bot.set_webhook(url=webhook_endpoint)
        else:
            print("[Lifespan] Starting bot in Long Polling mode...")
            try:
                await bot.delete_webhook(drop_pending_updates=True)
            except Exception as e:
                print(f"[Lifespan Warning] Could not delete webhook: {e}")

            async def run_polling():
                try:
                    print("[Polling] Dispatcher polling loop starting...")
                    await dp.start_polling(bot)
                except Exception as poll_err:
                    print(f"[Polling Error] Telegram polling exception: {poll_err}")
                    traceback.print_exc()

            polling_task = asyncio.create_task(run_polling())
    except Exception as e:
        print(f"[Lifespan Warning] Could not connect to Telegram Bot API: {e}")
        print("[Lifespan Warning] Web panel will continue to function. Please verify BOT_TOKEN or network.")

    yield

    # --- Shutdown ---
    print("[Lifespan] Shutting down...")
    if polling_task:
        polling_task.cancel()
    crypto_task.cancel()
    try:
        await bot.session.close()
    except Exception:
        pass


app = FastAPI(
    title="Botsaller - Persian Telegram Commerce & Custom Service Platform",
    version="1.0.0",
    lifespan=lifespan
)

# Exception handlers
@app.exception_handler(NotAuthenticatedException)
async def not_authenticated_handler(request: Request, exc: NotAuthenticatedException):
    return RedirectResponse(url="/login", status_code=302)


# Static & Uploads Mount
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# Include Routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(support.router)
app.include_router(webapp.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/admin/dashboard")


@app.post("/webhook")
async def telegram_webhook(request: Request):
    bot = get_bot_instance()
    dp = get_dispatcher_instance()
    data = await request.json()
    from aiogram.types import Update
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.WEB_HOST, port=settings.WEB_PORT, reload=True)
