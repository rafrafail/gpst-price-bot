# Быстрый старт: свой бот за 5 минут

Это руководство проведёт вас от чистого комплекта до работающего бота с вашим оформлением.

## 1. Получите комплект

Скачайте или клонируйте экспортированный стартовый комплект (не исходный репозиторий с историей).

```bash
# Вариант А: если у вас есть доступ к репозиторию
git clone https://github.com/rafrafail/tg_bot_template.git my-bot
cd my-bot

# Вариант Б: распакуйте готовый архив tg-bot-template-<sha>-<date>.tar.gz
tar -xzf tg-bot-template-abc12345-20240115.tar.gz
cd tg-bot-template-abc12345-20240115
```

## 2. Создайте виртуальное окружение

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 3. Настройте конфигурацию

Скопируйте пример и отредактируйте:

```bash
cp config/template-v2.example .env
chmod 600 .env
# Откройте .env в редакторе и заполните:
# BOT_TOKEN=ваш_токен_от_BotFather
# ADMIN_IDS=ваш_числовой_ID (узнайте через @userinfobot)
# BOT_TITLE=Название вашего бота
# BOT_TIMEZONE=Europe/Moscow
```

## 4. (Опционально) Создайте публичный профиль

Если хотите настроить меню, приветствие и разделы без правки кода:

```bash
cp config/bot-profile.example.toml config/bot-profile.toml
# Отредактируйте config/bot-profile.toml под свой продукт
# Затем укажите путь в .env:
# BOT_PROFILE_PATH=config/bot-profile.toml
```

**Пример профиля для интернет-магазина:**
```toml
[bot]
title = "ShopBot"
welcome = "Добро пожаловать в ShopBot! Выберите раздел ниже."
help = "Здесь можно посмотреть каталог, проверить заказ и настроить уведомления."
support_url = "https://t.me/shop_support"

[example]
enabled = false

[menu]
order = ["catalog", "orders", "help", "preferences"]

[[sections]]
id = "catalog"
label = "🛍 Каталог"
text = "Наш каталог товаров: одежда, обувь, аксессуары.\nНовинки каждую неделю!"

[[sections]]
id = "orders"
label = "📦 Мои заказы"
text = "Здесь будут отображаться ваши заказы после авторизации."
```

## 5. Проверьте конфигурацию

```bash
.venv/bin/python main.py --check
# Должно вывести: "Конфигурация корректна. AI, Redis и PostgreSQL не требуются."
```

## 6. Запустите бота

```bash
.venv/bin/python main.py
```

Бот начнёт работать в режиме polling. Откройте его в Telegram и напишите `/start`.

## 7. Настройте для продакшена (опционально)

### Systemd сервис

Создайте `/etc/systemd/system/my-bot.service`:
```ini
[Unit]
Description=My Telegram Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/my-bot
ExecStart=/path/to/my-bot/.venv/bin/python main.py
Restart=on-failure
RestartSec=5
EnvironmentFile=/path/to/my-bot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now my-bot
```

### Self-hosted Telegram Bot API (опционально)

Для больших файлов и высокой нагрузки:
1. Настройте `infra/telegram-bot-api/` (см. README там)
2. В `.env` поставьте:
   ```
   TELEGRAM_TRANSPORT=self_hosted
   LOCAL_BOT_API_URL=http://127.0.0.1:8081
   ```
3. Перед переключением: `.venv/bin/python main.py --logout-cloud`

## Структура проекта (для разработки)

```
my-bot/
├── main.py                    # Точка входа
├── .env                       # Ваши секреты (НЕ коммитить!)
├── config/
│   ├── template-v2.example    # Пример .env
│   └── bot-profile.example.toml  # Пример профиля
├── bot_template/              # Ядро бота
│   ├── config.py              # Конфигурация
│   ├── profile.py             # Публичный профиль
│   ├── app.py                 # Меню и UI
│   ├── storage.py             # SQLite
│   └── ...                    # Остальные модули
├── tests/                     # Тесты
├── docs/                      # Документация
└── scripts/                   # Утилиты (export_template.py)
```

## Добавляем свою функцию

1. Создайте модуль в `bot_template/features/ваша_функция.py`
2. Добавьте экран в `app.py` через `Navigator.open`
3. Добавьте пункт в `bot-profile.toml` в `menu.order` и `sections`
4. Напишите тест по образцу `tests/test_profile_journey.py`

**Правила:**
- Не меняйте `navigation.py`, `delivery.py`, `storage.py` без нужды
- Один экран — одна задача
- Навигация не уничтожает данные
- Результат живёт отдельно от меню

## Полезные команды

```bash
# Проверка конфигурации
.venv/bin/python main.py --check

# Локальные проверки (lint, типы, тесты)
.venv/bin/python -m ruff check .
.venv/bin/python -m compileall -q bot_template tests main.py
.venv/bin/python -m pytest -q

# Бэкап (только на остановленном боте!)
.venv/bin/python main.py --backup /путь/к/backup.sqlite3

# Восстановление
.venv/bin/python main.py --restore /путь/к/backup.sqlite3 --restore-to /путь/к/new.sqlite3
```

## Документация

- `docs/UI-CONVENTIONS.md` — правила интерфейса
- `docs/V2-ACCEPTANCE.md` — чек-лист приёмки
- `docs/OPERATIONS.md` — бэкап/восстановление/эксплуатация
- `AGENTS.md` — правила для разработчиков

---

**Готово!** Ваш бот работает. Меню, тексты и разделы настраиваются в `config/bot-profile.toml` без перезапуска (кроме добавления новых разделов).