import secrets
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column, Integer, BigInteger, String, Numeric, Boolean, 
    DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship
from app.database import Base


def generate_api_token() -> str:
    return secrets.token_urlsafe(32)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    username = Column(String(64), nullable=True)
    first_name = Column(String(128), nullable=True)
    language_code = Column(String(5), default="en", nullable=False)
    is_language_selected = Column(Boolean, default=False, nullable=False)
    wallet_balance = Column(Numeric(18, 8, asdecimal=False), default=0.0, nullable=False)
    api_token = Column(String(64), unique=True, index=True, default=generate_api_token, nullable=False)
    last_lucky_spin = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("WalletTransaction", back_populates="user", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True)
    titles = Column(JSON, default=dict, nullable=False)  # {"fa": "...", "en": "..."}
    descriptions = Column(JSON, default=dict, nullable=True)  # {"fa": "...", "en": "..."}
    price = Column(Numeric(18, 8, asdecimal=False), default=0.0, nullable=False)
    is_leaf = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    parent = relationship("Category", remote_side=[id], back_populates="children")
    children = relationship("Category", back_populates="parent", cascade="all, delete-orphan", order_by="Category.sort_order", lazy="selectin")
    form_fields = relationship("CategoryFormField", back_populates="category", cascade="all, delete-orphan", order_by="CategoryFormField.sort_order", lazy="selectin")
    orders = relationship("Order", back_populates="category")

    def get_title(self, lang: str = "en") -> str:
        if isinstance(self.titles, dict):
            return self.titles.get(lang) or self.titles.get("en") or self.titles.get("fa") or "Untitled"
        return str(self.titles or "Untitled")

    def get_description(self, lang: str = "en") -> str:
        if isinstance(self.descriptions, dict):
            return self.descriptions.get(lang) or self.descriptions.get("en") or self.descriptions.get("fa") or ""
        return str(self.descriptions or "")


class CategoryFormField(Base):
    __tablename__ = "category_form_fields"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    field_key = Column(String(64), nullable=False)
    labels = Column(JSON, default=dict, nullable=False)
    field_type = Column(String(32), default="text", nullable=False)
    options = Column(JSON, nullable=True)
    validation_regex = Column(String(255), nullable=True)
    is_required = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    category = relationship("Category", back_populates="form_fields")

    def get_label(self, lang: str = "en") -> str:
        if isinstance(self.labels, dict):
            return self.labels.get(lang) or self.labels.get("en") or self.labels.get("fa") or self.field_key
        return str(self.labels or self.field_key)


class StaffUser(Base):
    __tablename__ = "staff_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="support", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    assigned_orders = relationship("Order", back_populates="assigned_support")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_code = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    form_data = Column(JSON, default=dict, nullable=False)
    amount_paid = Column(Numeric(18, 8, asdecimal=False), default=0.0, nullable=False)
    status = Column(String(32), default="paid_in_queue", nullable=False)
    delivery_file_path = Column(String(500), nullable=True)
    admin_notes = Column(Text, nullable=True)
    assigned_support_id = Column(Integer, ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="orders", lazy="selectin")
    category = relationship("Category", back_populates="orders", lazy="selectin")
    assigned_support = relationship("StaffUser", back_populates="assigned_orders", lazy="selectin")


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(32), nullable=False)
    amount = Column(Numeric(18, 8, asdecimal=False), nullable=False)
    tx_hash = Column(String(128), unique=True, index=True, nullable=True)
    network = Column(String(32), default="TRC20", nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="transactions", lazy="selectin")


class Translation(Base):
    __tablename__ = "translations"

    id = Column(Integer, primary_key=True, index=True)
    lang_code = Column(String(5), default="fa", nullable=False, index=True)
    trans_key = Column(String(100), nullable=False, index=True)
    trans_value = Column(Text, nullable=False)


class Setting(Base):
    __tablename__ = "settings"

    setting_key = Column(String(64), primary_key=True)
    setting_value = Column(Text, nullable=False)


class PortfolioItem(Base):
    __tablename__ = "portfolio_items"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    image_path = Column(String(500), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    category = relationship("Category", lazy="selectin")


class LuckyWheelSpin(Base):
    __tablename__ = "lucky_wheel_spins"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    prize_type = Column(String(32), nullable=False)  # "usdt", "empty", "retry"
    prize_value = Column(Numeric(18, 8, asdecimal=False), default=0.0, nullable=False)
    prize_label = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", lazy="selectin")

