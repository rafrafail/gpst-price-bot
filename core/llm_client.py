"""OpenRouter LLM client module."""
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from loguru import logger

from core.config import Config, CriticalError
from core.ai_stats import ai_stats


class LLMClient:
    """Client for OpenRouter API with retries, timeouts, and logging."""
    
    def __init__(self):
        self.api_key = Config.OPENROUTER_API_KEY
        self.base_url = Config.OPENROUTER_BASE_URL
        self.config_path = Config.CONFIG_DIR / "openrouter_config.json"
        self.messages_dir = Config.OPENROUTER_MESSAGES_DIR
        self.messages_dir.mkdir(exist_ok=True)
        self._config_cache: Optional[Dict[str, Any]] = None
        self._load_config()
    
    def _load_config(self) -> None:
        """Load OpenRouter configuration from JSON file."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config_cache = json.load(f)
            
            # Валидация
            if "default" not in self._config_cache:
                raise CriticalError("openrouter_config.json должен содержать секцию 'default'")
            
            if "model" not in self._config_cache["default"]:
                raise CriticalError("openrouter_config.json: 'default' должен содержать 'model'")
            
            logger.info(f"Конфигурация OpenRouter загружена из {self.config_path}")
        
        except FileNotFoundError:
            raise CriticalError(f"Файл конфигурации не найден: {self.config_path}")
        except json.JSONDecodeError as e:
            raise CriticalError(f"Ошибка парсинга openrouter_config.json: {e}")
    
    def _get_agent_config(self, agent_name: str) -> Dict[str, Any]:
        """Get configuration for specific agent or use default."""
        if not self._config_cache:
            self._load_config()
        
        # Проверяем, есть ли конфигурация для агента
        if "agents" in self._config_cache and agent_name in self._config_cache["agents"]:
            agent_config = self._config_cache["agents"][agent_name].copy()
            # Мержим с default для полей, которых нет в agent_config
            default_config = self._config_cache["default"].copy()
            default_config.update(agent_config)
            return default_config
        
        # Используем default
        return self._config_cache["default"].copy()
    
    def _calculate_cost(
        self,
        model: str,
        tokens_in: int,
        tokens_out: int,
    ) -> Optional[float]:
        """Calculate request cost based on model pricing."""
        if not self._config_cache:
            return None
        
        model_costs = self._config_cache.get("model_costs", {})
        if model not in model_costs:
            return None
        
        costs = model_costs[model]
        input_cost = (tokens_in / 1000) * costs.get("input_per_1k", 0)
        output_cost = (tokens_out / 1000) * costs.get("output_per_1k", 0)
        
        return input_cost + output_cost
    
    def _save_message(
        self,
        agent_name: str,
        request_data: Dict[str, Any],
        response_data: Dict[str, Any],
    ) -> None:
        """Save request and response to file for audit."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dir_name = f"{agent_name}_{timestamp}"
        message_dir = self.messages_dir / dir_name
        message_dir.mkdir(exist_ok=True)
        
        # Сохраняем запрос
        request_file = message_dir / "request.json"
        with open(request_file, 'w', encoding='utf-8') as f:
            json.dump(request_data, f, ensure_ascii=False, indent=2)
        
        # Сохраняем ответ
        response_file = message_dir / "response.json"
        with open(response_file, 'w', encoding='utf-8') as f:
            json.dump(response_data, f, ensure_ascii=False, indent=2)
        
        if Config.DEBUG_MODE:
            logger.debug(f"Сообщение OpenRouter сохранено: {message_dir}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def request(
        self,
        prompt: str,
        agent_name: str = "default",
        system_prompt: Optional[str] = None,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
    ) -> str:
        """
        Make request to OpenRouter API.
        
        Args:
            prompt: User prompt
            agent_name: Agent name (planner, worker, critic, finalizer, etc.)
            system_prompt: Optional system prompt
            user_id: Telegram user ID (for statistics)
            username: Telegram username (for statistics)
        
        Returns:
            Response text from LLM
        """
        start_time = time.time()
        
        # Получаем конфигурацию агента
        agent_config = self._get_agent_config(agent_name)
        model = agent_config["model"]
        temperature = agent_config.get("temperature", 0.4)
        max_tokens = agent_config.get("max_tokens", 2048)
        top_p = agent_config.get("top_p", 0.9)
        
        # Формируем сообщения
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        # Подготавливаем запрос
        request_data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/your-repo",  # Опционально
            "X-Title": "Telegram Bot",  # Опционально
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=request_data,
                    headers=headers,
                )
                response.raise_for_status()
                response_data = response.json()
        
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP ошибка OpenRouter: {e.response.status_code} - {e.response.text}"
            logger.error(error_msg)
            raise Exception(error_msg)
        except httpx.TimeoutException as e:
            error_msg = f"Таймаут запроса к OpenRouter: {e}"
            logger.error(error_msg)
            raise
        except Exception as e:
            error_msg = f"Ошибка запроса к OpenRouter: {e}"
            logger.error(error_msg)
            raise
        
        # Извлекаем ответ
        if "choices" not in response_data or not response_data["choices"]:
            raise Exception("OpenRouter вернул пустой ответ")
        
        response_text = response_data["choices"][0]["message"]["content"]
        
        # Получаем статистику использования
        usage = response_data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        
        # Рассчитываем стоимость
        cost_usd = self._calculate_cost(model, tokens_in, tokens_out)
        
        # Сохраняем сообщение для аудита
        self._save_message(agent_name, request_data, response_data)
        
        # Записываем статистику
        duration_s = time.time() - start_time
        await ai_stats.record_request(
            user_id=user_id or 0,
            username=username,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tool=agent_name if agent_name != "default" else None,
            duration_s=duration_s,
            cost_usd=cost_usd,
            prompt_preview=prompt[:100],
        )
        
        if Config.DEBUG_MODE:
            logger.info(
                f"[AI] model={model} agent={agent_name} "
                f"tokens={tokens_in}+{tokens_out} duration={duration_s:.2f}s"
            )
        
        return response_text


# Глобальный экземпляр
llm_client = LLMClient()

