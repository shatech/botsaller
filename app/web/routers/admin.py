import os
import json
import uuid
from typing import Optional, List
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, update

from app.database import get_db
from app.models import (
    StaffUser, User, Category, CategoryFormField,
    Order, WalletTransaction, Setting, PortfolioItem
)
from app.services.auth_service import require_role, AuthService
from app.services.category_service import CategoryService
from app.services.order_service import OrderService
from app.services.crypto_verifier import CryptoVerifierService
from app.services.i18n_service import i18n
from app.bot.dispatcher import get_bot_instance
from app.config import settings
from app.web.templates_conf import templates

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_role("super_admin"))])


@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    # Metrics
    order_counts = await OrderService.get_counts(db)

    # Revenue
    rev_q = select(func.sum(Order.amount_paid)).where(Order.status.in_(["paid_in_queue", "in_progress", "completed"]))
    total_revenue = (await db.execute(rev_q)).scalar_one() or 0.0

    # User count
    users_q = select(func.count(User.id))
    total_users = (await db.execute(users_q)).scalar_one() or 0

    # Pending transactions
    pending_tx_q = select(func.count(WalletTransaction.id)).where(WalletTransaction.status == "pending")
    pending_txs = (await db.execute(pending_tx_q)).scalar_one() or 0

    # Recent orders
    recent_orders = await OrderService.list_orders(db, limit=10)

    # Recent transactions
    tx_q = select(WalletTransaction).order_by(desc(WalletTransaction.created_at)).limit(10)
    recent_txs = (await db.execute(tx_q)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "order_counts": order_counts,
            "total_revenue": total_revenue,
            "total_users": total_users,
            "pending_txs": pending_txs,
            "recent_orders": recent_orders,
            "recent_txs": recent_txs,
            "current_user": getattr(request.state, "current_staff", None)
        }
    )


# --- Category & Recursive Tree Management ---
@router.get("/categories", response_class=HTMLResponse)
async def list_categories_page(request: Request, db: AsyncSession = Depends(get_db)):
    categories = await CategoryService.get_all_categories_flat(db)
    cat_map = {c.id: c.get_title("fa") for c in categories}
    return templates.TemplateResponse(
        request=request,
        name="categories.html",
        context={
            "categories": categories,
            "cat_map": cat_map
        }
    )


@router.post("/categories/create")
async def create_category(
    title_fa: str = Form(...),
    title_en: Optional[str] = Form(None),
    description_fa: Optional[str] = Form(None),
    parent_id: Optional[str] = Form(None),
    price: float = Form(0.0),
    is_leaf: bool = Form(False),
    sort_order: int = Form(0),
    is_active: bool = Form(True),
    db: AsyncSession = Depends(get_db)
):
    pid = int(parent_id) if parent_id and parent_id.isdigit() else None
    titles = {"fa": title_fa.strip(), "en": title_en.strip() if title_en else title_fa.strip()}
    descriptions = {"fa": description_fa.strip() if description_fa else ""}

    await CategoryService.create_category(
        db=db,
        titles=titles,
        descriptions=descriptions,
        parent_id=pid,
        price=price,
        is_leaf=is_leaf,
        sort_order=sort_order,
        is_active=is_active
    )
    return RedirectResponse(url="/admin/categories", status_code=status.HTTP_302_FOUND)


@router.post("/categories/{cat_id}/edit")
async def edit_category(
    cat_id: int,
    title_fa: str = Form(...),
    description_fa: Optional[str] = Form(None),
    price: float = Form(0.0),
    is_leaf: bool = Form(False),
    sort_order: int = Form(0),
    is_active: bool = Form(True),
    db: AsyncSession = Depends(get_db)
):
    category = await CategoryService.get_category_by_id(db, cat_id)
    if category:
        titles = category.titles or {}
        titles["fa"] = title_fa.strip()
        descriptions = category.descriptions or {}
        descriptions["fa"] = description_fa.strip() if description_fa else ""

        await CategoryService.update_category(
            db,
            cat_id,
            titles=titles,
            descriptions=descriptions,
            price=price,
            is_leaf=is_leaf,
            sort_order=sort_order,
            is_active=is_active
        )
    return RedirectResponse(url="/admin/categories", status_code=status.HTTP_302_FOUND)


