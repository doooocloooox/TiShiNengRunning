from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from config import settings
DATABASE_URL = settings.database_url
engine = create_async_engine(DATABASE_URL, echo=False, poolclass=NullPool, future=True)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autocommit=False, autoflush=False)
Base = declarative_base()

async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if DATABASE_URL.startswith('sqlite'):
            from security import protect_secret
            rows = (await conn.execute(text('SELECT id, password FROM tsn_account'))).all()
            for account_id, password in rows:
                protected = protect_secret(password or '')
                if protected != password:
                    await conn.execute(text('UPDATE tsn_account SET password = :password WHERE id = :account_id'), {'password': protected, 'account_id': account_id})

async def close_db():
    await engine.dispose()
