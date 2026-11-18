import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import User, Category, CategoryFormField, Order, WalletTransaction, Setting, PortfolioItem
from app.services.category_service import CategoryService
from app.services.order_service import OrderService
from app.services.i18n_service import i18n, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE
from app.services.telegram_auth_service import (
    TelegramAuthService,
    get_current_webapp_user
)
from app.bot.dispatcher import get_bot_instance

router = APIRouter(prefix="", tags=["Telegram Mini App"])
templates = Jinja2Templates(directory="app/web/templates")


# --- Pydantic Schemas ---
class AuthRequest(BaseModel):
    init_data: str
    lang: Optional[str] = None


class OrderCreateRequest(BaseModel):
    category_id: int
    form_data: Dict[str, Any]


class UpdateLanguageRequest(BaseModel):
    language_code: str


class SubmitTxRequest(BaseModel):
    tx_hash: str
    network: str = "TRC20"


# --- WebApp Page View ---
@router.get("/webapp", response_class=HTMLResponse)
async def webapp_page(request: Request, lang: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Serves the standalone Telegram Mini App client."""
    bot = get_bot_instance()
    bot_username = "BotsallerBot"
    try:
        bot_user = await bot.get_me()
        if bot_user and bot_user.username:
            bot_username = bot_user.username
    except Exception:
        s = (await db.execute(select(Setting).where(Setting.setting_key == "support_username"))).scalar_one_or_none()
        if s and s.setting_value:
            bot_username = s.setting_value.replace("@", "").strip()

    initial_lang = lang or request.query_params.get("lang") or "en"
    if initial_lang not in SUPPORTED_LANGUAGES:
        initial_lang = "en"
    initial_dir = SUPPORTED_LANGUAGES.get(initial_lang, {}).get("dir", "ltr")

    return templates.TemplateResponse(
        request=request,
        name="miniapp.html",
        context={
            "app_title": "Botsaller Mini App",
            "bot_username": bot_username,
            "initial_lang": initial_lang,
            "initial_dir": initial_dir
        }
    )


# --- REST API for Mini App ---

@router.post("/api/v1/webapp/auth")
async def webapp_auth(payload: AuthRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticates Telegram WebApp client using initData.
    Returns access token and user information.
    """
    is_valid, user_data = TelegramAuthService.validate_init_data(payload.init_data, settings.BOT_TOKEN)
    if not is_valid or not user_data or "id" not in user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram authentication failed. Please open this app via the official bot."
        )

    req_lang = payload.lang if payload.lang in SUPPORTED_LANGUAGES else None
    user_lang = req_lang or user_data.get("language_code") or "en"
    if user_lang not in SUPPORTED_LANGUAGES:
        user_lang = "en"

    user = await TelegramAuthService.get_or_create_telegram_user(
        db,
        telegram_id=int(user_data["id"]),
        username=user_data.get("username"),
        first_name=user_data.get("first_name"),
        language_code=user_lang
    )

    if req_lang and not user.is_language_selected:
        user.language_code = req_lang
        await db.commit()

    token = TelegramAuthService.create_user_token(user)

    return {
        "status": "success",
        "token": token,
        "user": {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "first_name": user.first_name,
            "username": user.username,
            "language_code": user.language_code,
            "wallet_balance": float(user.wallet_balance),
            "api_token": user.api_token
        }
    }


@router.get("/api/v1/webapp/profile")
async def webapp_profile(
    current_user: User = Depends(get_current_webapp_user),
    db: AsyncSession = Depends(get_db)
):
    """Returns current user's profile, balance and quick stats."""
    # Count orders
    total_orders_res = await db.execute(
        select(func.count(Order.id)).where(Order.user_id == current_user.id)
    )
    total_orders = total_orders_res.scalar() or 0

    active_orders_res = await db.execute(
        select(func.count(Order.id)).where(
            Order.user_id == current_user.id,
            Order.status.in_(["paid_in_queue", "in_progress", "needs_review"])
        )
    )
    active_orders = active_orders_res.scalar() or 0

    return {
        "id": current_user.id,
        "telegram_id": current_user.telegram_id,
        "first_name": current_user.first_name,
        "username": current_user.username,
        "language_code": current_user.language_code,
        "wallet_balance": float(current_user.wallet_balance),
        "total_orders": total_orders,
        "active_orders": active_orders,
        "api_token": current_user.api_token
    }


@router.post("/api/v1/webapp/profile/language")
async def webapp_update_language(
    payload: UpdateLanguageRequest,
    current_user: User = Depends(get_current_webapp_user),
    db: AsyncSession = Depends(get_db)
):
    """Updates user's preferred language."""
    if payload.language_code in ["en", "fa", "ru", "zh", "hi"]:
        current_user.language_code = payload.language_code
        current_user.is_language_selected = True
        await db.commit()
    return {"success": True, "language_code": current_user.language_code}