@router.post("/categories/{cat_id}/delete")
async def delete_category(cat_id: int, db: AsyncSession = Depends(get_db)):
    await CategoryService.delete_category(db, cat_id)
    return RedirectResponse(url="/admin/categories", status_code=status.HTTP_302_FOUND)


# --- Dynamic Form Builder ---
@router.get("/categories/{cat_id}/fields", response_class=HTMLResponse)
async def category_form_builder(cat_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    category = await CategoryService.get_category_by_id(db, cat_id, load_fields=True)
    if not category:
        raise HTTPException(status_code=404, detail="دسته‌بندی یافت نشد.")

    fields = await CategoryService.get_form_fields(db, cat_id)
    return templates.TemplateResponse(
        request=request,
        name="form_builder.html",
        context={
            "category": category,
            "fields": fields
        }
    )


@router.post("/categories/{cat_id}/fields/add")
async def add_form_field(
    cat_id: int,
    field_key: str = Form(...),
    label_fa: str = Form(...),
    field_type: str = Form(...),
    options_raw: Optional[str] = Form(None),
    validation_regex: Optional[str] = Form(None),
    is_required: bool = Form(True),
    sort_order: int = Form(0),
    db: AsyncSession = Depends(get_db)
):
    options = None
    if field_type == "select" and options_raw:
        options = [opt.strip() for opt in options_raw.replace("\r", "").split("\n") if opt.strip()]

    labels = {"fa": label_fa.strip()}
    await CategoryService.add_form_field(
        db=db,
        category_id=cat_id,
        field_key=field_key.strip().lower(),
        labels=labels,
        field_type=field_type,
        options=options,
        validation_regex=validation_regex.strip() if validation_regex else None,
        is_required=is_required,
        sort_order=sort_order
    )
    return RedirectResponse(url=f"/admin/categories/{cat_id}/fields", status_code=status.HTTP_302_FOUND)


@router.post("/categories/{cat_id}/fields/{field_id}/delete")
async def delete_form_field(cat_id: int, field_id: int, db: AsyncSession = Depends(get_db)):
    await CategoryService.delete_form_field(db, field_id)
    return RedirectResponse(url=f"/admin/categories/{cat_id}/fields", status_code=status.HTTP_302_FOUND)


# --- Orders Management & Deliverables ---
@router.get("/orders", response_class=HTMLResponse)
async def list_orders_page(
    request: Request,
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    orders = await OrderService.list_orders(db, status=status_filter, limit=100)
    order_counts = await OrderService.get_counts(db)
    return templates.TemplateResponse(
        request=request,
        name="orders.html",
        context={
            "orders": orders,
            "current_status": status_filter,
            "counts": order_counts
        }
    )


@router.get("/orders/{order_id}", response_class=HTMLResponse)
async def view_order_detail(order_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    order = await OrderService.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="سفارش یافت نشد.")

    return templates.TemplateResponse(
        request=request,
        name="order_detail.html",
        context={
            "order": order
        }
    )


@router.post("/orders/{order_id}/status")
async def update_order_status(
    order_id: int,
    new_status: str = Form(...),
    admin_notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    order = await OrderService.get_order_by_id(db, order_id)
    if order:
        order.status = new_status
        if admin_notes:
            order.admin_notes = admin_notes
        await db.commit()
    return RedirectResponse(url=f"/admin/orders/{order_id}", status_code=status.HTTP_302_FOUND)


@router.post("/orders/{order_id}/deliver")
async def deliver_order_file(
    order_id: int,
    file: Optional[UploadFile] = File(None),
    admin_notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    saved_file_path = None
    if file and file.filename:
        deliveries_dir = os.path.join(settings.UPLOAD_DIR, "deliveries")
        os.makedirs(deliveries_dir, exist_ok=True)
        filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
        saved_file_path = os.path.join(deliveries_dir, filename)

        contents = await file.read()
        with open(saved_file_path, "wb") as f:
            f.write(contents)

    bot = get_bot_instance()
    await OrderService.deliver_and_complete(
        db=db,
        order_id=order_id,
        delivery_file_path=saved_file_path,
        admin_notes=admin_notes,
        support_id=None,
        bot=bot
    )
    return RedirectResponse(url=f"/admin/orders/{order_id}", status_code=status.HTTP_302_FOUND)


# --- Finance & Wallet Settings ---
@router.get("/finance", response_class=HTMLResponse)
async def finance_settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    cold_trc20 = await CryptoVerifierService.get_setting(db, "cold_wallet_trc20", settings.COLD_WALLET_TRC20)
    cold_bep20 = await CryptoVerifierService.get_setting(db, "cold_wallet_bep20", settings.COLD_WALLET_BEP20)
    api_key_tron = await CryptoVerifierService.get_setting(db, "trongrid_api_key", settings.TRONSCAN_API_KEY)
    api_key_bsc = await CryptoVerifierService.get_setting(db, "bscscan_api_key", settings.BSCSCAN_API_KEY)
    operator_chat = await CryptoVerifierService.get_setting(db, "operator_chat_id", "")

    # List all transactions with eager-loaded user
    q = select(WalletTransaction).order_by(desc(WalletTransaction.created_at)).limit(100)
    txs = (await db.execute(q)).scalars().all()

    # List users for manual adjustment select
    u_q = select(User).order_by(User.id.desc()).limit(50)
    users = (await db.execute(u_q)).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="finance.html",
        context={
            "cold_trc20": cold_trc20,
            "cold_bep20": cold_bep20,
            "api_key_tron": api_key_tron,
            "api_key_bsc": api_key_bsc,
            "operator_chat": operator_chat,
            "transactions": txs,
            "users": users
        }
    )


@router.post("/finance/settings")
async def save_finance_settings(
    cold_wallet_trc20: str = Form(...),
    cold_wallet_bep20: str = Form(...),
    trongrid_api_key: Optional[str] = Form(""),
    bscscan_api_key: Optional[str] = Form(""),
    operator_chat_id: Optional[str] = Form(""),
    db: AsyncSession = Depends(get_db)
):
    updates = {
        "cold_wallet_trc20": cold_wallet_trc20.strip(),
        "cold_wallet_bep20": cold_wallet_bep20.strip(),
        "trongrid_api_key": trongrid_api_key.strip() if trongrid_api_key else "",
        "bscscan_api_key": bscscan_api_key.strip() if bscscan_api_key else "",
        "operator_chat_id": operator_chat_id.strip() if operator_chat_id else ""
    }
    for k, v in updates.items():
        row = (await db.execute(select(Setting).where(Setting.setting_key == k))).scalar_one_or_none()
        if not row:
            db.add(Setting(setting_key=k, setting_value=v))
        else:
            row.setting_value = v
    await db.commit()
    return RedirectResponse(url="/admin/finance", status_code=status.HTTP_302_FOUND)


@router.post("/finance/adjust")
async def manual_balance_adjust(
    user_id: int = Form(...),
    amount: float = Form(...),
    reason: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    u_q = select(User).where(User.id == user_id).with_for_update()
    user = (await db.execute(u_q)).scalar_one_or_none()
    if user:
        user.wallet_balance = float(user.wallet_balance) + amount
        tx = WalletTransaction(
            user_id=user.id,
            type="admin_adjustment",
            amount=abs(amount),
            tx_hash=f"ADJ-{uuid.uuid4().hex[:8].upper()}",
            network="INTERNAL",
            status="confirmed"
        )
        db.add(tx)
        await db.commit()

        # Notify user on Telegram
        bot = get_bot_instance()
        if user.telegram_id:
            try:
                sign_str = "افزایش" if amount >= 0 else "کاهش"
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        f"🔔 **تغییر موجودی توسط مدیریت سیستم**\n\n"
                        f"🔹 نوع تراکنش: {sign_str} موجودی\n"
                        f"💰 مبلغ: `{abs(amount):,.2f}` USDT\n"
                        f"📝 دلیل: {reason}\n"
                        f"💼 موجودی نهایی شما: `{float(user.wallet_balance):,.2f}` USDT"
                    ),
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    return RedirectResponse(url="/admin/finance", status_code=status.HTTP_302_FOUND)


# --- Staff Management ---
@router.get("/staff", response_class=HTMLResponse)
async def list_staff_page(request: Request, db: AsyncSession = Depends(get_db)):
    q = select(StaffUser).order_by(StaffUser.id.desc())
    staff_list = (await db.execute(q)).scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="staff.html",
        context={
            "staff_list": staff_list
        }
    )


@router.post("/staff/create")
async def create_staff_user(
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("support"),
    db: AsyncSession = Depends(get_db)
):
    pw_hash = AuthService.get_password_hash(password)
    user = StaffUser(
        username=username.strip(),
        password_hash=pw_hash,
        role=role,
        is_active=True
    )
    db.add(user)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
    return RedirectResponse(url="/admin/staff", status_code=status.HTTP_302_FOUND)


@router.post("/staff/{staff_id}/toggle")
async def toggle_staff_active(staff_id: int, db: AsyncSession = Depends(get_db)):
    q = select(StaffUser).where(StaffUser.id == staff_id)
    staff = (await db.execute(q)).scalar_one_or_none()
    if staff and staff.role != "super_admin":
        staff.is_active = not staff.is_active
        await db.commit()
    return RedirectResponse(url="/admin/staff", status_code=status.HTTP_302_FOUND)


# --- Portfolio / Samples Management ---
@router.get("/portfolio", response_class=HTMLResponse)
async def list_portfolio_page(request: Request, db: AsyncSession = Depends(get_db)):
    # Fetch all portfolio items ordered by sort_order and id desc
    q = select(PortfolioItem).order_by(PortfolioItem.sort_order, PortfolioItem.id.desc())
    items = (await db.execute(q)).scalars().all()

    # Fetch leaf services/categories for dropdown
    categories = await CategoryService.get_all_categories_flat(db)

    return templates.TemplateResponse(
        request=request,
        name="portfolio.html",
        context={
            "portfolio_items": items,
            "categories": categories
        }
    )


@router.post("/portfolio/create")
async def create_portfolio_item(
    title: str = Form(...),
    description: Optional[str] = Form(None),
    category_id: Optional[str] = Form(None),
    sort_order: int = Form(0),
    is_active: bool = Form(True),
    image_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    cid = int(category_id) if category_id and category_id.isdigit() else None

    # Handle image file upload
    portfolio_dir = os.path.join(settings.UPLOAD_DIR, "portfolio")
    os.makedirs(portfolio_dir, exist_ok=True)

    filename = image_file.filename or "sample.png"
    ext = os.path.splitext(filename)[1].lower()
    if not ext:
        ext = ".png"

    safe_filename = f"{uuid.uuid4().hex}{ext}"
    file_disk_path = os.path.join(portfolio_dir, safe_filename)

    content = await image_file.read()
    with open(file_disk_path, "wb") as f:
        f.write(content)

    web_image_path = f"/uploads/portfolio/{safe_filename}"

    item = PortfolioItem(
        title=title.strip(),
        description=description.strip() if description else None,
        image_path=web_image_path,
        category_id=cid,
        sort_order=sort_order,
        is_active=is_active
    )
    db.add(item)
    await db.commit()

    return RedirectResponse(url="/admin/portfolio", status_code=status.HTTP_302_FOUND)


@router.post("/portfolio/{item_id}/toggle")
async def toggle_portfolio_item(item_id: int, db: AsyncSession = Depends(get_db)):
    q = select(PortfolioItem).where(PortfolioItem.id == item_id)
    item = (await db.execute(q)).scalar_one_or_none()
    if item:
        item.is_active = not item.is_active
        await db.commit()
    return RedirectResponse(url="/admin/portfolio", status_code=status.HTTP_302_FOUND)


@router.post("/portfolio/{item_id}/delete")
async def delete_portfolio_item(item_id: int, db: AsyncSession = Depends(get_db)):
    q = select(PortfolioItem).where(PortfolioItem.id == item_id)
    item = (await db.execute(q)).scalar_one_or_none()
    if item:
        # Attempt to delete file from disk
        if item.image_path and item.image_path.startswith("/uploads/"):
            rel_path = item.image_path.replace("/uploads/", "", 1)
            full_disk_path = os.path.join(settings.UPLOAD_DIR, rel_path)
            if os.path.exists(full_disk_path):
                try:
                    os.remove(full_disk_path)
                except Exception:
                    pass

        await db.delete(item)
        await db.commit()
    return RedirectResponse(url="/admin/portfolio", status_code=status.HTTP_302_FOUND)
