from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.config import settings

# Engine configuration
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    # 1. Ensure all models are registered in Base.metadata
    import app.models  # noqa: F401

    # 2. Create any missing tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 3. Check and apply safe schema migrations using inspector (without failing transactions)
    try:
        async with engine.connect() as conn:
            def _check_and_migrate(sync_conn):
                from sqlalchemy import inspect
                inspector = inspect(sync_conn)
                tables = inspector.get_table_names()
                
                # Check users table columns
                if "users" in tables:
                    user_cols = [c["name"] for c in inspector.get_columns("users")]
                    if "is_language_selected" not in user_cols:
                        sync_conn.execute(text("ALTER TABLE users ADD COLUMN is_language_selected BOOLEAN DEFAULT 0"))
                        sync_conn.commit()
                    if "language_code" not in user_cols:
                        sync_conn.execute(text("ALTER TABLE users ADD COLUMN language_code VARCHAR(5) DEFAULT 'en'"))
                        sync_conn.commit()
                    if "last_lucky_spin" not in user_cols:
                        sync_conn.execute(text("ALTER TABLE users ADD COLUMN last_lucky_spin DATETIME NULL"))
                        sync_conn.commit()

            await conn.run_sync(_check_and_migrate)
    except Exception as e:
        print(f"[init_db warning] Column migration: {e}")

