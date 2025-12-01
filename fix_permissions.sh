#!/bin/bash
# Скрипт для исправления прав доступа

echo "Исправление прав доступа для папки tg_bot_template..."
echo "Требуется пароль sudo:"

cd /home/user/DevProjects

# Изменяем владельца всех файлов на user:user
sudo chown -R user:user tg_bot_template

# Даем права на запись владельцу
sudo chmod -R u+w tg_bot_template

echo ""
echo "✓ Права доступа исправлены!"
echo ""
echo "Проверка:"
ls -la tg_bot_template | head -5