@router.get("/api/v1/webapp/categories")
async def webapp_categories(lang: str = "en", db: AsyncSession = Depends(get_db)):
    """Returns nested category tree and services for the Mini App catalog."""
    query = (
        select(Category)
        .where(Category.is_active == True)
        .order_by(Category.sort_order, Category.id)
        .options(selectinload(Category.form_fields))
    )
    res = await db.execute(query)
    all_cats = list(res.scalars().all())

    cat_map = {}
    for cat in all_cats:
        cat_map[cat.id] = {
            "id": cat.id,
            "parent_id": cat.parent_id,
            "title": cat.get_title(lang),
            "description": cat.get_description(lang),
            "price": float(cat.price),
            "is_leaf": cat.is_leaf,
            "sort_order": cat.sort_order,
            "fields_count": len(cat.form_fields),
            "children": []
        }

    tree = []
    for cat in all_cats:
        if cat.parent_id and cat.parent_id in cat_map:
            cat_map[cat.parent_id]["children"].append(cat_map[cat.id])
        elif cat.parent_id is None:
            tree.append(cat_map[cat.id])

    return {
        "tree": tree,
        "all_services": [item for item in cat_map.values() if item["is_leaf"]]
    }


@router.get("/api/v1/webapp/portfolio")
async def webapp_portfolio(
    category_id: Optional[int] = None,
    lang: str = "en",
    db: AsyncSession = Depends(get_db)
):
    """Returns active portfolio items for Mini App gallery."""
    query = (
        select(PortfolioItem)
        .where(PortfolioItem.is_active == True)
        .order_by(PortfolioItem.sort_order, PortfolioItem.id.desc())
        .options(selectinload(PortfolioItem.category))
    )
    if category_id:
        query = query.where(PortfolioItem.category_id == category_id)

    res = await db.execute(query)
    items = res.scalars().all()

    return {
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "description": item.description,
                "image_path": item.image_path,
                "category_id": item.category_id,
                "category_title": item.category.get_title(lang) if item.category else None,
                "category_price": float(item.category.price) if item.category else None,
                "created_at": item.created_at.strftime("%Y/%m/%d") if item.created_at else ""
            }
            for item in items
        ]
    }


@router.get("/api/v1/webapp/categories/{category_id}/fields")
async def webapp_category_fields(category_id: int, lang: str = "en", db: AsyncSession = Depends(get_db)):
    """Returns dynamic form fields required for placing an order in a category."""
    category = await CategoryService.get_category_by_id(db, category_id, load_fields=True)
    if not category:
        raise HTTPException(status_code=404, detail="Category or service not found.")

    fields = [
        {
            "id": f.id,
            "field_key": f.field_key,
            "label": f.get_label(lang),
            "field_type": f.field_type,
            "options": f.options,
            "validation_regex": f.validation_regex,
            "is_required": f.is_required,
            "sort_order": f.sort_order
        }
        for f in category.form_fields
    ]

    return {
        "category": {
            "id": category.id,
            "title": category.get_title(lang),
            "description": category.get_description(lang),
            "price": float(category.price)
        },
        "fields": fields
    }


@router.post("/api/v1/webapp/upload")
async def webapp_upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_webapp_user)
):
    """Uploads customer files (images, documents) from the Mini App."""
    client_uploads_dir = os.path.join(settings.UPLOAD_DIR, "client_uploads")
    os.makedirs(client_uploads_dir, exist_ok=True)

    extension = os.path.splitext(file.filename)[1] if file.filename else ""
    safe_filename = f"user_{current_user.telegram_id}_{uuid.uuid4().hex[:10]}{extension}"
    save_path = os.path.join(client_uploads_dir, safe_filename)

    contents = await file.read()
    with open(save_path, "wb") as f:
        f.write(contents)

    file_url = f"/uploads/client_uploads/{safe_filename}"
    return {
        "success": True,
        "file_url": file_url,
        "filename": file.filename
    }


