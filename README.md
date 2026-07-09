# Video Processing Pipeline with Vosk

Скрипт для обработки видео: разбивает на сегменты, распознает речь через Vosk, добавляет субтитры и конвертирует в 9:16 формат.

Проект разделён на три **концептуальных слоя** (все модули лежат в одном плоском
пакете `video_processor/`):

- **core** — чистая бизнес-логика (`config`, `ffmpeg`, `transcribe`, `subtitles`, `pipeline`, `youtube`, `youtube_config`, `resources`, `progress`, `errors`).
- **cli** — командная строка (`cli`, `__main__`).
- **ui** — Tkinter GUI (`ui`).

Все три слоя работают поверх одного и того же ядра `core`, а `PipelineConfig`
(один dataclass) и протокол `ProgressCallback` связывают их между собой.

## Быстрый старт

### Linux / macOS (разработка)

```bash
# Установка зависимостей
pip install -r requirements.txt

# Скачайте модель Vosk
wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
unzip vosk-model-small-ru-0.22.zip

# Убедитесь что ffmpeg установлен
ffmpeg -version

# Запуск (GUI mode)
python -m video_processor

# Запуск (CLI mode)
python -m video_processor -i video.mp4 -o ./output

# После установки пакета доступна команда video-processor
video-processor -i video.mp4 -o ./output
```

### Windows (exe файл)

1. Скачайте `VideoProcessor-Windows.zip` из [Releases](../../releases)
2. Распакуйте в любую папку
3. Запустите `VideoProcessor.exe`
4. Выберите видео и папку для сохранения через GUI

Или через командную строку:
```cmd
VideoProcessor.exe -i "C:\Videos\input.mp4" -o "C:\Output"
```

## Сборка exe для Windows

### Способ 1: GitHub Actions (рекомендуется)

1. Запушьте код на GitHub
2. Перейдите во вкладку **Actions**
3. Выберите **Build Windows Executable**
4. Нажмите **Run workflow**
5. Через несколько минут скачайте артефакт `VideoProcessor-Windows.zip`

Или создайте тег для автоматического релиза:
```bash
git tag v1.0.0
git push origin v1.0.0
```

### Способ 2: Локальная сборка на Windows

```bash
# На Windows машине
python build_windows.py
```

### Способ 3: Wine на Linux

```bash
# Установите Wine и Python для Windows
wine pip install pyinstaller vosk
python build_windows.py
```

## Структура проекта

```
.
├── video_processor/          # Пакет приложения
│   ├── __init__.py
│   ├── __main__.py          # Точка входа: python -m video_processor
│   ├── cli.py                # CLI
│   ├── ui.py                 # Tkinter GUI
│   ├── config.py             # Конфигурация пайплайна (PipelineConfig)
│   ├── resources.py          # Пути к ресурсам (dev / PyInstaller bundle)
│   ├── progress.py           # Протокол прогресса (ProgressCallback)
│   ├── errors.py             # PipelineError
│   ├── pipeline.py           # Оркестрация пайплайна
│   ├── ffmpeg.py             # FFmpeg/FFprobe обёртки
│   ├── transcribe.py         # Vosk + группировка слов
│   ├── youtube.py            # Загрузка видео на YouTube
│   ├── youtube_config.py     # Конфигурация загрузки на YouTube
│   └── subtitles.py          # Генерация ASS
├── tests/                    # pytest-тесты (чистые функции + пайплайн)
├── build_windows.py          # Скрипт сборки для Windows
├── requirements.txt          # Python зависимости (runtime)
├── pyproject.toml            # Метаданные, точка входа, конфиги ruff/mypy/pytest
├── setup.sh                  # Setup Linux/macOS
├── .github/
│   └── workflows/
│       ├── ci.yml            # lint (ruff) + typecheck (mypy) + tests (pytest)
│       └── build-windows.yml # Сборка Windows exe
├── assets/
│   └── oswald/              # Шрифты
└── vosk-model-small-ru-0.22/ # Модель Vosk
```

## Разработка

Дев-тулчейн (pytest, mypy, ruff) ставится опциональной группой зависимостей.
Для загрузки на YouTube нужна отдельная группа `[youtube]`:

```bash
pip install -e ".[dev,youtube]"
# или через uv: uv pip install -e ".[dev,youtube]"

ruff check .   # линтер
mypy           # статическая типизация ядра (Tkinter-GUI исключён из-за шума stubs)
pytest         # unit-тесты на чистые функции и оркестрацию
```

Все три проверки прогоняются в CI (`.github/workflows/ci.yml`) на каждый push/PR.

## Использование

### GUI режим (по умолчанию)

```bash
python -m video_processor
```

Откроется окно с выбором исходного видео, папки для результатов и настройками.

### CLI режим

```bash
# Полный CLI
python -m video_processor -i video.mp4 -o ./results

# Только input
python -m video_processor -i video.mp4

# Показать help
python -m video_processor --help
```

### Программное использование (core)

```python
from pathlib import Path
from video_processor.config import PipelineConfig
from video_processor.pipeline import run_pipeline
from video_processor.progress import Step

def on_progress(step: Step, current: int, total: int, message: str) -> None:
    print(f"[{current}/{total}] {step.value}: {message}")

config = PipelineConfig(
    input=Path("assets/videoplayback.mp4"),
    output_dir=Path("out"),
    seg_seconds=60,
    burn_subs=True,
)
run_pipeline(config, on_progress)
```

