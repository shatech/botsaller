import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import Category, User, PortfolioItem
from app.services.category_service import CategoryService
from app.services.i18n_service import i18n
from app.bot.keyboards import categories_keyboard, leaf_service_keyboard, portfolio_nav_keyboard
from app.config import settings

router = Router(name="catalog_router")


def _get_portfolio_media(image_path: str):
    if not image_path:
        return None
    if image_path.startswith("http://") or image_path.startswith("https://"):
        return image_path
    rel_path = image_path.replace("/uploads/", "", 1) if image_path.startswith("/uploads/") else image_path
    full_disk_path = os.path.join(settings.UPLOAD_DIR, rel_path)
    if os.path.exists(full_disk_path):
        return FSInputFile(full_disk_path)
    return None


@router.message(Command("catalog", "services"))
@router.message(F.text.in_(
    i18n.get_all_button_texts("btn_services") +
    ["🛍 Services & Products", "🛍 Services & Catalog", "🛍 خدمات و ثبت سفارش", "Services", "Catalog"]
))
async def show_root_catalog(message: Message):
    async with AsyncSessionLocal() as session:
        roots = await CategoryService.get_root_categories(session, only_active=True)
        if not roots:
            await message.answer(
                "⚠️ Currently no services or products are available.",
                parse_mode="Markdown"
            )
            return

        text = "🛍 **Services & Products**\n\nPlease select a document category below:"
        await message.answer(
            text=text,
            reply_markup=categories_keyboard(roots, parent_category=None, lang="en"),
            parse_mode="Markdown"
        )


@router.callback_query(F.data == "cat:root")
async def handle_back_to_root(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        roots = await CategoryService.get_root_categories(session, only_active=True)
        text = "🛍 **Services & Products**\n\nPlease select a document category below:"
        kb = categories_keyboard(roots, parent_category=None, lang="en")
        try:
            await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text=text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def handle_category_click(callback: CallbackQuery):
    cat_id_str = callback.data.split(":")[1]
    if not cat_id_str.isdigit():
        await callback.answer()
        return

    cat_id = int(cat_id_str)
    async with AsyncSessionLocal() as session:
        category = await CategoryService.get_category_by_id(session, cat_id)
        if not category or not category.is_active:
            await callback.answer("This service is currently unavailable.", show_alert=True)
            return

        if not category.is_leaf:
            # Subcategories view (e.g. Complete Pack Digital / Physical)
            subcategories = await CategoryService.get_subcategories(session, cat_id, only_active=True)
            if not subcategories:
                await callback.answer("No options available in this section.", show_alert=True)
                return

            text = f"📁 **{category.get_title('en')}**\n"
            if category.get_description("en"):
                text += f"_{category.get_description('en')}_\n\n"
            else:
                text += "\n"
            text += "Please choose an edition/version below:"

            kb = categories_keyboard(subcategories, parent_category=category, lang="en")
            try:
                await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="Markdown")
            except Exception:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.message.answer(text=text, reply_markup=kb, parse_mode="Markdown")
        else:
            # Leaf node: final service/product view with sample work photo displayed!
            title = category.get_title("en")
            desc = category.get_description("en") or ""
            price = float(category.price)

            # Query sample portfolio items for this category
            port_q = (
                select(PortfolioItem)
                .where(PortfolioItem.category_id == category.id, PortfolioItem.is_active == True)
                .order_by(PortfolioItem.sort_order, PortfolioItem.id.desc())
            )
            port_items = list((await session.execute(port_q)).scalars().all())
            sample = port_items[0] if port_items else None

            sample_note = "\n\n🎨 **Sample Work:** Illustrated in the photo above" if sample else ""

            text = (
                f"✨ **{title}**\n\n"
                f"📝 **Description & Specs:**\n{desc}\n\n"
                f"💰 **Price:** `{price:,.2f}` USDT{sample_note}"
            )

            kb = leaf_service_keyboard(category.id, category.parent_id, lang="en")
            photo_media = _get_portfolio_media(sample.image_path) if sample else None

            if photo_media:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.message.answer_photo(
                    photo=photo_media,
                    caption=text,
                    reply_markup=kb,
                    parse_mode="Markdown"
                )
            else:
                try:
                    await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="Markdown")
                except Exception:
                    try:
                        await callback.message.delete()
                    except Exception:
                        pass
                    await callback.message.answer(text=text, reply_markup=kb, parse_mode="Markdown")

    await callback.answer()


@router.callback_query(F.data.startswith("samples_cat:"))
async def handle_category_samples_carousel(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        q = (
            select(PortfolioItem)
            .where(PortfolioItem.category_id == cat_id, PortfolioItem.is_active == True)
            .order_by(PortfolioItem.sort_order, PortfolioItem.id.desc())
            .options(selectinload(PortfolioItem.category))
        )
        items = list((await session.execute(q)).scalars().all())
        if not items:
            await callback.answer("No additional sample works found for this service.", show_alert=True)
            return

        total = len(items)
        first_item = items[0]
        cat_title = first_item.category.get_title("en") if first_item.category else "Service"
        caption = (
            f"🎨 **{first_item.title}**\n"
            f"📁 **Service:** {cat_title}\n"
            f"📝 {first_item.description}\n\n"
            f"🔢 1 / {total}"
        )
        photo_media = _get_portfolio_media(first_item.image_path)
        kb = portfolio_nav_keyboard(0, total, first_item.category_id, lang="en")

        try:
            await callback.message.delete()
        except Exception:
            pass

        if photo_media:
            await callback.message.answer_photo(photo=photo_media, caption=caption, reply_markup=kb, parse_mode="Markdown")
        else:
            await callback.message.answer(caption, reply_markup=kb, parse_mode="Markdown")

    await callback.answer()


@router.callback_query(F.data == "close_catalog")
async def handle_close_catalog(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()
