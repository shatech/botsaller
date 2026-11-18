import os
from fastapi.templating import Jinja2Templates
from app.services.i18n_service import i18n

# Resolve absolute path to templates directory regardless of cwd
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(CURRENT_DIR, "templates")

templates = Jinja2Templates(directory=TEMPLATES_DIR)


def format_currency(val):
    try:
        if val is None:
            return "0.00 USDT"
        return f"{float(val):,.2f} USDT"
    except Exception:
        return f"{val} USDT"


# Register custom filters globally
templates.env.filters["format_currency"] = format_currency
templates.env.filters["status_label"] = i18n.get_status_label
templates.env.filters["field_type_label"] = i18n.get_field_type_label
templates.env.filters["tx_type_label"] = i18n.get_tx_type_label

