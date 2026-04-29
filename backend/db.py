"""asyncpg connection pool singleton."""
import os
import asyncpg

class PostgresDB:
    pool: asyncpg.Pool = None

    @classmethod
    async def connect(cls) -> None:
        import os
        from config import DATABASE_URL

        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")

        print("Using DATABASE_URL:", DATABASE_URL[:30], "...")

        cls.pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            ssl="require",
            min_size=2,
            max_size=10,
        )

    @classmethod
    async def disconnect(cls) -> None:
        if cls.pool:
            await cls.pool.close()


async def get_db() -> asyncpg.Pool:
    if PostgresDB.pool is None:
        await PostgresDB.connect()
    return PostgresDB.pool
