from typing import List, Optional, Any
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo
)
from app.config import settings
from app.models import Category
from app.services.i18n_service import i18n, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE


def language_selection_keyboard() -> InlineKeyboardMarkup:
    """Returns inline keyboard with the 5 supported languages."""
    kb = [
        [
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            InlineKeyboardButton(text="🇮🇷 فارسی", callback_data="lang:fa"),
        ],
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
            InlineKeyboardButton(text="🇨🇳 中文", callback_data="lang:zh"),
        ],
        [
            InlineKeyboardButton(text="🇮🇳 हिन्दी", callback_data="lang:hi")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def main_menu_keyboard(lang: str = "en", miniapp_url: Optional[str] = None) -> ReplyKeyboardMarkup:
    """Returns clean English Reply Keyboard for user main menu."""
    url = miniapp_url or settings.MINIAPP_URL
    kb = []
    if url:
        sep = "&" if "?" in url else "?"
        url_with_lang = f"{url}{sep}lang={lang}"
        kb.append([
            KeyboardButton(
                text=f"🚀 Open Mini App",
                web_app=WebAppInfo(url=url_with_lang)
            )
        ])
    kb.extend([
        [
            KeyboardButton(text="🛍 Services & Products"),
            KeyboardButton(text="🎨 Portfolio & Samples")
        ],
        [
            KeyboardButton(text="💳 Wallet & Top-up"),
            KeyboardButton(text="📦 My Orders")
        ],
        [
            KeyboardButton(text="🆘 Support"),
            KeyboardButton(text="🔑 My Account Token")
        ]
    ])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def login_inline_keyboard(lang: str = "en", miniapp_url: Optional[str] = None) -> InlineKeyboardMarkup:
    """Returns localized inline button for opening the personalized Mini App."""
    url = miniapp_url or settings.MINIAPP_URL or "http://localhost:8000/webapp"
    sep = "&" if "?" in url else "?"
    url_with_lang = f"{url}{sep}lang={lang}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"🔐 {i18n.get('btn_login_webapp', lang)}",
                web_app=WebAppInfo(url=url_with_lang)
            )
        ]
    ])


def miniapp_inline_keyboard(lang: str = "en", miniapp_url: Optional[str] = None) -> InlineKeyboardMarkup:
    return login_inline_keyboard(lang=lang, miniapp_url=miniapp_url)


def categories_keyboard(
    categories: List[Category],
    parent_category: Optional[Category] = None,
    lang: str = "en"
) -> InlineKeyboardMarkup:
    inline_keyboard = []
    row = []

    for cat in categories:
        title = cat.get_title(lang)
        if cat.is_leaf:
            btn_text = f"✨ {title}"
        else:
            btn_text = f"📁 {title}"

        btn = InlineKeyboardButton(text=btn_text, callback_data=f"cat:{cat.id}")
        row.append(btn)
        if len(row) == 2:
            inline_keyboard.append(row)
            row = []

    if row:
        inline_keyboard.append(row)

    # Back / Close button
    if parent_category:
        back_data = f"cat:{parent_category.parent_id}" if parent_category.parent_id else "cat:root"
        inline_keyboard.append([
            InlineKeyboardButton(text=i18n.get("btn_back", lang), callback_data=back_data)
        ])
    else:
        inline_keyboard.append([
            InlineKeyboardButton(text=i18n.get("btn_cancel", lang), callback_data="close_catalog")
        ])

    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def leaf_service_keyboard(category_id: int, parent_id: Optional[int] = None, lang: str = "en") -> InlineKeyboardMarkup:
    back_data = f"cat:{parent_id}" if parent_id else "cat:root"
    kb = [
        [
            InlineKeyboardButton(text="✅ Order Now", callback_data=f"start_order:{category_id}")
        ],
        [
            InlineKeyboardButton(text="🎨 View Sample Works", callback_data=f"samples_cat:{category_id}")
        ],
        [
            InlineKeyboardButton(text="🔙 Back to Catalog", callback_data=back_data)
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def wizard_field_keyboard(is_required: bool, options: Optional[List[Any]] = None, lang: str = "en") -> InlineKeyboardMarkup:
    rows = []
    if options:
        for opt in options:
            opt_text = opt if isinstance(opt, str) else str(opt.get(lang) or opt.get("en") or opt.get("fa", opt))
            rows.append([
                InlineKeyboardButton(text=f"▫️ {opt_text}", callback_data=f"opt:{opt_text}")
            ])

    actions = []
    if not is_required:
        actions.append(InlineKeyboardButton(text=i18n.get("btn_skip", lang), callback_data="skip_field"))
    actions.append(InlineKeyboardButton(text=i18n.get("btn_cancel", lang), callback_data="cancel_wizard"))

    rows.append(actions)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_confirmation_keyboard(can_afford: bool, lang: str = "en") -> InlineKeyboardMarkup:
    rows = []
    if can_afford:
        rows.append([
            InlineKeyboardButton(text=i18n.get("btn_pay_wallet", lang), callback_data="confirm_pay_wallet")
        ])
    else:
        rows.append([
            InlineKeyboardButton(text=i18n.get("btn_topup_wallet", lang), callback_data="topup_for_order")
        ])

    rows.append([
        InlineKeyboardButton(text=i18n.get("btn_cancel", lang), callback_data="cancel_wizard")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wallet_networks_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="🌐 USDT (TRC20 - Tron)", callback_data="net:TRC20"),
        ],
        [
            InlineKeyboardButton(text="🌐 USDT (BEP20 - BSC)", callback_data="net:BEP20")
        ],
        [
            InlineKeyboardButton(text=i18n.get("btn_cancel_back", lang, default="❌ Cancel"), callback_data="cancel_wallet")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def portfolio_nav_keyboard(current_idx: int, total: int, category_id: Optional[int] = None, lang: str = "en") -> InlineKeyboardMarkup:
    """Navigation keyboard for browsing portfolio samples in Telegram bot."""
    rows = []
    nav_row = []

    if current_idx > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"port:{current_idx - 1}"))
    
    nav_row.append(InlineKeyboardButton(text=f"{current_idx + 1} / {total}", callback_data="port:noop"))

    if current_idx < total - 1:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"port:{current_idx + 1}"))

    if nav_row:
        rows.append(nav_row)

    if category_id:
        rows.append([
            InlineKeyboardButton(text=f"🛍 {i18n.get('btn_start_order', lang)}", callback_data=f"start_order:{category_id}")
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)
