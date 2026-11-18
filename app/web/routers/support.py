import os
import uuid
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database import get_db
from app.models import StaffUser, Order, WalletTransaction
from app.services.auth_service import require_role, get_current_staff
from app.services.order_service import OrderService
from app.bot.dispatcher import get_bot_instance
from app.config import settings
from app.web.templates_conf import templates

router = APIRouter(prefix="/support", tags=["Support"], dependencies=[Depends(require_role(["super_admin", "support"]))])


@router.get("/dashboard", response_class=HTMLResponse)
async def support_dashboard(
    request: Request,
    current_staff: StaffUser = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db)
):
    # Orders needing review
    review_orders = await OrderService.list_orders(db, status="needs_review", limit=20)

    # Orders paid in queue
    queue_orders = await OrderService.list_orders(db, status="paid_in_queue", limit=20)

    # In progress
    in_progress_orders = await OrderService.list_orders(db, status="in_progress", limit=20)

    # Pending transactions
    tx_q = select(WalletTransaction).where(WalletTransaction.status == "pending").order_by(desc(WalletTransaction.created_at)).limit(20)
    pending_txs = (await db.execute(tx_q)).scalars().all()

    counts = await OrderService.get_counts(db)

    return templates.TemplateResponse(
        request=request,
        name="support_dashboard.html",
        context={
            "current_staff": current_staff,
            "review_orders": review_orders,
            "queue_orders": queue_orders,
            "in_progress_orders": in_progress_orders,
            "pending_txs": pending_txs,
            "counts": counts
        }
    )


@router.get("/orders/{order_id}", response_class=HTMLResponse)
async def support_order_detail(
    order_id: int,
    request: Request,
    current_staff: StaffUser = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db)
):
    order = await OrderService.get_order_by_id(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="سفارش یافت نشد.")

    return templates.TemplateResponse(
        request=request,
        name="support_order_detail.html",
        context={
            "current_staff": current_staff,
            "order": order
        }
    )


@router.post("/orders/{order_id}/status")
async def support_update_status(
    order_id: int,
    new_status: str = Form(...),
    admin_notes: Optional[str] = Form(None),
    current_staff: StaffUser = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db)
):
    order = await OrderService.get_order_by_id(db, order_id)
    if order:
        order.status = new_status
        if admin_notes:
            order.admin_notes = admin_notes
        order.assigned_support_id = current_staff.id
        await db.commit()
    return RedirectResponse(url=f"/support/orders/{order_id}", status_code=status.HTTP_302_FOUND)


@router.post("/orders/{order_id}/deliver")
async def support_deliver_order(
    order_id: int,
    file: Optional[UploadFile] = File(None),
    admin_notes: Optional[str] = Form(None),
    current_staff: StaffUser = Depends(get_current_staff),
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
        support_id=current_staff.id,
        bot=bot
    )
    return RedirectResponse(url=f"/support/orders/{order_id}", status_code=status.HTTP_302_FOUND)
