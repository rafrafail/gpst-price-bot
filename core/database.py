"""Database management module."""
import aiosqlite
import json
from datetime import datetime
from typing import Optional, List, Dict
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
    
    async def get_all_users_with_info(self) -> list[dict]:
        """Get all registered users with full information."""
        await self.init()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT telegram_id, telegram_nickname, telegram_name FROM users"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_all_user_ids(self) -> list[int]:
        """Get all user telegram IDs (for broadcast)."""
        users = await self.get_all_users()
        return [user["telegram_id"] for user in users]
    
    async def init_scheduled_broadcasts_table(self) -> None:
        """Initialize scheduled_broadcasts table."""
        await self.init()
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_broadcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    photos TEXT,
                    videos TEXT,
                    buttons TEXT,
                    scheduled_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    sent_at TEXT,
                    error_message TEXT,
                    broadcast_id TEXT
                )
            """)
            await db.commit()
        
        logger.debug("Таблица scheduled_broadcasts инициализирована")
    
    async def create_scheduled_broadcast(
        self,
        text: str,
        media: List[Dict],
        buttons: List[Dict],
        scheduled_at: str,
        created_by: int,
        status: str = "pending"
    ) -> int:
        """Create a new scheduled broadcast and return its ID."""
        await self.init_scheduled_broadcasts_table()
        
        created_at = datetime.utcnow().isoformat()
        media_json = json.dumps(media) if media else None
        buttons_json = json.dumps(buttons) if buttons else None
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO scheduled_broadcasts 
                (text, photos, videos, buttons, scheduled_at, created_at, created_by, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (text, media_json, None, buttons_json, scheduled_at, created_at, created_by, status))
            await db.commit()
            post_id = cursor.lastrowid
        
        logger.info(f"Создан запланированный пост #{post_id} для админа {created_by}")
        return post_id
    
    async def get_scheduled_broadcasts(
        self,
        status: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """Get scheduled broadcasts, optionally filtered by status."""
        await self.init_scheduled_broadcasts_table()
        
        query = "SELECT * FROM scheduled_broadcasts"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status)
        
        query += " ORDER BY scheduled_at ASC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()
                result = []
                for row in rows:
                    post = dict(row)
                    # Парсим JSON поля
                    if post.get("photos"):
                        post["media"] = json.loads(post["photos"])
                    else:
                        post["media"] = []
                    if post.get("buttons"):
                        post["buttons"] = json.loads(post["buttons"])
                    else:
                        post["buttons"] = []
                    result.append(post)
                return result
    
    async def get_scheduled_broadcast_by_id(self, post_id: int) -> Optional[Dict]:
        """Get scheduled broadcast by ID."""
        await self.init_scheduled_broadcasts_table()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM scheduled_broadcasts WHERE id = ?",
                (post_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    post = dict(row)
                    # Парсим JSON поля
                    if post.get("photos"):
                        post["media"] = json.loads(post["photos"])
                    else:
                        post["media"] = []
                    if post.get("buttons"):
                        post["buttons"] = json.loads(post["buttons"])
                    else:
                        post["buttons"] = []
                    return post
                return None
    
    async def update_scheduled_broadcast(
        self,
        post_id: int,
        text: Optional[str] = None,
        media: Optional[List[Dict]] = None,
        buttons: Optional[List[Dict]] = None,
        status: Optional[str] = None,
        sent_at: Optional[str] = None,
        error_message: Optional[str] = None,
        broadcast_id: Optional[str] = None
    ) -> bool:
        """Update scheduled broadcast fields."""
        await self.init_scheduled_broadcasts_table()
        
        updates = []
        params = []
        
        if text is not None:
            updates.append("text = ?")
            params.append(text)
        
        if media is not None:
            updates.append("photos = ?")
            params.append(json.dumps(media))
        
        if buttons is not None:
            updates.append("buttons = ?")
            params.append(json.dumps(buttons))
        
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        
        if sent_at is not None:
            updates.append("sent_at = ?")
            params.append(sent_at)
        
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        
        if broadcast_id is not None:
            updates.append("broadcast_id = ?")
            params.append(broadcast_id)
        
        if not updates:
            return False
        
        params.append(post_id)
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE scheduled_broadcasts SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )
            await db.commit()
        
        logger.debug(f"Обновлен запланированный пост #{post_id}")
        return True
    
    async def cancel_scheduled_broadcast(self, post_id: int) -> bool:
        """Cancel scheduled broadcast by setting status to 'cancelled'."""
        return await self.update_scheduled_broadcast(post_id, status="cancelled")
    
    async def delete_scheduled_broadcast(self, post_id: int) -> bool:
        """Delete scheduled broadcast from database."""
        await self.init_scheduled_broadcasts_table()
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM scheduled_broadcasts WHERE id = ?",
                (post_id,)
            )
            await db.commit()
            return cursor.rowcount > 0


# Глобальный экземпляр
db = Database()