## Конфигурация

Основные настройки CLI:

| Аргумент | Описание | По умолчанию |
|----------|----------|--------------|
| `-i, --input` | Входное видео | — |
| `-o, --output` | Папка для результатов | `out` |
| `-m, --model` | Папка с моделью Vosk | `vosk-model-small-ru-0.22` |
| `--seg-seconds` | Длительность сегмента | `60` |
| `--burn-subs` / `--no-burn-subs` | Прожигать субтитры | `True` |
| `--font` | Название шрифта | `Oswald` |
| `--font-size` | Размер шрифта | `100` |
| `--pos-y` | Позиция по Y | `1500` |
| `--fade-in` | Появление, мс | `200` |
| `--fade-out` | Исчезновение, мс | `200` |
| `--mirror` / `--no-mirror` | Зеркальное отражение | `True` |
| `--speed` | Скорость (`1.0` или `0.95-1.05`) | `0.95-1.05` |
| `--seed` | Seed для рандомизированных эффектов (напр. `--speed`) | — |
| `--brightness` | Яркость (FFmpeg eq) | — |
| `--contrast` | Контраст (FFmpeg eq) | — |
| `--saturation` | Насыщенность (FFmpeg eq) | — |
| `--gamma` | Гамма (FFmpeg eq) | — |
| `--hue` | Оттенок (FFmpeg eq) | — |
| `--sharpness` | Лёгкая резкость | `False` |
| `--noise` | Шум (0 = выкл) | `0` |
| `--overlay-text` | Текстовый оверлей | — |
| `--bg-audio` | Фоновое аудио | — |
| `--bg-volume` | Громкость фона | `0.3` |
| `--upload` | Загрузить итоговые клипы на YouTube после обработки | `False` |
| `--upload-only` | Загрузить один файл или папку без запуска пайплайна | — |
| `--yt-credentials` | Путь к `client_secret.json` OAuth | `~/.config/video_processor/client_secret.json` |
| `--yt-token` | Путь к кешированному `token.json` | `~/.config/video_processor/token.json` |
| `--yt-title` | Шаблон названия видео (`{name}`, `{idx}`, `{total}`) | `{name}` |
| `--yt-description` | Описание видео | — |
| `--yt-tags` | Теги через запятую | — |
| `--yt-privacy` | Приватность: `private`, `unlisted`, `public` | `private` |
| `--yt-category` | ID категории YouTube | `22` |
| `--yt-notify` | Уведомлять подписчиков | `False` |

### Загрузка на YouTube

Автоматическая загрузка готовых клипов на YouTube работает через **YouTube Data API v3**
и OAuth 2.0. После первой авторизации (`client_secret.json`) токен сохраняется в
`token.json`, и все следующие запуски будут полностью автоматическими.

1. Установите зависимости для загрузки:

```bash
pip install -e ".[youtube]"
```

2. Создайте OAuth 2.0 Desktop credentials в [Google Cloud Console](https://console.cloud.google.com/)
   и скачайте `client_secret.json`.

3. Положите `client_secret.json` в `~/.config/video_processor/` (Linux/macOS) или
   `%APPDATA%\video_processor\` (Windows).

4. Запустите обработку с загрузкой:

```bash
python -m video_processor -i video.mp4 -o ./out --upload \
  --yt-title "Clip {idx:02d}" --yt-privacy private --yt-tags "shorts,automation"
```

Первый запрос откроет браузер для подтверждения доступа. После этого
`token.json` кешируется, и браузер больше не нужен.

Загрузить готовый файл без обработки:

```bash
python -m video_processor --upload-only ./out/final/clip_00_sub.mp4 \
  --yt-title "My video" --yt-privacy public
```

### Пример CLI с эффектами

```bash
python -m video_processor -i video.mp4 -o ./out \
  --mirror --speed 0.95-1.05 \
  --brightness 0.05 --contrast 1.05 --noise 5 \
  --bg-audio music.mp3 --bg-volume 0.3
```

### Воспроизводимость, resume и прогресс

- **`--seed N`** — фиксирует генератор случайных чисел. Все рандомизированные
  эффекты (например, случайная скорость из диапазона `0.95-1.05`) становятся
  детерминированными: повторный запуск на том же входе даёт тот же результат.
  Без `--seed` используется системная энтропия (поведение по умолчанию).
- **Resume** — если в `final/` уже лежит готовый клип (`clip_NN_sub.mp4`), сегмент
  пропускается. Прерванный запуск можно перезапустить без переработки целых
  сегментов: просто удалите только незавершённые клипы.
- **Прогресс** — FFmpeg пишет построчный прогресс в stderr; пайплайн парсит
  `out_time_ms` и сообщает процент выполнения внутри каждого сегмента (с шагом
  5%, чтобы не засорять вывод в CLI).

## Зависимости

### Для разработки (Linux/macOS)

- Python 3.9+
- ffmpeg (apt/brew)
- Модель Vosk (скачать отдельно)
- Шрифт Oswald (включен в репозиторий)

### Для Windows exe

Все зависимости включены в exe:
- ffmpeg.exe и ffprobe.exe
- Модель Vosk Russian
- Шрифт Oswald
- Python runtime

## Требования

### Linux
```bash
sudo apt-get install ffmpeg python3-tk
```

### macOS
```bash
brew install ffmpeg python-tk
```

### Windows
Не требуется (все включено в exe).

## Лицензия

MIT
