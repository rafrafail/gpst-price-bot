"""AI statistics tracking module."""
import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from loguru import logger

from core.config import Config

# Максимальное количество записей в одном файле
MAX_RECORDS_PER_FILE = 10000


class AIStats:
    """Track AI request statistics in CSV format."""
    
    def __init__(self, stats_dir: Path = None):
        self.stats_dir = stats_dir or Config.LOGS_DIR
        self.stats_dir.mkdir(exist_ok=True)
        self.current_file = None
        self.current_record_count = 0
        self._ensure_csv_header()
    
    def _get_stats_file_path(self, part: int = 0) -> Path:
        """Get path to stats CSV file."""
        if part == 0:
            return self.stats_dir / "ai_stats.csv"
        return self.stats_dir / f"ai_stats_part{part}.csv"
    
    def _ensure_csv_header(self) -> None:
        """Ensure CSV file exists with header."""
        stats_file = self._get_stats_file_path()
        
        if not stats_file.exists():
            with open(stats_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp',
                    'user_id',
                    'username',
                    'model',
                    'tokens_in',
                    'tokens_out',
                    'tool',
                    'duration_s',
                    'cost_usd',
                    'prompt_preview'
                ])
            logger.info(f"Создан файл статистики: {stats_file}")
    
    def _get_current_file_path(self) -> Path:
        """Get current stats file path, creating new one if needed."""
        part = 0
        while True:
            file_path = self._get_stats_file_path(part)
            if not file_path.exists():
                # Создаем новый файл с заголовком
                self._ensure_csv_header()
                return file_path
            
            # Подсчитываем количество записей в файле
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                row_count = sum(1 for row in reader) - 1  # Минус заголовок
            
            if row_count < MAX_RECORDS_PER_FILE:
                return file_path
            
            part += 1
    
    def _mask_user_id(self, user_id: int) -> str:
        """Mask user ID for privacy."""
        user_str = str(user_id)
        if len(user_str) > 4:
            return user_str[:2] + "***" + user_str[-2:]
        return "***"
    
    async def record_request(
        self,
        user_id: int,
        username: Optional[str],
        model: str,
        tokens_in: int,
        tokens_out: int,
        tool: Optional[str],
        duration_s: float,
        cost_usd: Optional[float],
        prompt_preview: str,
    ) -> None:
        """
        Record AI request statistics.
        
        Args:
            user_id: Telegram user ID (will be masked)
            username: Telegram username
            model: OpenRouter model name
            tokens_in: Input tokens
            tokens_out: Output tokens
            tool: Tool/agent name (if used)
            duration_s: Request duration in seconds
            cost_usd: Calculated cost in USD
            prompt_preview: First 100 characters of prompt
        """
        try:
            file_path = self._get_current_file_path()
            
            # Маскируем user_id
            masked_user_id = self._mask_user_id(user_id)
            
            # Обрезаем prompt_preview до 100 символов
            prompt_preview = prompt_preview[:100] if prompt_preview else ""
            
            # Маскируем username если нужно
            if username:
                username = username[:20]  # Ограничиваем длину
            
            timestamp = datetime.utcnow().isoformat()
            
            # Записываем в CSV
            with open(file_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    masked_user_id,
                    username or "",
                    model,
                    tokens_in,
                    tokens_out,
                    tool or "",
                    f"{duration_s:.2f}",
                    f"{cost_usd:.6f}" if cost_usd else "",
                    prompt_preview
                ])
            
            if Config.DEBUG_MODE:
                logger.debug(
                    f"AI статистика записана: model={model} tool={tool} "
                    f"tokens={tokens_in}+{tokens_out} duration={duration_s:.2f}s"
                )
        
        except Exception as e:
            # Ошибки записи статистики не должны прерывать работу бота
            logger.warning(f"Ошибка при записи статистики AI: {e}")


# Глобальный экземпляр
ai_stats = AIStats()

