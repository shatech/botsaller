import asyncio
from sqlalchemy import select, delete
from app.database import init_db, AsyncSessionLocal
from app.models import Category, CategoryFormField, PortfolioItem


COMMON_FORM_FIELDS = [
    {
        "field_key": "country",
        "labels": {"en": "Country Name"},
        "field_type": "text",
        "is_required": True,
        "sort_order": 1
    },
    {
        "field_key": "state_province",
        "labels": {"en": "State / Province"},
        "field_type": "text",
        "is_required": True,
        "sort_order": 2
    },
    {
        "field_key": "city",
        "labels": {"en": "City"},
        "field_type": "text",
        "is_required": True,
        "sort_order": 3
    },
    {
        "field_key": "address",
        "labels": {"en": "Full Street Address"},
        "field_type": "text",
        "is_required": True,
        "sort_order": 4
    },
    {
        "field_key": "zip_code",
        "labels": {"en": "ZIP / Postal Code"},
        "field_type": "text",
        "is_required": True,
        "sort_order": 5
    },
    {
        "field_key": "birth_date",
        "labels": {"en": "Date of Birth (YYYY/MM/DD)"},
        "field_type": "text",
        "is_required": True,
        "sort_order": 6
    },
    {
        "field_key": "first_name",
        "labels": {"en": "First Name"},
        "field_type": "text",
        "is_required": True,
        "sort_order": 7
    },
    {
        "field_key": "middle_name",
        "labels": {"en": "Middle Name (Optional)"},
        "field_type": "text",
        "is_required": False,
        "sort_order": 8
    },
    {
        "field_key": "last_name",
        "labels": {"en": "Last Name / Surname"},
        "field_type": "text",
        "is_required": True,
        "sort_order": 9
    },
    {
        "field_key": "father_name",
        "labels": {"en": "Father's Name"},
        "field_type": "text",
        "is_required": True,
        "sort_order": 10
    }
]

PRODUCTS_SPEC = [
    {
        "key": "passport",
        "title": "Passport",
        "description": "High-resolution international biometric passport with valid MRZ barcode and official specs.\n⚡ Delivery: Fast digital delivery within 3 hours.",
        "price": 15.0,
        "is_leaf": True,
        "sort_order": 1,
        "sample_title": "Biometric Passport Sample (ICAO Standard)",
        "sample_desc": "Full 4K biometric passport sample with UV patterns, watermark and machine-readable zone (MRZ).",
        "sample_image": "https://images.unsplash.com/photo-1544717305-2782549b5136?auto=format&fit=crop&w=800&q=80"
    },
    {
        "key": "id_card",
        "title": "National ID Card",
        "description": "High-definition front and back National Identity Card with realistic chip, hologram and official formatting.\n⚡ Delivery: Fast digital delivery within 3 hours.",
        "price": 15.0,
        "is_leaf": True,
        "sort_order": 2,
        "sample_title": "National Identity Card Sample",
        "sample_desc": "Front & back high-definition ID Card sample with smart chip and optical security features.",
        "sample_image": "https://images.unsplash.com/photo-1589829545856-d10d557cf95f?auto=format&fit=crop&w=800&q=80"
    },
    {
        "key": "drivers_license",
        "title": "Driver's License",
        "description": "Official standard front & back Driver's License in high-definition resolution with barcodes.\n⚡ Delivery: Fast digital delivery within 3 hours.",
        "price": 15.0,
        "is_leaf": True,
        "sort_order": 3,
        "sample_title": "Driver's License Sample",
        "sample_desc": "Front & back official grade Driver's License sample with holographic overlay and magnetic strip.",
        "sample_image": "https://images.unsplash.com/photo-1557804506-669a67965ba0?auto=format&fit=crop&w=800&q=80"
    },
    {
        "key": "utility_bill",
        "title": "Utility Bill (Electricity Bill)",
        "description": "Genuine Electricity/Utility Bill or Bank Statement customized with your full address for proof of address verification.\n⚡ Delivery: Fast digital delivery within 3 hours.",
        "price": 10.0,
        "is_leaf": True,
        "sort_order": 4,
        "sample_title": "Utility Bill & Proof of Address Sample",
        "sample_desc": "Official Electricity / Utility statement with customized billing name and verified address format.",
        "sample_image": "https://images.unsplash.com/photo-1554224155-6726b3ff858f?auto=format&fit=crop&w=800&q=80"
    },
    {
        "key": "complete_pack",
        "title": "Complete Document Pack",
        "description": "All-in-one complete document suite (Passport + ID Card + Driver's License + Utility Bill). Available in Digital & Physical editions.",
        "price": 0.0,
        "is_leaf": False,
        "sort_order": 5,
        "subcategories": [
            {
                "key": "complete_pack_digital",
                "title": "Complete Pack (Digital Delivery)",
                "description": "All-in-one document suite (Passport + ID Card + Driver's License + Utility Bill) in ultra-high digital resolution.\n⚡ Delivery: Fast digital delivery within 3 hours.",
                "price": 45.0,
                "is_leaf": True,
                "sort_order": 1,
                "sample_title": "Complete Document Pack (Digital 4K)",
                "sample_desc": "Complete suite including Passport, ID Card, Driver's License and Utility statement. 3-Hour Digital Delivery.",
                "sample_image": "https://images.unsplash.com/photo-1450133064473-71024230f91b?auto=format&fit=crop&w=800&q=80"
            },
            {
                "key": "complete_pack_physical",
                "title": "Complete Pack (Physical Shipping)",
                "description": "Full premium printed physical document pack (Passport + ID Card + Driver's License + Utility Bill) with high-grade security features.\n📦 Worldwide Delivery: Tracked shipping worldwide within 10 to 20 business days to your doorstep.",
                "price": 200.0,
                "is_leaf": True,
                "sort_order": 2,
                "sample_title": "Complete Document Pack (Physical Shipping)",
                "sample_desc": "Hard-copy printed physical documents package with security seals. Worldwide tracked delivery in 10-20 business days.",
                "sample_image": "https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?auto=format&fit=crop&w=800&q=80"
            }
        ]
    }
]


