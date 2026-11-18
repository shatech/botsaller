import os
from typing import Optional
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InputMediaPhoto
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import User, PortfolioItem, Category
from app.services.i18n_service import i18n
from app.bot.keyboards import portfolio_nav_keyboard
from app.config import settings

router = Router(name="portfolio_router")


def _get_item_media_and_caption(item: PortfolioItem, current_idx: int, total: int, lang: str):
    """Formats caption and determines media for a portfolio item."""
    cat_title = item.category.get_title(lang) if item.category else None
    
    caption_lines = [
        f"🎨 **{item.title}**\n"
    ]
    if cat_title:
        rel_svc_lbl = i18n.get("related_service", lang=lang, default="Related Service:")
        caption_lines.append(f"📁 **{rel_svc_lbl}** {cat_title}")
    if item.description:
        caption_lines.append(f"📝 {item.description}\n")

    caption_lines.append(f"🔢 {current_idx + 1} / {total}")
    caption = "\n".join(caption_lines)

    # Resolve local disk file path
    photo_media = None
    if item.image_path:
        if item.image_path.startswith("http://") or item.image_path.startswith("https://"):
            photo_media = item.image_path
        else:
            rel_path = item.image_path.replace("/uploads/", "", 1) if item.image_path.startswith("/uploads/") else item.image_path
            full_disk_path = os.path.join(settings.UPLOAD_DIR, rel_path)
            if os.path.exists(full_disk_path):
                photo_media = FSInputFile(full_disk_path)

    return photo_media, caption


@router.message(Command("portfolio", "samples"))
@router.message(F.text.in_(
    i18n.get_all_button_texts("btn_portfolio") +
    ["🎨 Portfolio & Samples", "Portfolio", "Samples", "🎨 Samples"]
))
async def show_portfolio_gallery(message: Message, state: FSMContext):
    """Sends the first portfolio sample with interactive navigation buttons."""
    await state.clear()
    
    async with AsyncSessionLocal() as session:
        # Get user's preferred language
        u_res = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = u_res.scalar_one_or_none()
        lang = user.language_code if user and user.language_code else "en"

        # Fetch active portfolio items
        q = (
            select(PortfolioItem)
            .where(PortfolioItem.is_active == True)
            .order_by(PortfolioItem.sort_order, PortfolioItem.id.desc())
            .options(selectinload(PortfolioItem.category))
        )
        items = (await session.execute(q)).scalars().all()

        if not items:
            await message.answer(i18n.get("portfolio_empty", lang=lang))
            return

        total = len(items)
        first_item = items[0]
        photo_media, caption = _get_item_media_and_caption(first_item, 0, total, lang)
        kb = portfolio_nav_keyboard(0, total, first_item.category_id, lang=lang)

        if photo_media:
            await message.answer_photo(
                photo=photo_media,
                caption=caption,
                reply_markup=kb,
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                caption,
                reply_markup=kb,
                parse_mode="Markdown"
            )


@router.callback_query(F.data.startswith("port:"))
async def handle_portfolio_navigation(callback: CallbackQuery):
    """Handles carousel navigation (next, previous) between portfolio items."""
    param = callback.data.split(":")[1]
    if param == "noop":
        await callback.answer()
        return

    try:
        target_idx = int(param)
    except ValueError:
        await callback.answer()
        return

    async with AsyncSessionLocal() as session:
        u_res = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = u_res.scalar_one_or_none()
        lang = user.language_code if user and user.language_code else "en"

        q = (
            select(PortfolioItem)
            .where(PortfolioItem.is_active == True)
            .order_by(PortfolioItem.sort_order, PortfolioItem.id.desc())
            .options(selectinload(PortfolioItem.category))
        )
        items = (await session.execute(q)).scalars().all()
        total = len(items)

        if not items or target_idx < 0 or target_idx >= total:
            await callback.answer()
            return

        target_item = items[target_idx]
        photo_media, caption = _get_item_media_and_caption(target_item, target_idx, total, lang)
        kb = portfolio_nav_keyboard(target_idx, total, target_item.category_id, lang=lang)

        try:
            if photo_media:
                media_obj = InputMediaPhoto(media=photo_media, caption=caption, parse_mode="Markdown")
                await callback.message.edit_media(media=media_obj, reply_markup=kb)
            else:
                await callback.message.edit_caption(caption=caption, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            # If edit media failed (e.g., photo file format or unchanged), edit caption or answer
            try:
                await callback.message.edit_caption(caption=caption, reply_markup=kb, parse_mode="Markdown")
            except Exception:
                pass

        await callback.answer()
