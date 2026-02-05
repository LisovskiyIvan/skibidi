# Video Processing Pipeline with Vosk

Скрипт для обработки видео: разбивает на сегменты, распознает речь через Vosk, добавляет субтитры и конвертирует в 9:16 формат.

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
python pipeline_vosk.py

# Запуск (CLI mode)
python pipeline_vosk.py -i video.mp4 -o ./output
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
├── pipeline_vosk.py          # Основной скрипт
├── build_windows.py          # Скрипт сборки для Windows
├── requirements.txt          # Python зависимости
├── .github/
│   └── workflows/
│       └── build-windows.yml # GitHub Actions workflow
├── assets/
│   └── oswald/              # Шрифты (создается при сборке)
└── vosk-model-small-ru-0.22/ # Модель Vosk
```

## Использование

### GUI режим (по умолчанию)

```bash
python pipeline_vosk.py
```

Откроются два диалога:
1. Выбор исходного видео
2. Выбор папки для результатов

### CLI режим

```bash
# Полный CLI
python pipeline_vosk.py -i video.mp4 -o ./results

# Только input
python pipeline_vosk.py -i video.mp4

# Только output
python pipeline_vosk.py -o ./results

# Показать help
python pipeline_vosk.py --help
```

## Конфигурация

Основные настройки в начале файла `pipeline_vosk.py`:

```python
SEG_SECONDS = 60          # Длительность сегмента в секундах
BURN_SUBS = True          # Прожигать субтитры в видео
SUBTITLE_FONTSIZE = 100   # Размер шрифта
SUBTITLE_POS_Y = 1500     # Позиция по Y
```

## Зависимости

### Для разработки (Linux/macOS)

- Python 3.8+
- ffmpeg (установить через apt/brew)
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