async def seed_kyc_data():
    """
    Synchronizes the 5 core products, their exact 10 form fields,
    pricing, delivery times, and sample portfolio items.
    """
    print("[Seed Products] Initializing database connection...")
    await init_db()

    async with AsyncSessionLocal() as session:
        # 1. Fetch all existing categories
        all_cats_q = select(Category)
        all_cats = list((await session.execute(all_cats_q)).scalars().all())

        cat_by_title = {}
        for c in all_cats:
            t = c.get_title("en").strip()
            cat_by_title[t.lower()] = c

        # Helper to sync 10 form fields on a leaf category
        async def sync_form_fields(category_id: int):
            # Delete existing fields
            await session.execute(
                delete(CategoryFormField).where(CategoryFormField.category_id == category_id)
            )
            # Add the exact 10 fields
            for f in COMMON_FORM_FIELDS:
                session.add(CategoryFormField(
                    category_id=category_id,
                    field_key=f["field_key"],
                    labels=f["labels"],
                    field_type=f["field_type"],
                    options=None,
                    is_required=f["is_required"],
                    sort_order=f["sort_order"]
                ))

        # Helper to sync sample portfolio item
        async def sync_portfolio_sample(category_id: int, title: str, desc: str, img: str):
            q = select(PortfolioItem).where(PortfolioItem.category_id == category_id)
            existing_item = (await session.execute(q)).scalars().first()
            if existing_item:
                existing_item.title = title
                existing_item.description = desc
                existing_item.image_path = img
                existing_item.is_active = True
            else:
                session.add(PortfolioItem(
                    title=title,
                    description=desc,
                    image_path=img,
                    category_id=category_id,
                    sort_order=1,
                    is_active=True
                ))

        # 2. Iterate through specifications and create/update categories
        for spec in PRODUCTS_SPEC:
            title_en = spec["title"]
            cat = cat_by_title.get(title_en.lower())

            if not cat:
                cat = Category(
                    titles={"en": title_en},
                    descriptions={"en": spec["description"]},
                    price=spec["price"],
                    parent_id=None,
                    is_leaf=spec["is_leaf"],
                    sort_order=spec["sort_order"],
                    is_active=True
                )
                session.add(cat)
                await session.flush()
                print(f"[Seed Products] Created root category: {title_en} (Price: ${cat.price})")
            else:
                cat.titles = {"en": title_en}
                cat.descriptions = {"en": spec["description"]}
                cat.price = spec["price"]
                cat.is_leaf = spec["is_leaf"]
                cat.sort_order = spec["sort_order"]
                cat.is_active = True
                await session.flush()
                print(f"[Seed Products] Updated root category: {title_en} (Price: ${cat.price})")

            # If leaf, sync fields and portfolio
            if spec["is_leaf"]:
                await sync_form_fields(cat.id)
                await sync_portfolio_sample(
                    category_id=cat.id,
                    title=spec.get("sample_title", title_en),
                    desc=spec.get("sample_desc", spec["description"]),
                    img=spec.get("sample_image", "")
                )
            elif "subcategories" in spec:
                # Subcategories handling (e.g. Complete Pack Digital & Physical)
                sub_q = select(Category).where(Category.parent_id == cat.id)
                sub_cats = list((await session.execute(sub_q)).scalars().all())
                sub_by_title = {s.get_title("en").lower().strip(): s for s in sub_cats}

                for sub_spec in spec["subcategories"]:
                    sub_title = sub_spec["title"]
                    sub_cat = sub_by_title.get(sub_title.lower())

                    if not sub_cat:
                        sub_cat = Category(
                            titles={"en": sub_title},
                            descriptions={"en": sub_spec["description"]},
                            price=sub_spec["price"],
                            parent_id=cat.id,
                            is_leaf=True,
                            sort_order=sub_spec["sort_order"],
                            is_active=True
                        )
                        session.add(sub_cat)
                        await session.flush()
                        print(f"  [Seed Products] Created subcategory: {sub_title} (Price: ${sub_cat.price})")
                    else:
                        sub_cat.titles = {"en": sub_title}
                        sub_cat.descriptions = {"en": sub_spec["description"]}
                        sub_cat.price = sub_spec["price"]
                        sub_cat.is_leaf = True
                        sub_cat.sort_order = sub_spec["sort_order"]
                        sub_cat.is_active = True
                        await session.flush()
                        print(f"  [Seed Products] Updated subcategory: {sub_title} (Price: ${sub_cat.price})")

                    await sync_form_fields(sub_cat.id)
                    await sync_portfolio_sample(
                        category_id=sub_cat.id,
                        title=sub_spec.get("sample_title", sub_title),
                        desc=sub_spec.get("sample_desc", sub_spec["description"]),
                        img=sub_spec.get("sample_image", "")
                    )

        # Deactivate any old root categories that are not in the new 5 specs
        new_titles = {s["title"].lower().strip() for s in PRODUCTS_SPEC}
        for c in all_cats:
            if c.parent_id is None and c.get_title("en").lower().strip() not in new_titles and c.get_title("fa").lower().strip() not in new_titles:
                c.is_active = False

        await session.commit()
        print("[Seed Products] All 5 products, 10 fields, prices, and sample portfolios synced successfully!")


if __name__ == "__main__":
    asyncio.run(seed_kyc_data())
