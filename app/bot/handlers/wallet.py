import os
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database import AsyncSessionLocal
from app.models import User, WalletTransaction, Order, Setting
from app.services.crypto_verifier import CryptoVerifierService
from app.services.order_service import OrderService
from app.services.i18n_service import i18n
from app.bot.states import WalletDepositState
from app.bot.keyboards import wallet_networks_keyboard, main_menu_keyboard
from app.config import settings

router = Router(name="wallet_router")


@router.message(Command("wallet", "balance"))
@router.message(F.text.in_(
    i18n.get_all_button_texts("btn_wallet") +
    ["💳 Wallet & Top-up", "💳 Wallet", "Wallet", "Balance"]
))
async def show_wallet_menu(message: Message, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        u_res = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = u_res.scalar_one_or_none()
        if not user:
            return

        lang = user.language_code or "en"
        text = i18n.get("wallet_title", lang=lang, balance=float(user.wallet_balance))
        await message.answer(text, reply_markup=wallet_networks_keyboard(lang=lang), parse_mode="Markdown")


@router.callback_query(F.data == "topup_for_order")
async def handle_topup_for_order(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        u_res = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = u_res.scalar_one_or_none()
        lang = user.language_code if user else "en"

    text = i18n.get("topup_wallet_title", lang=lang)
    await callback.message.answer(text, reply_markup=wallet_networks_keyboard(lang=lang), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("net:"))
async def handle_network_chosen(callback: CallbackQuery, state: FSMContext):
    network = callback.data.split(":")[1]  # TRC20 or BEP20

    async with AsyncSessionLocal() as session:
        u_res = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = u_res.scalar_one_or_none()
        lang = user.language_code if user else "en"

        setting_key = "cold_wallet_trc20" if network == "TRC20" else "cold_wallet_bep20"
        default_val = settings.COLD_WALLET_TRC20 if network == "TRC20" else settings.COLD_WALLET_BEP20
        cold_wallet = await CryptoVerifierService.get_setting(session, setting_key, default_val)

        qr_path = CryptoVerifierService.generate_qr_code(cold_wallet)
        await state.update_data(network=network, cold_wallet=cold_wallet, lang=lang)
        await state.set_state(WalletDepositState.waiting_for_txid)

        caption = i18n.get("deposit_instructions", lang=lang, network=network, cold_wallet=cold_wallet)

        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=i18n.get("btn_cancel_back", lang=lang, default="❌ Cancel"), callback_data="cancel_wallet")
        ]])

        if os.path.exists(qr_path):
            photo_file = FSInputFile(qr_path)
            await callback.message.answer_photo(
                photo=photo_file,
                caption=caption,
                reply_markup=cancel_kb,
                parse_mode="Markdown"
            )
        else:
            await callback.message.answer(caption, reply_markup=cancel_kb, parse_mode="Markdown")

    await callback.answer()


@router.message(WalletDepositState.waiting_for_txid)
async def handle_txid_input(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    lang = data.get("lang", "en")
    network = data.get("network", "TRC20")

    txid = message.text.strip() if message.text else ""
    if not txid or len(txid) < 8:
        await message.answer(i18n.get("txid_prompt_invalid", lang=lang))
        return

    async with AsyncSessionLocal() as session:
        u_res = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = u_res.scalar_one()

        # Check anti-replay
        dup_check = await session.execute(
            select(WalletTransaction).where(WalletTransaction.tx_hash == txid)
        )
        if dup_check.scalar_one_or_none():
            await message.answer(i18n.get("txid_duplicate_error", lang=lang))
            await state.clear()
            return

        tx = WalletTransaction(
            user_id=user.id,
            type="deposit",
            amount=0.0,
            tx_hash=txid,
            network=network,
            status="pending"
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)

        await message.answer(
            i18n.get("txid_received_checking", lang=lang),
            parse_mode="Markdown"
        )

        # Attempt immediate check
        verified = await CryptoVerifierService.process_transaction(session, tx, bot)
        await state.clear()

        if not verified:
            await message.answer(
                i18n.get("txid_still_pending", lang=lang)
            )


@router.callback_query(F.data == "tx_history")
async def handle_tx_history(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        u_res = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = u_res.scalar_one()
        lang = user.language_code or "en"

        q = select(WalletTransaction).where(
            WalletTransaction.user_id == user.id
        ).order_by(desc(WalletTransaction.created_at)).limit(10)
        res = await session.execute(q)
        txs = res.scalars().all()

        if not txs:
            await callback.message.answer(i18n.get("no_tx_found", lang=lang))
            await callback.answer()
            return

        lines = [i18n.get("tx_history_header", lang=lang)]
        for tx in txs:
            type_lbl = i18n.get_tx_type_label(tx.type, lang=lang)
            status_lbl = i18n.get_status_label(tx.status, lang=lang)
            date_str = tx.created_at.strftime("%Y-%m-%d %H:%M")
            lines.append(
                f"▫️ **{type_lbl}** | `{tx.amount:,.2f} USDT`\n"
                f"   Status: {status_lbl} | {tx.network} | {date_str}\n"
            )

        await callback.message.answer("\n".join(lines), parse_mode="Markdown")

    await callback.answer()


@router.message(Command("orders"))
@router.message(Command("orders", "my_orders"))
@router.message(F.text.in_(
    i18n.get_all_button_texts("btn_my_orders") +
    ["📦 My Orders", "My Orders", "Orders"]
))
async def show_workspace_orders(message: Message):
    async with AsyncSessionLocal() as session:
        u_res = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = u_res.scalar_one()
        lang = user.language_code or "en"

        orders = await OrderService.list_user_orders(session, user.id, limit=10)
        if not orders:
            await message.answer(
                f"📦 **{i18n.get('btn_my_orders', lang)}**\n\n{i18n.get('no_orders', lang)}",
                parse_mode="Markdown"
            )
            return

        text = f"📦 **{i18n.get('my_orders_title', lang)}**\n"
        await message.answer(text, parse_mode="Markdown")

        for o in orders:
            status_lbl = i18n.get_status_label(o.status, lang=lang)
            title = o.category.get_title(lang) if o.category else "Service"
            date_str = o.created_at.strftime("%Y-%m-%d %H:%M")

            order_card = (
                f"🧾 **Order:** `{o.order_code}`\n"
                f"📁 **Service:** {title}\n"
                f"💰 **Amount:** `{o.amount_paid:,.2f}` USDT\n"
                f"📊 **Status:** {status_lbl}\n"
                f"📅 **Date:** {date_str}\n"
            )

            kb = None
            if o.status == "completed" and o.delivery_file_path:
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=i18n.get("btn_download_delivered", lang=lang), callback_data=f"dl_order:{o.id}")
                ]])

            await message.answer(order_card, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("dl_order:"))
async def handle_download_order(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        u_res = await session.execute(select(User.language_code).where(User.telegram_id == callback.from_user.id))
        lang = u_res.scalar_one_or_none() or "en"

        order = await OrderService.get_order_by_id(session, order_id)
        if not order or not order.delivery_file_path or not os.path.exists(order.delivery_file_path):
            await callback.answer(i18n.get("file_not_found_server", lang=lang), show_alert=True)
            return

        doc = FSInputFile(order.delivery_file_path)
        caption = i18n.get("delivered_file_caption", lang=lang, order_code=order.order_code)
        await bot.send_document(
            chat_id=callback.from_user.id,
            document=doc,
            caption=caption,
            parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data == "cancel_wallet")
async def handle_cancel_wallet(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    await state.clear()
    await callback.message.edit_text(i18n.get("deposit_cancelled", lang=lang))
    await callback.answer()