@router.post("/api/v1/webapp/orders")
async def webapp_create_order(
    payload: OrderCreateRequest,
    current_user: User = Depends(get_current_webapp_user),
    db: AsyncSession = Depends(get_db)
):
    """Places an order, verifies and deducts wallet balance atomically."""
    user_lang = current_user.language_code or "en"
    # Check category
    cat = await CategoryService.get_category_by_id(db, payload.category_id, load_fields=True)
    if not cat or not cat.is_leaf:
        raise HTTPException(status_code=400, detail="Category or service is not valid.")

    # Check required fields
    for field in cat.form_fields:
        if field.is_required and (field.field_key not in payload.form_data or not payload.form_data[field.field_key]):
            raise HTTPException(
                status_code=400,
                detail=i18n.get("field_required_error", lang=user_lang, label=field.get_label(user_lang))
            )

    # Check wallet balance
    if float(current_user.wallet_balance) < float(cat.price):
        raise HTTPException(
            status_code=400,
            detail=i18n.get(
                "insufficient_balance_error",
                lang=user_lang,
                balance=f"{current_user.wallet_balance:,.2f}",
                price=f"{cat.price:,.2f}"
            )
        )

    try:
        bot = get_bot_instance()
        order = await OrderService.create_paid_order(
            db=db,
            user_id=current_user.id,
            category_id=cat.id,
            form_data=payload.form_data,
            bot=bot
        )
        return {
            "success": True,
            "message": i18n.get("order_success_msg", lang=user_lang),
            "order": {
                "id": order.id,
                "order_code": order.order_code,
                "status": order.status,
                "amount_paid": float(order.amount_paid),
                "created_at": order.created_at.strftime("%Y/%m/%d %H:%M")
            }
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Order error: {str(e)}")


@router.get("/api/v1/webapp/orders")
async def webapp_list_orders(
    lang: Optional[str] = None,
    current_user: User = Depends(get_current_webapp_user),
    db: AsyncSession = Depends(get_db)
):
    """Returns list of past and active orders for the user."""
    user_lang = lang or current_user.language_code or "en"
    query = (
        select(Order)
        .where(Order.user_id == current_user.id)
        .order_by(desc(Order.created_at))
        .options(selectinload(Order.category))
    )
    res = await db.execute(query)
    orders = res.scalars().all()

    status_colors = {
        "paid_in_queue": "blue",
        "in_progress": "amber",
        "needs_review": "orange",
        "completed": "green",
        "cancelled": "red"
    }

    results = []
    for o in orders:
        results.append({
            "id": o.id,
            "order_code": o.order_code,
            "category_title": o.category.get_title(user_lang) if o.category else i18n.get("custom_service", lang=user_lang, default="Custom Service"),
            "amount_paid": float(o.amount_paid),
            "status": o.status,
            "status_label": i18n.get_status_label(o.status, lang=user_lang),
            "status_color": status_colors.get(o.status, "gray"),
            "delivery_file_url": f"/{o.delivery_file_path.replace(os.sep, '/')}" if o.delivery_file_path else None,
            "delivery_file_name": os.path.basename(o.delivery_file_path) if o.delivery_file_path else None,
            "admin_notes": o.admin_notes,
            "form_data": o.form_data,
            "created_at": o.created_at.strftime("%Y/%m/%d - %H:%M"),
            "updated_at": o.updated_at.strftime("%Y/%m/%d - %H:%M") if o.updated_at else None
        })

    return {"orders": results}


@router.get("/api/v1/webapp/wallet")
async def webapp_wallet_info(
    lang: Optional[str] = None,
    current_user: User = Depends(get_current_webapp_user),
    db: AsyncSession = Depends(get_db)
):
    """Returns wallet deposit addresses, balance, and transaction history."""
    user_lang = lang or current_user.language_code or "en"

    async def get_setting(key: str, default: str) -> str:
        s = (await db.execute(select(Setting).where(Setting.setting_key == key))).scalar_one_or_none()
        return s.setting_value.strip() if s and s.setting_value else default

    cold_trc20 = await get_setting("cold_wallet_trc20", settings.COLD_WALLET_TRC20)
    cold_bep20 = await get_setting("cold_wallet_bep20", settings.COLD_WALLET_BEP20)
    min_dep = await get_setting("min_deposit", "1.0")

    tx_q = (
        select(WalletTransaction)
        .where(WalletTransaction.user_id == current_user.id)
        .order_by(desc(WalletTransaction.created_at))
        .limit(30)
    )
    tx_res = await db.execute(tx_q)
    txs = tx_res.scalars().all()

    tx_list = [
        {
            "id": t.id,
            "type": t.type,
            "type_label": i18n.get_tx_type_label(t.type, lang=user_lang),
            "amount": float(t.amount),
            "tx_hash": t.tx_hash,
            "network": t.network,
            "status": t.status,
            "status_label": i18n.get(f"tx_status_{t.status}", lang=user_lang, default=t.status),
            "created_at": t.created_at.strftime("%Y/%m/%d %H:%M")
        }
        for t in txs
    ]

    return {
        "balance": float(current_user.wallet_balance),
        "deposit_addresses": {
            "TRC20": cold_trc20,
            "BEP20": cold_bep20
        },
        "min_deposit": float(min_dep),
        "transactions": tx_list
    }


@router.post("/api/v1/webapp/wallet/submit-tx")
async def webapp_submit_tx(
    payload: SubmitTxRequest,
    current_user: User = Depends(get_current_webapp_user),
    db: AsyncSession = Depends(get_db)
):
    """Submits a crypto transaction hash for background verification."""
    user_lang = current_user.language_code or "en"
    tx_hash = payload.tx_hash.strip()
    if len(tx_hash) < 20:
        raise HTTPException(status_code=400, detail=i18n.get("txid_invalid", lang=user_lang))

    # Check if duplicate
    existing = (await db.execute(select(WalletTransaction).where(WalletTransaction.tx_hash == tx_hash))).scalar_one_or_none()
    if existing:
        if existing.status == "confirmed":
            raise HTTPException(status_code=400, detail=i18n.get("txid_already_confirmed", lang=user_lang))
        else:
            raise HTTPException(status_code=400, detail=i18n.get("txid_already_pending", lang=user_lang))

    new_tx = WalletTransaction(
        user_id=current_user.id,
        type="deposit",
        amount=0.0,
        tx_hash=tx_hash,
        network=payload.network.upper(),
        status="pending"
    )
    db.add(new_tx)
    await db.commit()

    return {
        "success": True,
        "message": i18n.get("tx_submitted_success", lang=user_lang)
    }
