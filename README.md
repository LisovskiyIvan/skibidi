# Video Processing Pipeline with Vosk

Скрипт для обработки видео: разбивает на сегменты, распознает речь через Vosk, добавляет субтитры и конвертирует в 9:16 формат.

Проект разделён на три слоя:

- **core** — чистая бизнес-логика (`config`, `ffmpeg`, `transcribe`, `subtitles`, `pipeline`, `resources`, `progress`).
- **cli** — командная строка.
- **ui** — Tkinter GUI.

Все три слоя работают поверх одного и того же ядра `core`.

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
│   ├── config.py             # Конфигурация пайплайна
│   ├── resources.py          # Пути к ресурсам (dev / PyInstaller bundle)
│   ├── progress.py           # Протокол прогресса
│   ├── pipeline.py           # Оркестрация пайплайна
│   ├── ffmpeg.py             # FFmpeg/FFprobe обёртки
│   ├── transcribe.py         # Vosk + группировка слов
│   └── subtitles.py          # Генерация ASS
├── build_windows.py          # Скрипт сборки для Windows
├── requirements.txt          # Python зависимости
├── pyproject.toml            # Метаданные и точка входа video-processor
├── setup.sh                  # Setup Linux/macOS
├── .github/
│   └── workflows/
│       └── build-windows.yml # GitHub Actions workflow
├── assets/
│   └── oswald/              # Шрифты
└── vosk-model-small-ru-0.22/ # Модель Vosk
```

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
