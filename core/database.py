"""Database management module."""
import aiosqlite
from datetime import datetime
from typing import Optional
from loguru import logger

from core.config import Config


class Database:
    """Database manager for user data."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or Config.DATABASE_PATH
        self._initialized = False
    
    async def init(self) -> None:
        """Initialize database and create tables."""
        if self._initialized:
            return
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    telegram_nickname TEXT,
                    telegram_name TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            await db.commit()
        
        self._initialized = True
        logger.info(f"База данных инициализирована: {self.db_path}")
    
    async def register_user(
        self,
        telegram_id: int,
        telegram_nickname: Optional[str] = None,
        telegram_name: Optional[str] = None,
    ) -> None:
        """Register or update user in database."""
        await self.init()
        
        created_at = datetime.utcnow().isoformat()
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO users 
                (telegram_id, telegram_nickname, telegram_name, created_at)
                VALUES (?, ?, ?, ?)
            """, (telegram_id, telegram_nickname, telegram_name, created_at))
            await db.commit()
        
        logger.debug(f"Пользователь зарегистрирован: {telegram_id}")
    
    async def get_user(self, telegram_id: int) -> Optional[dict]:
        """Get user by telegram_id."""
        await self.init()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    
    async def get_all_users(self) -> list[dict]:
        """Get all registered users."""
        await self.init()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT telegram_id FROM users") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_all_user_ids(self) -> list[int]:
        """Get all user telegram IDs (for broadcast)."""
        users = await self.get_all_users()
        return [user["telegram_id"] for user in users]


# Глобальный экземпляр
db = Database()

