import os
import re
import uuid
from typing import Dict, Any, List
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Category, CategoryFormField, User
from app.services.category_service import CategoryService
from app.services.order_service import OrderService
from app.services.i18n_service import i18n
from app.bot.states import OrderWizardState
from app.bot.keyboards import (
    wizard_field_keyboard,
    order_confirmation_keyboard,
    main_menu_keyboard
)
from app.config import settings

router = Router(name="order_wizard_router")


async def ask_current_field(message_or_callback, state: FSMContext, bot: Bot):
    data = await state.get_data()
    fields: List[Dict[str, Any]] = data.get("fields", [])
    idx: int = data.get("current_index", 0)
    lang: str = data.get("lang", "en")

    if idx >= len(fields):
        # All questions answered -> Go to confirmation
        await show_order_summary(message_or_callback, state)
        return

    field = fields[idx]
    label = field.get("label", "")
    ftype = field.get("field_type", "text")
    is_req = field.get("is_required", True)
    options = field.get("options") or []

    prompt = i18n.get("wizard_step_header", lang=lang, current=idx + 1, total=len(fields), label=label)

    if ftype == "photo":
        prompt += i18n.get("wizard_prompt_photo", lang=lang)
    elif ftype == "document":
        prompt += i18n.get("wizard_prompt_document", lang=lang)
    elif ftype == "date":
        prompt += i18n.get("wizard_prompt_date", lang=lang)
    elif ftype == "number":
        prompt += i18n.get("wizard_prompt_number", lang=lang)
    elif ftype == "select":
        prompt += i18n.get("wizard_prompt_select", lang=lang)

    if not is_req:
        prompt += i18n.get("wizard_optional_note", lang=lang)

    kb = wizard_field_keyboard(is_required=is_req, options=options if ftype == "select" else None, lang=lang)

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.answer(prompt, reply_markup=kb, parse_mode="Markdown")
    else:
        await message_or_callback.answer(prompt, reply_markup=kb, parse_mode="Markdown")


async def show_order_summary(message_or_callback, state: FSMContext):
    data = await state.get_data()
    cat_id = data["category_id"]
    answers = data.get("answers", {})

    async with AsyncSessionLocal() as session:
        cat = await CategoryService.get_category_by_id(session, cat_id)
        # Fetch user
        tg_id = message_or_callback.from_user.id
        u_res = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = u_res.scalar_one()
        lang = user.language_code or "en"

        price = float(cat.price)
        balance = float(user.wallet_balance)
        can_afford = balance >= price

        summary_lines = [
            f"🧾 **{i18n.get('order_summary_title', lang=lang)}**\n",
            f"📁 **{i18n.get('order_summary_service', lang=lang)}:** {cat.get_title(lang)}",
            f"💰 **{i18n.get('order_summary_price', lang=lang)}:** `{price:,.2f}` USDT",
            f"💼 **{i18n.get('order_summary_balance', lang=lang)}:** `{balance:,.2f}` USDT\n",
            "━━━━━━━━━━━━━━━",
            f"📝 **{i18n.get('order_summary_details', lang=lang)}:**"
        ]

        for key, ans in answers.items():
            lbl = ans.get("label", key)
            val = ans.get("value", "-")
            if ans.get("type") in ("photo", "document"):
                summary_lines.append(f"▫️ **{lbl}:** [Attachment uploaded]")
            else:
                summary_lines.append(f"▫️ **{lbl}:** {val}")

        summary_lines.append("━━━━━━━━━━━━━━━")
        if can_afford:
            summary_lines.append(i18n.get("order_summary_sufficient", lang=lang))
        else:
            diff = price - balance
            summary_lines.append(i18n.get("order_summary_insufficient", lang=lang, diff=diff))

        text = "\n".join(summary_lines)
        kb = order_confirmation_keyboard(can_afford=can_afford, lang=lang)

        await state.set_state(OrderWizardState.confirming_order)

        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
        else:
            await message_or_callback.answer(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("start_order:"))
async def handle_start_order(callback: CallbackQuery, state: FSMContext, bot: Bot):
    cat_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        u_res = await session.execute(select(User.language_code).where(User.telegram_id == callback.from_user.id))
        lang = u_res.scalar_one_or_none() or "en"

        cat = await CategoryService.get_category_by_id(session, cat_id)
        if not cat or not cat.is_leaf:
            await callback.answer("This service is not available.", show_alert=True)
            return

        form_fields = await CategoryService.get_form_fields(session, cat_id)

        # Store serializable field data in state
        field_dicts = []
        for f in form_fields:
            field_dicts.append({
                "id": f.id,
                "field_key": f.field_key,
                "label": f.get_label(lang),
                "field_type": f.field_type,
                "options": f.options,
                "validation_regex": f.validation_regex,
                "is_required": f.is_required,
                "sort_order": f.sort_order
            })

        await state.update_data(
            category_id=cat_id,
            fields=field_dicts,
            current_index=0,
            answers={},
            lang=lang
        )
        await state.set_state(OrderWizardState.waiting_for_field)

        await callback.message.answer(
            f"🚀 **{cat.get_title(lang)}**\n"
            "Please provide the required details below:",
            parse_mode="Markdown"
        )
        await ask_current_field(callback, state, bot)

    await callback.answer()


