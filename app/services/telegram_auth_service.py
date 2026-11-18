import hmac
import hashlib
import json
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import Request, HTTPException, Depends, Header, status

from app.config import settings
from app.database import get_db
from app.models import User
from app.services.auth_service import AuthService, ALGORITHM


class TelegramAuthService:
    @staticmethod
    def validate_init_data(init_data: str, bot_token: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Cryptographically validates Telegram WebApp initData query string using HMAC-SHA256
        according to official Telegram WebApp security specifications.
        Guarantees 100% account isolation and prevents identity spoofing.
        """
        if not init_data or not bot_token:
            return False, None

        try:
            parsed_data = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
            if "hash" not in parsed_data:
                return False, None

            received_hash = parsed_data.pop("hash")

            # Check auth_date expiration (24 hours = 86400 seconds) to prevent Replay Attacks
            auth_date_raw = parsed_data.get("auth_date")
            if not auth_date_raw:
                return False, None

            auth_timestamp = int(auth_date_raw)
            current_timestamp = int(datetime.utcnow().timestamp())
            if abs(current_timestamp - auth_timestamp) > 86400:
                print(f"[TelegramAuth] Rejected expired initData (timestamp: {auth_timestamp})")
                return False, None

            # Sort parameters alphabetically: k=v separated by \n
            data_check_list = [f"{k}={v}" for k, v in sorted(parsed_data.items())]
            data_check_string = "\n".join(data_check_list)

            # Secret key is HMAC-SHA256 of bot_token with constant "WebAppData"
            secret_key = hmac.new(
                key=b"WebAppData",
                msg=bot_token.encode("utf-8"),
                digestmod=hashlib.sha256
            ).digest()

            # Hash the data_check_string with secret_key
            calculated_hash = hmac.new(
                key=secret_key,
                msg=data_check_string.encode("utf-8"),
                digestmod=hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(calculated_hash, received_hash):
                print(f"[TelegramAuth] Invalid signature hash mismatch!")
                return False, None

            # Extract user object
            user_json_str = parsed_data.get("user")
            if not user_json_str:
                return False, None

            user_data = json.loads(user_json_str)
            if "id" not in user_data:
                return False, None

            return True, user_data

        except Exception as e:
            print(f"[TelegramAuthService Error] {e}")
            return False, None

    @staticmethod
    async def get_or_create_telegram_user(
        db: AsyncSession,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        language_code: str = "en"
    ) -> User:
        """
        Finds or registers the authenticated Telegram customer in the database.
        Strictly binds all wallet balances, transactions, and orders to this unique telegram_id.
        """
        result = await db.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                language_code=language_code or "en",
                wallet_balance=0.0
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        else:
            # Sync latest username / first_name if updated in Telegram
            updated = False
            if username and user.username != username:
                user.username = username
                updated = True
            if first_name and user.first_name != first_name:
                user.first_name = first_name
                updated = True
            if updated:
                await db.commit()
                await db.refresh(user)

        return user

    @staticmethod
    def create_user_token(user: User) -> str:
        """Creates a signed, scoped JWT access token for the Telegram user."""
        return AuthService.create_access_token(
            data={"sub": str(user.telegram_id), "user_id": user.id, "role": "telegram_user"},
            expires_delta=timedelta(days=7)
        )


async def get_current_webapp_user(
    authorization: Optional[str] = Header(None),
    x_telegram_init_data: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    FastAPI dependency that enforces strict authentication for all Mini App API endpoints.
    Denies access completely if request does not originate from an authenticated Telegram session.
    """
    # 1. Validate JWT Bearer token
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        payload = AuthService.decode_token(token)
        if payload and payload.get("sub") and payload.get("role") == "telegram_user":
            telegram_id = int(payload["sub"])
            user_res = await db.execute(select(User).where(User.telegram_id == telegram_id))
            user = user_res.scalar_one_or_none()
            if user:
                return user

    # 2. Validate raw X-Telegram-Init-Data header
    if x_telegram_init_data:
        is_valid, user_data = TelegramAuthService.validate_init_data(x_telegram_init_data, settings.BOT_TOKEN)
        if is_valid and user_data and "id" in user_data:
            user = await TelegramAuthService.get_or_create_telegram_user(
                db,
                telegram_id=int(user_data["id"]),
                username=user_data.get("username"),
                first_name=user_data.get("first_name"),
                language_code=user_data.get("language_code", "fa")
            )
            return user

    # Strict rejection: no unauthorized access allowed!
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="دسترسی غیرمجاز: این بخش فقط از طریق حساب کاربری تلگرام قابل دسترس است."
    )
