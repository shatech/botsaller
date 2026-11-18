from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import User, Setting
from app.bot.keyboards import (
    main_menu_keyboard,
    login_inline_keyboard,
    miniapp_inline_keyboard,
    language_selection_keyboard
)
from app.services.i18n_service import i18n, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE

router = Router(name="start_router")


async def get_or_create_user(telegram_user, session: AsyncSession) -> User:
    query = select(User).where(User.telegram_id == telegram_user.id)
    result = await session.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            language_code="en",
            is_language_selected=True
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    else:
        # Update username/first_name if changed in Telegram
        updated = False
        if user.language_code != "en":
            user.language_code = "en"
            user.is_language_selected = True
            updated = True
        if user.username != telegram_user.username:
            user.username = telegram_user.username
            updated = True
        if user.first_name != telegram_user.first_name:
            user.first_name = telegram_user.first_name
            updated = True
        if updated:
            await session.commit()

    return user


async def send_welcome_and_menu(message: Message, user: User):
    """Sends localized welcome message with Mini App login button and main menu."""
    welcome_text = i18n.get(
        "welcome",
        lang="en",
        first_name=user.first_name or "User",
        api_token=user.api_token
    )

    caption = (
        f"{welcome_text}\n\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"{i18n.get('miniapp_caption', lang='en', telegram_id=user.telegram_id, balance=float(user.wallet_balance))}"
    )

    # 1. Send inline button for Mini App
    await message.answer(
        text=caption,
        reply_markup=login_inline_keyboard(lang="en"),
        parse_mode="Markdown"
    )

    # 2. Display the Reply Menu keyboard in English
    await message.answer(
        text="▫️ " + i18n.get("select_option", lang="en", default="Main Menu:"),
        reply_markup=main_menu_keyboard(lang="en")
    )


@router.message(CommandStart())
async def handle_start(message: Message):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(message.from_user, session)
        await send_welcome_and_menu(message, user)


@router.message(Command("language", "lang"))
async def handle_language_setting(message: Message):
    await message.answer("🌐 The system interface is configured in **English** 🇬🇧.", parse_mode="Markdown")


@router.message(F.text.in_(i18n.get_all_button_texts("btn_my_token") + ["🔑 My Token", "🔑 My Account Token", "My Token", "Token"]))
async def handle_my_token(message: Message):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(message.from_user, session)
        msg = i18n.get(
            "token_title",
            lang="en",
            telegram_id=user.telegram_id,
            api_token=user.api_token
        )
        await message.answer(msg, parse_mode="Markdown")


@router.message(F.text.in_(i18n.get_all_button_texts("btn_support") + ["🆘 Support", "Support", "Help"]))
async def handle_support(message: Message):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(message.from_user, session)
        setting_res = await session.execute(
            select(Setting).where(Setting.setting_key == "support_username")
        )
        setting = setting_res.scalar_one_or_none()
        support_id = setting.setting_value if setting and setting.setting_value else "@Support"

        msg = i18n.get("support_title", lang="en", support_id=support_id)
        await message.answer(msg, parse_mode="Markdown")


@router.message(Command("login", "app", "miniapp"))
@router.message(F.text.in_(
    i18n.get_all_button_texts("btn_login_webapp") +
    [f"🚀 {t}" for t in i18n.get_all_button_texts("btn_login_webapp")] +
    ["🚀 Open Mini App", "Login", "Mini App", "App"]
))
async def handle_open_app_command(message: Message):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(message.from_user, session)
        msg = (
            f"🔐 **{i18n.get('btn_login_webapp', 'en')}**\n\n"
            f"👤 {i18n.get('user_id_info', 'en', telegram_id=user.telegram_id, default=f'ID: {user.telegram_id}')}\n"
            f"💰 {i18n.get('wallet_balance_info', 'en', balance=float(user.wallet_balance), default=f'Balance: {user.wallet_balance:,.2f} USDT')}\n\n"
            f"{i18n.get('miniapp_cta', 'en', default='Click the button below to open your exclusive Mini App:')}"
        )
        await message.answer(msg, reply_markup=login_inline_keyboard(lang="en"), parse_mode="Markdown")