@router.callback_query(F.data == "skip_field", OrderWizardState.waiting_for_field)
async def handle_skip_field(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    fields = data.get("fields", [])
    idx = data.get("current_index", 0)
    lang = data.get("lang", "en")

    if idx < len(fields):
        field = fields[idx]
        if field.get("is_required", True):
            await callback.answer(i18n.get("wizard_step_required", lang=lang), show_alert=True)
            return

        answers = data.get("answers", {})
        answers[field["field_key"]] = {
            "label": field["label"],
            "type": field["field_type"],
            "value": i18n.get("wizard_skipped_val", lang=lang)
        }
        await state.update_data(current_index=idx + 1, answers=answers)
        await ask_current_field(callback, state, bot)

    await callback.answer()


@router.callback_query(F.data.startswith("opt:"), OrderWizardState.waiting_for_field)
async def handle_option_selected(callback: CallbackQuery, state: FSMContext, bot: Bot):
    selected_value = callback.data.split("opt:")[1]
    data = await state.get_data()
    fields = data.get("fields", [])
    idx = data.get("current_index", 0)

    if idx < len(fields):
        field = fields[idx]
        answers = data.get("answers", {})
        answers[field["field_key"]] = {
            "label": field["label"],
            "type": field["field_type"],
            "value": selected_value
        }
        await state.update_data(current_index=idx + 1, answers=answers)
        await ask_current_field(callback, state, bot)

    await callback.answer()


@router.message(OrderWizardState.waiting_for_field)
async def handle_field_input(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    fields = data.get("fields", [])
    idx = data.get("current_index", 0)
    lang = data.get("lang", "en")

    if idx >= len(fields):
        await show_order_summary(message, state)
        return

    field = fields[idx]
    ftype = field.get("field_type", "text")
    regex = field.get("validation_regex")

    value = None
    local_path = None
    file_id = None

    orders_dir = os.path.join(settings.UPLOAD_DIR, "orders")
    os.makedirs(orders_dir, exist_ok=True)

    web_url = None

    if ftype == "photo":
        if not message.photo:
            await message.answer(i18n.get("wizard_invalid_photo", lang=lang))
            return
        photo = message.photo[-1]
        file_id = photo.file_id
        file_info = await bot.get_file(file_id)
        local_name = f"{uuid.uuid4().hex[:10]}_{os.path.basename(file_info.file_path or 'image.jpg')}"
        local_path = os.path.join(orders_dir, local_name)
        await bot.download_file(file_info.file_path, destination=local_path)
        value = f"Photo ({local_name})"
        web_url = f"/uploads/orders/{local_name}"

    elif ftype == "document":
        if not message.document:
            await message.answer(i18n.get("wizard_invalid_doc", lang=lang))
            return
        doc = message.document
        file_id = doc.file_id
        file_info = await bot.get_file(file_id)
        local_name = f"{uuid.uuid4().hex[:10]}_{doc.file_name or 'document'}"
        local_path = os.path.join(orders_dir, local_name)
        await bot.download_file(file_info.file_path, destination=local_path)
        value = f"Document: {doc.file_name}"
        web_url = f"/uploads/orders/{local_name}"

    elif ftype == "number":
        text_val = message.text.strip() if message.text else ""
        try:
            float(text_val)
            value = text_val
        except ValueError:
            await message.answer(i18n.get("wizard_invalid_num", lang=lang))
            return

    else:
        # text or date
        text_val = message.text.strip() if message.text else ""
        if not text_val:
            await message.answer(i18n.get("wizard_invalid_text", lang=lang))
            return

        if regex:
            try:
                if not re.match(regex, text_val):
                    await message.answer(i18n.get("wizard_invalid_regex", lang=lang))
                    return
            except Exception:
                pass

        value = text_val

    answers = data.get("answers", {})
    answers[field["field_key"]] = {
        "label": field["label"],
        "type": ftype,
        "value": value,
        "local_path": local_path,
        "web_url": web_url,
        "file_id": file_id
    }

    await state.update_data(current_index=idx + 1, answers=answers)
    await ask_current_field(message, state, bot)


@router.callback_query(F.data == "confirm_pay_wallet", OrderWizardState.confirming_order)
async def handle_confirm_payment(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    cat_id = data["category_id"]
    answers = data.get("answers", {})
    lang = data.get("lang", "en")

    async with AsyncSessionLocal() as session:
        u_res = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = u_res.scalar_one()

        try:
            order = await OrderService.create_paid_order(
                db=session,
                user_id=user.id,
                category_id=cat_id,
                form_data=answers,
                bot=bot
            )

            await state.clear()
            msg = i18n.get("order_placed_success", lang=lang, order_code=order.order_code)
            await callback.message.edit_text(msg, parse_mode="Markdown")

        except ValueError as e:
            await callback.answer(str(e), show_alert=True)

    await callback.answer()


@router.callback_query(F.data == "cancel_wizard")
async def handle_cancel_wizard(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    await state.clear()
    await callback.message.edit_text(i18n.get("order_cancelled", lang=lang))
    await callback.message.answer(
        "▫️ " + i18n.get("select_option", lang=lang, default="Navigation Menu:"),
        reply_markup=main_menu_keyboard(lang=lang)
    )
    await callback.answer()

