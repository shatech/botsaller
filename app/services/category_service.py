from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload
from app.models import Category, CategoryFormField


class CategoryService:
    @staticmethod
    async def get_root_categories(db: AsyncSession, only_active: bool = True) -> List[Category]:
        query = select(Category).where(Category.parent_id == None)
        if only_active:
            query = query.where(Category.is_active == True)
        query = query.order_by(Category.sort_order, Category.id)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_subcategories(db: AsyncSession, parent_id: int, only_active: bool = True) -> List[Category]:
        query = select(Category).where(Category.parent_id == parent_id)
        if only_active:
            query = query.where(Category.is_active == True)
        query = query.order_by(Category.sort_order, Category.id)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_category_by_id(db: AsyncSession, category_id: int, load_fields: bool = False) -> Optional[Category]:
        query = select(Category).where(Category.id == category_id)
        if load_fields:
            query = query.options(
                selectinload(Category.form_fields),
                selectinload(Category.children),
                selectinload(Category.parent)
            )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_breadcrumbs(db: AsyncSession, category_id: int) -> List[Category]:
        breadcrumbs = []
        curr_id = category_id
        while curr_id:
            cat = await CategoryService.get_category_by_id(db, curr_id)
            if not cat:
                break
            breadcrumbs.insert(0, cat)
            curr_id = cat.parent_id
        return breadcrumbs

    @staticmethod
    async def get_all_categories_flat(db: AsyncSession) -> List[Category]:
        query = select(Category).order_by(Category.sort_order, Category.id)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def create_category(
        db: AsyncSession,
        titles: Dict[str, str],
        descriptions: Optional[Dict[str, str]] = None,
        parent_id: Optional[int] = None,
        price: float = 0.0,
        is_leaf: bool = False,
        sort_order: int = 0,
        is_active: bool = True
    ) -> Category:
        category = Category(
            titles=titles,
            descriptions=descriptions or {},
            parent_id=parent_id,
            price=price,
            is_leaf=is_leaf,
            sort_order=sort_order,
            is_active=is_active
        )
        db.add(category)
        await db.commit()
        await db.refresh(category)
        return category

    @staticmethod
    async def update_category(
        db: AsyncSession,
        category_id: int,
        **kwargs
    ) -> Optional[Category]:
        category = await CategoryService.get_category_by_id(db, category_id)
        if not category:
            return None
        for key, value in kwargs.items():
            if hasattr(category, key):
                setattr(category, key, value)
        await db.commit()
        await db.refresh(category)
        return category

    @staticmethod
    async def delete_category(db: AsyncSession, category_id: int) -> bool:
        category = await CategoryService.get_category_by_id(db, category_id)
        if not category:
            return False
        await db.delete(category)
        await db.commit()
        return True

    # --- Dynamic Form Builder ---
    @staticmethod
    async def get_form_fields(db: AsyncSession, category_id: int) -> List[CategoryFormField]:
        query = select(CategoryFormField).where(
            CategoryFormField.category_id == category_id
        ).order_by(CategoryFormField.sort_order, CategoryFormField.id)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def add_form_field(
        db: AsyncSession,
        category_id: int,
        field_key: str,
        labels: Dict[str, str],
        field_type: str,
        options: Optional[List[Any]] = None,
        validation_regex: Optional[str] = None,
        is_required: bool = True,
        sort_order: int = 0
    ) -> CategoryFormField:
        field = CategoryFormField(
            category_id=category_id,
            field_key=field_key.strip().lower(),
            labels=labels,
            field_type=field_type,
            options=options,
            validation_regex=validation_regex,
            is_required=is_required,
            sort_order=sort_order
        )
        db.add(field)
        await db.commit()
        await db.refresh(field)
        return field

    @staticmethod
    async def update_form_field(
        db: AsyncSession,
        field_id: int,
        **kwargs
    ) -> Optional[CategoryFormField]:
        query = select(CategoryFormField).where(CategoryFormField.id == field_id)
        result = await db.execute(query)
        field = result.scalar_one_or_none()
        if not field:
            return None
        for key, value in kwargs.items():
            if hasattr(field, key):
                setattr(field, key, value)
        await db.commit()
        await db.refresh(field)
        return field

    @staticmethod
    async def delete_form_field(db: AsyncSession, field_id: int) -> bool:
        query = select(CategoryFormField).where(CategoryFormField.id == field_id)
        result = await db.execute(query)
        field = result.scalar_one_or_none()
        if not field:
            return False
        await db.delete(field)
        await db.commit()
        return True

    @staticmethod
    async def reorder_form_fields(db: AsyncSession, field_ids: List[int]) -> None:
        for idx, f_id in enumerate(field_ids):
            await db.execute(
                update(CategoryFormField).where(CategoryFormField.id == f_id).values(sort_order=idx)
            )
        await db.commit()
