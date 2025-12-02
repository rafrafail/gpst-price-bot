# Архитектура проекта

Документ описывает принципы организации кода и структуру проекта телеграм-бота.

## Структура директорий

```
tg_bot_template/
├── core/                    # Инфраструктура и базовые модули
│   ├── config.py           # Загрузка конфигурации
│   ├── database.py         # Работа с БД
│   ├── logger.py           # Настройка логирования
│   ├── llm_client.py       # Клиент OpenRouter API
│   ├── markdown_v2.py      # Утилиты MarkdownV2
│   └── message_splitter.py # Разбиение длинных сообщений
│
├── features/               # Бизнес-логика и фичи бота
│   └── admin/              # Админ-панель
│       ├── handlers.py     # Обработчики команд
│       ├── states.py       # FSM состояния
│       └── broadcast.py    # Модуль рассылки
│
├── config/                 # Конфигурационные файлы
├── docs/                   # Документация
├── prompts/                # Промпты для AI
└── main.py                 # Точка входа
```

## Принципы разделения `/core` и `/features`

### `/core` — Инфраструктура

**Что сюда класть:**
- Модули, используемые несколькими фичами
- Инфраструктурные компоненты (БД, логи, конфиг)
- Утилиты без бизнес-логики
- Переиспользуемые компоненты

**Примеры:**
- ✅ `core/config.py` — используется всеми модулями
- ✅ `core/database.py` — работа с БД для всех фич
- ✅ `core/llm_client.py` — клиент AI, используется многими фичами
- ✅ `core/markdown_v2.py` — утилиты форматирования
- ✅ `core/message_splitter.py` — разбиение сообщений

**Правило:** Если модуль используется только одной фичей → он должен быть в `/features`, а не в `/core`.

### `/features` — Бизнес-логика

**Что сюда класть:**
- Конкретные функциональные модули
- Обработчики команд и callback'ов
- FSM состояния для фич
- Бизнес-логика, специфичная для фичи

**Примеры:**
- ✅ `features/admin/handlers.py` — обработчики админ-команд
- ✅ `features/admin/states.py` — FSM состояния админ-панели
- ✅ `features/admin/broadcast.py` — модуль рассылки (фича админа)

**Правило:** Каждая фича — отдельная папка в `/features` с изолированной логикой.

## Структура фичи

Каждая фича должна иметь следующую структуру:

```
features/
└── [feature_name]/
    ├── __init__.py         # Инициализация модуля
    ├── handlers.py         # Обработчики команд и callback'ов
    ├── states.py          # FSM состояния (если нужны)
    └── [другие модули]     # Специфичные для фичи модули
```

### Пример: Фича "SQL Query"

```
features/sql_query/
├── __init__.py
├── handlers.py            # Команда /sql, обработка запросов
├── states.py             # SQL__INPUT, SQL__CONFIRM
├── query_builder.py      # Построение SQL через AI
└── validators.py         # Валидация SQL
```

### Пример: Фича "Reports"

```
features/reports/
├── __init__.py
├── handlers.py           # Команда /report
├── states.py            # REPORTS__TYPE, REPORTS__DATE
├── generators/          # Генераторы разных типов отчетов
│   ├── daily.py
│   ├── weekly.py
│   └── custom.py
└── templates/           # Шаблоны отчетов
```

## Правила принятия решений

### 1. Куда поместить новый модуль?

**Вопрос:** Используется ли модуль только одной фичей?

- **Да** → `/features/[feature_name]/`
- **Нет** → `/core/` или `/core/shared/`

**Пример:**
- `broadcast.py` используется только админ-панелью → `/features/admin/broadcast.py` ✅
- `database.py` используется всеми фичами → `/core/database.py` ✅

### 2. Когда создавать общие модули?

Если несколько фич используют одну логику, создайте:

```
core/shared/              # Общие модули для фич
├── validators.py         # Валидация данных
├── formatters.py         # Форматирование
└── helpers.py            # Вспомогательные функции
```

Или:

```
features/shared/          # Общие компоненты фич
├── auth.py              # Авторизация
└── permissions.py       # Проверка прав
```

### 3. Инфраструктура → всегда в `/core`

- База данных
- Логирование
- Конфигурация
- Клиенты внешних API (если используются несколькими фичами)

## Подключение фич в main.py

Каждая фича экспортирует `router` для подключения:

```python
# main.py
from features.admin.handlers import router as admin_router
from features.admin.broadcast import router as broadcast_router
from features.reports.handlers import router as reports_router

# ...
dp.include_router(admin_router)
dp.include_router(broadcast_router)
dp.include_router(reports_router)
```

## FSM состояния

Все состояния следуют формату `FEAT__GROUP__STEP`:

- `FEAT` — слаг фичи (например, `ADMIN`, `REPORTS`, `SQL_QUERY`)
- `GROUP` — логическая подгруппа (например, `BROADCAST`, `CONFIG`, `INPUT`)
- `STEP` — конкретный шаг (например, `TEXT`, `PREVIEW`, `CONFIRM`)

**Пример:**
```python
class ADMIN_States(StatesGroup):
    BROADCAST_TEXT = State()      # ADMIN__BROADCAST__TEXT
    BROADCAST_PREVIEW = State()   # ADMIN__BROADCAST__PREVIEW
    BROADCAST_CONFIRM = State()   # ADMIN__BROADCAST__CONFIRM
```

## Итоговые рекомендации

1. **Одна фича = одна папка** в `/features`
2. **Если используется только одной фичей** → в `/features/[feature]/`
3. **Если используется 2+ фичами** → в `/core/shared/` или `/features/shared/`
4. **Инфраструктура** → всегда в `/core`
5. **Каждая фича изолирована** и может быть отключена удалением роутера
6. **Экспортируйте `router`** из каждого модуля фичи для подключения в `main.py`

## Примеры правильной организации

### ✅ Правильно

```
core/
├── database.py          # Используется всеми
├── config.py            # Используется всеми
└── llm_client.py       # Используется несколькими фичами

features/
├── admin/
│   ├── handlers.py      # Только для админа
│   ├── states.py        # Только для админа
│   └── broadcast.py     # Только для админа
└── reports/
    ├── handlers.py      # Только для отчетов
    └── generators.py    # Только для отчетов
```

### ❌ Неправильно

```
core/
├── broadcast.py         # ❌ Используется только админом
└── report_generator.py  # ❌ Используется только фичей reports

features/
└── admin/
    └── database.py     # ❌ БД используется всеми, должна быть в core
```

## Миграция существующего кода

При переносе модуля из `/core` в `/features`:

1. Переместить файл в нужную директорию фичи
2. Обновить импорты в `main.py` и других файлах
3. Убедиться, что модуль используется только этой фичей
4. Обновить документацию

**Пример:** `broadcast.py` был перенесен из `/core` в `/features/admin/`, так как используется только админ-панелью.

