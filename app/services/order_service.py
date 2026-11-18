import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, update
from sqlalchemy.orm import selectinload
from aiogram import Bot
from aiogram.types import FSInputFile
from app.models import Order, User, Category, WalletTransaction, Setting
from app.services.i18n_service import i18n


class OrderService:
    @staticmethod
    def generate_order_code() -> str:
        date_str = datetime.utcnow().strftime("%Y%m%d")
        suffix = uuid.uuid4().hex[:6].upper()
        return f"ORD-{date_str}-{suffix}"

    @staticmethod
    async def create_paid_order(
        db: AsyncSession,
        user_id: int,
        category_id: int,
        form_data: Dict[str, Any],
        bot: Optional[Bot] = None
    ) -> Order:
        # Atomic lock on user row
        user_query = select(User).where(User.id == user_id).with_for_update()
        user_res = await db.execute(user_query)
        user = user_res.scalar_one()

        cat_query = select(Category).where(Category.id == category_id)
        cat_res = await db.execute(cat_query)
        category = cat_res.scalar_one()

        order_amount = float(category.price)

        if user.wallet_balance < order_amount:
            user_lang = user.language_code or "en"
            err_msg = i18n.get(
                "insufficient_balance_error",
                lang=user_lang,
                balance=f"{user.wallet_balance:,.2f}",
                price=f"{order_amount:,.2f}"
            )
            raise ValueError(err_msg)

        # Deduct balance
        user.wallet_balance = float(user.wallet_balance) - order_amount

        order_code = OrderService.generate_order_code()
        order = Order(
            order_code=order_code,
            user_id=user.id,
            category_id=category.id,
            status="paid_in_queue",
            amount_paid=order_amount,
            form_data=form_data
        )
        db.add(order)

        # Log WalletTransaction
        tx = WalletTransaction(
            user_id=user.id,
            type="order_payment",
            amount=order_amount,
            tx_hash=f"ORD-PAY-{order_code}",
            network="INTERNAL",
            status="confirmed"
        )
        db.add(tx)

        await db.commit()
        await db.refresh(order)

        # Notify operator group/channel if configured
        if bot:
            await OrderService.notify_operator_group(db, bot, order, user, category)

        return order

    @staticmethod
    async def notify_operator_group(
        db: AsyncSession,
        bot: Bot,
        order: Order,
        user: User,
        category: Category
    ) -> None:
        try:
            setting_res = await db.execute(
                select(Setting).where(Setting.setting_key == "operator_chat_id")
            )
            setting = setting_res.scalar_one_or_none()
            if not setting or not setting.setting_value.strip():
                return

            chat_id = setting.setting_value.strip()

            lines = [
                "🔔 **سفارش جدید ثبت و پرداخت شد!**",
                f"📦 **کد سفارش:** `{order.order_code}`",
                f"📁 **سرویس:** {category.get_title('fa')}",
                f"💰 **مبلغ پرداخت‌شده:** {order.amount_paid:,.2f} USDT",
                f"👤 **مشتری:** {user.first_name or 'کاربر'} (@{user.username or 'ندارد'}) [ID: `{user.telegram_id}`]",
                "━━━━━━━━━━━━━━━",
                "📝 **اطلاعات ثبت‌شده توسط کاربر:**"
            ]

            for key, val in (order.form_data or {}).items():
                label = val.get("label", key)
                ans = val.get("value", "-")
                file_type = val.get("type")
                if file_type in ("photo", "document"):
                    lines.append(f"▫️ **{label}:** [فایل/تصویر پیوست]")
                else:
                    lines.append(f"▫️ **{label}:** {ans}")

            message_text = "\n".join(lines)
            await bot.send_message(chat_id=chat_id, text=message_text, parse_mode="Markdown")

            # Send attachments if any
            for key, val in (order.form_data or {}).items():
                local_path = val.get("local_path")
                if local_path and os.path.exists(local_path):
                    doc = FSInputFile(local_path)
                    caption = f"پیوست سفارش {order.order_code} - {val.get('label', key)}"
                    await bot.send_document(chat_id=chat_id, document=doc, caption=caption)
        except Exception as e:
            print(f"[OrderService] Could not notify operator chat: {e}")

    @staticmethod
    async def get_order_by_id(db: AsyncSession, order_id: int) -> Optional[Order]:
        query = select(Order).where(Order.id == order_id).options(
            selectinload(Order.user),
            selectinload(Order.category),
            selectinload(Order.assigned_support)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_order_by_code(db: AsyncSession, order_code: str) -> Optional[Order]:
        query = select(Order).where(Order.order_code == order_code).options(
            selectinload(Order.user),
            selectinload(Order.category),
            selectinload(Order.assigned_support)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_user_orders(db: AsyncSession, user_id: int, limit: int = 20) -> List[Order]:
        query = select(Order).where(Order.user_id == user_id).options(
            selectinload(Order.category)
        ).order_by(desc(Order.created_at)).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def list_orders(
        db: AsyncSession,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Order]:
        query = select(Order).options(
            selectinload(Order.user),
            selectinload(Order.category),
            selectinload(Order.assigned_support)
        ).order_by(desc(Order.created_at)).offset(offset).limit(limit)

        if status:
            query = query.where(Order.status == status)

        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_counts(db: AsyncSession) -> Dict[str, int]:
        total_q = select(func.count(Order.id))
        queue_q = select(func.count(Order.id)).where(Order.status == "paid_in_queue")
        review_q = select(func.count(Order.id)).where(Order.status == "needs_review")
        completed_q = select(func.count(Order.id)).where(Order.status == "completed")

        t = (await db.execute(total_q)).scalar_one() or 0
        q = (await db.execute(queue_q)).scalar_one() or 0
        r = (await db.execute(review_q)).scalar_one() or 0
        c = (await db.execute(completed_q)).scalar_one() or 0

        return {
            "total": t,
            "paid_in_queue": q,
            "needs_review": r,
            "completed": c
        }

    @staticmethod
    async def deliver_and_complete(
        db: AsyncSession,
        order_id: int,
        delivery_file_path: Optional[str],
        admin_notes: Optional[str],
        support_id: Optional[int],
        bot: Optional[Bot] = None
    ) -> Order:
        order = await OrderService.get_order_by_id(db, order_id)
        if not order:
            raise ValueError("سفارش یافت نشد.")

        order.status = "completed"
        if delivery_file_path:
            order.delivery_file_path = delivery_file_path
        if admin_notes:
            order.admin_notes = admin_notes
        if support_id:
            order.assigned_support_id = support_id

        await db.commit()
        await db.refresh(order)

        # Send completion message & deliverable document to customer via Telegram
        if bot and order.user and order.user.telegram_id:
            try:
                user_lang = order.user.language_code or "en"
                completed_at_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
                service_title = order.category.get_title(user_lang) if order.category else "Service"
                caption = i18n.get(
                    "order_completed_caption",
                    lang=user_lang,
                    order_code=order.order_code,
                    service_title=service_title,
                    completed_at=completed_at_str
                )
                if admin_notes:
                    caption += i18n.get("order_admin_note_prefix", lang=user_lang, notes=admin_notes)

                if delivery_file_path and os.path.exists(delivery_file_path):
                    doc = FSInputFile(delivery_file_path)
                    await bot.send_document(
                        chat_id=order.user.telegram_id,
                        document=doc,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                else:
                    await bot.send_message(
                        chat_id=order.user.telegram_id,
                        text=caption,
                        parse_mode="Markdown"
                    )
            except Exception as e:
                print(f"[OrderService] Failed to deliver document to user: {e}")

        return order
