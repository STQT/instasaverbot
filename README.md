# Ахмедовлар оиласи — Instagram/Facebook Downloader Bot

Telegram бот, который автоматически скачивает Reels, Stories и посты с Instagram и Facebook при отправке ссылок в группу.

## Возможности

- Скачивает **Instagram Reels, Stories, посты**
- Скачивает **Facebook Reels, видео**
- Поддерживает **несколько ссылок** в одном сообщении
- Отправляет **медиа-группы** (альбомы)
- Работает в **группах, каналах и личных чатах**

## Установка

### 1. Клонируй репозиторий

```bash
cd axmedovsbot
```

### 2. Установи зависимости

```bash
pip install -r requirements.txt
```

> Также нужен `ffmpeg` для объединения видео+аудио:
> ```bash
> # macOS
> brew install ffmpeg
>
> # Ubuntu/Debian
> sudo apt install ffmpeg
> ```

### 3. Создай бота через @BotFather

1. Открой Telegram, найди `@BotFather`
2. Отправь `/newbot`, следуй инструкциям
3. Скопируй полученный токен

### 4. Настрой окружение

```bash
cp .env.example .env
```

Отредактируй `.env`:
```
BOT_TOKEN=123456:ABC-DEF...
```

### 5. (Необязательно) Добавь куки для приватного контента

Для скачивания приватных Stories и контента, требующего авторизации:

1. Войди в Instagram/Facebook в браузере
2. Установи расширение **"Get cookies.txt LOCALLY"** (Chrome/Firefox)
3. Экспортируй куки для `instagram.com` и `facebook.com` в файл `cookies.txt`
4. Убедись что в `.env` указан правильный путь: `COOKIES_FILE=cookies.txt`

### 6. Добавь бота в группу

1. Добавь бота в группу "Ахмедовлар оиласи"
2. Дай боту право **читать сообщения** (в настройках группы)

### 7. Запусти бота

```bash
python bot.py
```

## Как это работает

1. Кто-то отправляет в группу сообщение с Instagram/Facebook ссылкой
2. Бот автоматически определяет ссылку
3. Скачивает видео/фото через `yt-dlp`
4. Отправляет медиа-файл в ответ на исходное сообщение
5. Временные файлы автоматически удаляются

## Структура проекта

```
axmedovsbot/
├── bot.py           # Главный файл бота
├── downloader.py    # Логика скачивания через yt-dlp
├── requirements.txt # Python зависимости
├── .env.example     # Пример конфига
├── .env             # Твой конфиг (не коммитить!)
├── cookies.txt      # Куки браузера (не коммитить!)
└── downloads/       # Временная папка для файлов (создаётся автоматически)
```

## Поддерживаемые ссылки

### Instagram
- `https://www.instagram.com/reel/ABC123/`
- `https://www.instagram.com/p/ABC123/`
- `https://www.instagram.com/stories/username/123/`

### Facebook
- `https://www.facebook.com/watch/?v=123456`
- `https://www.facebook.com/share/r/ABC123/`
- `https://fb.watch/ABC123/`
- `https://www.facebook.com/username/videos/123456/`
