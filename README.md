# Telegram Bot AI Framework Template

Шаблон для создания телеграм-ботов с интеграцией ИИ через OpenRouter на основе Aiogram 3.22.

## Описание

Этот шаблон предоставляет готовую структуру для быстрого создания телеграм-ботов с поддержкой:
- Интеграции с OpenRouter API
- FSM (Finite State Machine) для интерактивных сценариев
- Логирования и статистики
- Рассылки сообщений
- Обработки Markdown
- И многого другого

## Требования

- Python >= 3.11
- Aiogram == 3.22
- Все зависимости указаны в `requirements.txt`

## Установка

1. Клонируйте репозиторий или используйте этот шаблон
2. Создайте виртуальное окружение:
```bash
python3.11 -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте файл `.env` на основе `.env.example`:
```bash
cp .env.example .env
```

5. Заполните обязательные переменные в `.env`:
- `BOT_TOKEN` — токен вашего Telegram бота
- `OPENROUTER_API_KEY` — API ключ OpenRouter
- `ADMIN_IDS` — ID администраторов (через запятую)

## Запуск

```bash
python main.py
```

## Структура проекта

```
tg_bot_template/
├── main.py                    # Точка входа
├── requirements.txt           # Зависимости
├── .env.example              # Пример конфигурации
├── core/                     # Основные модули
│   ├── config.py            # Загрузка конфигурации
│   ├── database.py          # Работа с БД
│   ├── llm_client.py        # Клиент OpenRouter
│   ├── ai_stats.py          # Статистика AI запросов
│   ├── broadcast.py         # Модуль рассылки
│   ├── message_splitter.py  # Разбиение длинных сообщений
│   ├── markdown_sanitizer.py # Очистка Markdown
│   └── logger.py            # Настройка логирования
├── features/                 # Фичи бота
│   └── admin/               # Пример фичи (админ-панель)
├── prompts/                  # Промпты в .md
├── config/                   # Конфигурация
│   └── openrouter_config.json
├── docs/                     # Документация
└── logs/                     # Логи (создается автоматически)
```

## Основные возможности

### LLM Client

Класс `LLMClient` в `core/llm_client.py` предоставляет единый интерфейс для работы с OpenRouter:
- Автоматические ретраи с экспоненциальной задержкой
- Таймауты и обработка ошибок
- Сохранение всех запросов/ответов для аудита
- Подсчет токенов и стоимости
- Загрузка конфигурации из `openrouter_config.json`

### FSM (Finite State Machine)

Все состояния следуют формату `FEAT__GROUP__STEP`:
- `FEAT` — слаг фичи (например, `DIGEST`, `SQL`, `ADMIN`)
- `GROUP` — логическая подгруппа (например, `CONFIG`, `INPUT`, `CONFIRM`)
- `STEP` — конкретный шаг (например, `DATE`, `FILTERS`, `SUBMIT`)

### Статистика AI

Все запросы к OpenRouter автоматически записываются в `/logs/ai_stats.csv` с информацией о:
- Модели и токенах
- Времени выполнения
- Стоимости запроса
- Превью промпта

### Рассылка

Модуль `/broadcast` позволяет администраторам рассылать сообщения всем пользователям бота.

## Конфигурация

### Переменные окружения (.env)

- `BOT_TOKEN` — токен Telegram бота (обязательно)
- `OPENROUTER_API_KEY` — API ключ OpenRouter (обязательно)
- `ADMIN_IDS` — ID администраторов через запятую
- `DEBUG_MODE` — режим отладки (1 = включен, 0 = выключен)
- `LOG_TO_FILE` — запись логов в файл (1 = включена, 0 = выключена)

### OpenRouter конфигурация

Настройки моделей и агентов находятся в `config/openrouter_config.json`. Можно настроить:
- Модели по умолчанию
- Параметры для каждого агента (planner, worker, critic, finalizer)
- Стоимость моделей для расчета расходов

## Разработка

### Добавление новой фичи

1. Создайте директорию в `features/`:
```bash
mkdir -p features/my_feature
```

2. Создайте `states.py` с FSM состояниями:
```python
from aiogram.fsm.state import StatesGroup, State

class MYFEAT_States(StatesGroup):
    CONFIG_DATE = State()  # MYFEAT__CONFIG__DATE
    CONFIG_FILTERS = State()  # MYFEAT__CONFIG__FILTERS
```

3. Создайте `handlers.py` с обработчиками:
```python
from aiogram import Router
from aiogram.filters import Command

router = Router()

@router.message(Command("mycommand"))
async def cmd_mycommand(message):
    await message.answer("Hello!")
```

4. Зарегистрируйте роутер в `main.py`

### Использование LLM Client

```python
from core.llm_client import llm_client

response = await llm_client.request(
    prompt="Ваш промпт",
    agent_name="worker",  # или "planner", "critic", "finalizer"
    user_id=message.from_user.id,
    username=message.from_user.username,
)
```

### Отправка длинных сообщений

```python
from core.message_splitter import send_long_markdown

await send_long_markdown(
    bot=bot,
    chat_id=message.chat.id,
    text="Очень длинный текст...",
    parse_mode="Markdown"
)
```

## Документация

Подробные правила и требования описаны в `Rules.md`.

## Лицензия

Этот шаблон предоставляется как есть для использования в ваших проектах.

