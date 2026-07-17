# Video Transcription

Инструмент командной строки и Tkinter GUI для нарезки видео, распознавания речи,
генерации ASS-субтитров и преобразования клипов в формат 9:16. Основной движок
распознавания Vosk; faster-whisper, загрузка на YouTube и скачивание через yt-dlp
подключаются отдельными extras.

## Возможности

- параллельная обработка сегментов через FFmpeg;
- Vosk по умолчанию и optional faster-whisper (CPU/CUDA);
- прожиг субтитров, эффекты, фоновое аудио и выбор аппаратного encoder;
- optional YouTube Data API upload и yt-dlp download;
- CLI и GUI поверх одного pipeline;
- безопасная публикация результата через временный `.part` файл;
- resume только после проверки manifest, fingerprint настроек и видеопотока.

## Требования

- Python 3.9-3.14;
- [uv](https://docs.astral.sh/uv/);
- `ffmpeg` и `ffprobe` в `PATH`;
- Tkinter из системного Python-пакета для GUI;
- каталог `vosk-model-small-ru-0.22` для Vosk.

Linux обычно требует `ffmpeg` и `python3-tk`; macOS с Homebrew - `ffmpeg` и
`python-tk`. Extra `gui` устанавливает optional integrations, показанные в GUI
(Whisper, upload и download), но Tkinter не распространяется через PyPI и этот
extra не заменяет системный пакет Tk.

## Установка

Детерминированная установка из `uv.lock`:

```bash
uv sync --locked
```

Нужные функции включаются явно:

```bash
uv sync --locked --extra youtube     # YouTube upload
uv sync --locked --extra download    # yt-dlp download
uv sync --locked --extra stt         # faster-whisper
uv sync --locked --extra stt --extra stt-cuda  # large NVIDIA CUDA runtime
uv sync --locked --extra gui         # all optional GUI integrations
uv sync --locked --extra dev         # pytest, ruff, mypy
```

Для полной среды разработки на Linux/macOS можно выполнить `./setup.sh`. Скрипт
проверяет `uv`, FFmpeg, FFprobe и Tkinter, затем синхронизирует locked extras; он
не вызывает bare `pip` и не скачивает непроверенные assets.

## Запуск

GUI:

```bash
uv run video-processor
```

CLI:

```bash
uv run video-processor -i video.mp4 -o ./out
uv run python -m video_processor --help
```

Примеры optional функций:

```bash
uv run video-processor --download https://youtu.be/VIDEO_ID -o ./downloads

uv run video-processor -i video.mp4 -o ./out --upload \
  --yt-title "Clip {idx:02d}" --yt-privacy private

uv run video-processor -i video.mp4 -o ./out \
  --stt-engine whisper --whisper-model small --whisper-device auto
```

YouTube upload требует OAuth Desktop credentials. По умолчанию credentials и
token находятся в `~/.config/video_processor/` (Linux/macOS) или
`%APPDATA%\video_processor\` (Windows). Upload использует private visibility,
если пользователь явно не выбрал другое значение.

## Resume, отмена и cleanup

- Resume не доверяет одному наличию `final/clip_*.mp4`. Pipeline сверяет версию
  manifest, fingerprint входа и output-affecting настроек, размер/mtime файла и
  результат `ffprobe`. Изменение входа или настроек инвалидирует старый resume.
- Финальный файл заменяется атомарно только после успешного render и `ffprobe`;
  поврежденный или отмененный `.part` удаляется, а прежний финальный файл
  сохраняется.
- GUI cancellation кооперативная. Download/upload останавливаются в своих
  hooks, а активные FFmpeg/ffprobe процессы получают завершение через общий
  cancellation event; после короткого grace period зависший процесс убивается.
- После успешного сегмента WAV и служебный segment-файл удаляются, если
  `keep_intermediates` выключен. ASS-файлы и готовые клипы сохраняются. Временные
  каталоги фильтров и `.part` файлы очищаются даже при ошибке.
- `--seed N` делает рандомизированные эффекты воспроизводимыми.

## Разработка и CI

```bash
uv sync --locked --extra dev
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

CI проверяет форматирование, lint, strict mypy, pytest на Python 3.9-3.14, затем
строит wheel и устанавливает его в чистое окружение. `video_processor/py.typed`
публикуется в wheel как PEP 561 marker.

## Windows onedir

Release artifact - это каталог, а не одиночный exe:

```text
VideoProcessor/
├── VideoProcessor.exe
└── _internal/
    ├── ffmpeg.exe
    ├── ffprobe.exe
    ├── vosk-model-small-ru-0.22/ ...
    └── assets/oswald/ ...
```

Переносить и распаковывать нужно весь каталог. Workflow публикует
`VideoProcessor-Windows.zip` и `VideoProcessor-Windows.zip.sha256`, а Actions
artifact дополнительно содержит исходный onedir-каталог.

### Локальная сборка

`VideoProcessor.spec` использует PyInstaller 6 `EXE(exclude_binaries=True)` и
`COLLECT`. `build_windows.py` - единственный код подготовки assets для локальной
сборки и GitHub Actions. Скрипт никогда не создает пустой font fallback.

FFmpeg и Oswald должны задаваться immutable/versioned URL и известным SHA-256:

```powershell
$env:VIDEO_PROCESSOR_FFMPEG_URL = "https://example.invalid/ffmpeg-VERSION.zip"
$env:VIDEO_PROCESSOR_FFMPEG_SHA256 = "64-lowercase-hex-characters"
$env:VIDEO_PROCESSOR_OSWALD_URL = "https://github.com/googlefonts/OswaldFont/archive/COMMIT.zip"
$env:VIDEO_PROCESSOR_OSWALD_SHA256 = "64-lowercase-hex-characters"

uv sync --locked --extra windows
uv run --frozen python build_windows.py
```

Подставьте реальные upstream URL и независимо проверенные hashes; значения в
примере намеренно не являются рабочим manifest. Архив кешируется только после
успешной SHA-256 проверки. Tracked Vosk model берется из checkout. Если model
отсутствует, script также требует `VIDEO_PROCESSOR_VOSK_MODEL_SHA256` и
опционально принимает `VIDEO_PROCESSOR_VOSK_MODEL_URL`.

Результат: `dist_windows/VideoProcessor/`.

### GitHub Actions

Workflow запускается вручную и на тегах `v*`. Для tag build заранее задайте
repository variables:

- `WINDOWS_FFMPEG_URL` и `WINDOWS_FFMPEG_SHA256`;
- `WINDOWS_OSWALD_URL` и `WINDOWS_OSWALD_SHA256`.

При ручном запуске те же значения можно передать workflow inputs. Build job
имеет только `contents: read`; отдельный tag-only release job получает
`contents: write`.

```bash
git tag v0.1.0
git push origin v0.1.0
```

## Модель Vosk и история Git

Существующие tracked файлы `vosk-model-small-ru-0.22/` намеренно не удаляются.
Удаление больших blobs из прежних commits не является обычным cleanup: это
отдельная явная операция переписывания Git history, требующая согласования с
всеми клонами и force-push. Текущая настройка packaging историю не меняет.

Официальный каталог Vosk указывает для `vosk-model-small-ru-0.22` лицензию
Apache 2.0. Ее текст распространяется как `VOSK_MODEL_LICENSE`, источник и
остальные notices перечислены в `THIRD_PARTY_NOTICES`.

## Лицензия

Код проекта распространяется по MIT License, см. `LICENSE`. Third-party
компоненты имеют собственные условия, см. `THIRD_PARTY_NOTICES`.
