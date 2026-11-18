from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import StaffUser
from app.services.auth_service import AuthService
from app.web.templates_conf import templates

router = APIRouter(tags=["Auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None}
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    query = select(StaffUser).where(StaffUser.username == username.strip())
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user or not user.is_active or not AuthService.verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "نام کاربری یا رمز عبور اشتباه است، یا حساب غیرفعال می‌باشد."},
            status_code=400
        )

    # Generate JWT
    token = AuthService.create_access_token({"sub": user.username, "role": user.role})

    # Redirect based on role
    redirect_url = "/admin/dashboard" if user.role == "super_admin" else "/support/dashboard"
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=86400,
        samesite="lax"
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token")
    return response
