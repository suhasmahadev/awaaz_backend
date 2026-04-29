"""asyncpg connection pool singleton."""
import os
import asyncpg

class PostgresDB:
    pool: asyncpg.Pool = None

    @classmethod
    async def connect(cls) -> None:
        cls.pool = await asyncpg.create_pool(
            user=os.environ["PG_USER"],
            password=os.environ["PG_PASSWORD"],
            database=os.environ["PG_DB"],
            host=os.environ.get("PG_HOST", "localhost"),
            port=int(os.environ.get("PG_PORT", 5432)),
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
