# Refactoring Plan — video_processor

> Обратная совместимость **не требуется**. Редизайн с нуля ради качества кода,
> типобезопасности и удобства сопровождения.

---

## Цели

1. **Устранить баги** (незакрытая кавычка в drawtext)
2. **Убрать дублирование** (as_dict, upload paths, error handling, optional-deps паттерн, тестовые фабрики)
3. **Повысить типобезопасность** (Enums вместо строк, строгие типы)
4. **Сократить монолитные модули** (cli.py 523 строк, ui.py 567 строк, config.py 34 поля)
5. **Привести к best practices** (PEP 561, dataclasses.asdict, named constants, py.typed)

## Принципы

- Один файл = одна ответственность
- Конфиги — вложенные dataclass'ы, а не плоский суп из 40 полей
- Строковые литералы для enum-like значений → настоящие `Enum`
- Приватные функции, используемые в тестах → публичные (или через `__all__`)
- Никаких deprecated-швов: чистый разрыв старого API

---

## Целевая архитектура

```
video_processor/
├── __init__.py                # public API: PipelineConfig, run_pipeline, Step, ...
├── __main__.py                # точка входа (без изменений)
├── py.typed                   # НОВЫЙ: PEP 561 marker
├── constants.py               # НОВЫЙ: OUTPUT_WIDTH, OUTPUT_HEIGHT, WAV_* и т.д.
├── errors.py                  # PipelineError + YouTubeUploadError + YouTubeDownloadError
├── progress.py                # Step enum, ProgressCallback protocol (без мёртвого кода)
├── resources.py               # path helpers (без изменений по сути)
├── env_loader.py              # .env loading (без изменений)
│
├── enums.py                   # НОВЫЙ: STTEngine, VideoEncoder, HwAccel
├── hwaccel.py                 # детектирование (использует enums)
│
├── config.py                  # ПЕРЕРАБОТАН: вложенные dataclass'ы
│                              #   PipelineConfig(STTConfig, SubtitleConfig, EditConfig, EncodingConfig)
│
├── transcribe.py              # SpeechToText protocol, WordInfo, Cue, grouping (без изменений)
├── subtitles.py               # ASS generation (использует constants)
├── ffmpeg.py                  # ПЕРЕРАБОТАН: чёткое разделение filters / commands / runner
├── pipeline.py                # orchestration (практически без изменений)
├── paths.py                   # НОВЫЙ: collect_upload_paths() — общий для cli + ui
│
├── stt/                       # НОВЫЙ подпакет
│   ├── __init__.py            #   реэкспорт VoskEngine, WhisperEngine
│   ├── vosk.py                #   (бывший stt_vosk.py)
│   └── whisper.py             #   (бывший stt_whisper.py)
│
├── youtube/                   # НОВЫЙ подпакет
│   ├── __init__.py            #   реэкспорт upload_to_youtube, download_from_youtube, конфиги
│   ├── upload.py              #   (бывший youtube.py + youtube_config.py слиты воедино)
│   └── download.py            #   (бывший youtube_download.py + youtube_download_config.py слиты)
│
├── cli/                       # НОВЫЙ подпакет (бывший monolithic cli.py)
│   ├── __init__.py            #   main(), run_cli()
│   ├── parser.py              #   build_parser() разбит на _add_*_args()
│   └── builders.py            #   config_from_args(), youtube_config_from_args(), ...
│
└── ui/                        # НОВЫЙ подпакет (бывший monolithic ui.py)
    ├── __init__.py            #   run_gui()
    ├── app.py                 #   Application shell (notebook + Run + прогресс)
    ├── tab_process.py         #   ProcessTab + _make_config()
    ├── tab_upload.py          #   UploadTab + _make_yt_config()
    └── tab_download.py        #   DownloadTab + _make_download_config()
```

**Итог**: 20 плоских файлов → структурированное дерево с чёткими границами.

---

## Phase 0 — Safety Net

> Запускается **первым**, чтобы каждое последующее изменение было проверяемым.

### 0.1 Создать `.github/workflows/ci.yml`

README:135 обещает CI с ruff + mypy + pytest, но файла нет.

```yaml
name: CI
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: mypy
      - run: pytest
```

### 0.2 Зафиксировать baseline

```bash
ruff check .   # текущее состояние — green
mypy           # текущее состояние — green
pytest         # текущее состояние — green
```

---

## Phase 1 — Critical Fixes

### 1.1 Исправить баг drawtext (незакрытая кавычка)

**Файл**: `video_processor/ffmpeg.py:192-196`

Текущий код генерирует `drawtext=text'my_text:x=...` — открывающая `'` есть,
закрывающей нет. Весь хвост уходит в значение `text=`, фильтр сломан.

```python
# ДО
filters.append(
    "drawtext=text='"
    f"{text}"
    ":x=(w-text_w)/2:y=h-text_h-50:fontsize=24:fontcolor=white"
)

# ПОСЛЕ
filters.append(
    f"drawtext=text='{text}':x=(w-text_w)/2:y=h-text_h-50"
    f":fontsize=24:fontcolor=white"
)
```

### 1.2 Удалить `requirements.txt`

`requirements.txt` содержит 5 зависимостей вперемешку и не соответствует ни одной
optional-группе из `pyproject.toml`.

- **Удалить**: `requirements.txt`
- **Обновить**: `setup.sh:26` → `pip install -e ".[youtube,download,stt]"`
- **Обновить**: `README.md:21` → заменить `pip install -r requirements.txt`

### 1.3 Устранить дублирование PyInstaller spec

Spec-файл дублирован в `build_windows.py:167-227` (inline f-string) и
`.github/workflows/build-windows.yml:65-118` (PowerShell heredoc).

- **Создать**: `VideoProcessor.spec` — единый источник правды
- **`build_windows.py`**: убрать `create_spec_file()`, запускать PyInstaller с `.spec`
- **`build-windows.yml`**: убрать step "Create PyInstaller spec", запускать с `.spec`

---

## Phase 2 — DRY: устранение дублирования

### 2.1 Удалить `as_dict()`, использовать `dataclasses.asdict()` в тестах

`as_dict()` определён в трёх датаклассах, но используется **только в тестах**.
В продакшен-коде — нигде.

- **Удалить**: `config.py:80-118`, `youtube_config.py:47-61`, `youtube_download_config.py:37-45`
- **Обновить тесты**: `test_config.py:21`, `test_youtube.py:38`, `test_youtube_download.py:27`

```python
# В тестах вместо cfg.as_dict():
from dataclasses import asdict
d = asdict(cfg)
# Path→str конверсия при необходимости:
# {k: str(v) if isinstance(v, Path) else v for k, v in d.items()}
```

### 2.2 Вынести `collect_upload_paths()` в `paths.py`

Дублирование: `cli.py:412-423` (функция) и `ui.py:540-545` (инлайн-копия).

- **Создать**: `video_processor/paths.py`

```python
from pathlib import Path
from .config import PipelineConfig

def collect_upload_paths(config: PipelineConfig) -> list[Path]:
    """Собрать финальные клипы из output_dir/final."""
    final_dir = config.output_dir / "final"
    if not final_dir.exists():
        return []
    if config.burn_subs:
        return sorted(final_dir.glob("clip_*_sub.mp4"))
    clips = sorted(final_dir.glob("clip_*.mp4"))
    return [p for p in clips if not p.name.endswith("_sub.mp4")]
```

- **Обновить**: `cli.py:412` → `from .paths import collect_upload_paths`
- **Обновить**: `ui.py:540-545` → `from .paths import collect_upload_paths`

### 2.3 Обобщить try/except в cli.py

Три идентичных блока в `cli.py:460-467`, `482-489`, `508-513`:

```python
except PipelineError as exc:
    print(f"Error: {exc}", file=sys.stderr)
    return 1
except Exception as exc:
    print(f"Unexpected error: {exc}", file=sys.stderr)
    return 1
```

- **Создать** хелпер:

```python
def _run_or_report(action: Callable[[], T]) -> T | int:
    """Выполнить action, вернуть результат или код ошибки 1."""
    try:
        return action()
    except PipelineError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1
```

- Применить в трёх местах `run_cli()`.

### 2.4 Обобщить optional-deps паттерн

`youtube.py:19-55` и `youtube_download.py:19-39` имеют идентичный паттерн:
runtime-holder класс + try/import + `_ensure_deps()`.

- **Создать** `video_processor/_optional_deps.py`:

```python
def ensure_optional_dep(available: bool, dep_name: str, install_hint: str) -> None:
    if not available:
        raise PipelineError(
            f"{dep_name} is not installed. Install with: {install_hint}"
        )
```

- Или вынести общую логику lazy-import в типобезопасный helper.

### 2.5 Общая фабрика тестового конфига → `conftest.py`

Четыре тестовых файла имеют идентичную `_cfg()` / `_config()`:

| Файл | Функция | Строка |
|---|---|---|
| `tests/test_stt.py` | `_cfg(**overrides)` | 18 |
| `tests/test_pipeline.py` | `_cfg(input, out, **overrides)` | 16 |
| `tests/test_ffmpeg.py` | `_config(**overrides)` | 18 |
| `tests/test_subtitles.py` | `_config(**overrides)` | 16 |

- **Создать**: `tests/conftest.py`

```python
import pytest
from video_processor.config import PipelineConfig

@pytest.fixture
def make_config():
    def _factory(**overrides) -> PipelineConfig:
        base = {"input": Path("dummy.mp4")}
        base.update(overrides)
        return PipelineConfig(**base)
    return _factory
```

- Удалить локальные `_cfg` / `_config` из тестов, использовать фикстуру.

---

## Phase 3 — Type Safety: Enums

### 3.1 Создать `enums.py`

```python
import enum

class STTEngine(enum.Enum):
    VOSK = "vosk"
    WHISPER = "whisper"

class VideoEncoder(enum.Enum):
    LIBX264 = "libx264"
    NVENC = "h264_nvenc"
    QSV = "h264_qsv"
    AMF = "h264_amf"
    VIDEOTOOLBOX = "h264_videotoolbox"

class HwAccel(enum.Enum):
    CUDA = "cuda"
    QSV = "qsv"
    D3D11VA = "d3d11va"
    VIDEOTOOLBOX = "videotoolbox"
    NONE = "none"
    AUTO = "auto"
```

### 3.2 Интегрировать enums в config

- **`config.py`**: `stt_engine: STTEngine`, `hwaccel: HwAccel`, `video_encoder: VideoEncoder`
- **`cli.py`**: argparse конвертер `type=STTEngine`, `choices` из enum members
- **`hwaccel.py`**: заменить строковые сравнения на enum-сопоставление
- **`transcribe.py:78-88`**: `if engine is STTEngine.VOSK:` вместо `== "vosk"`

```python
# argparse helper для enum
def _enum_arg(enum_cls):
    def _parse(value: str):
        return enum_cls(value)
    return _parse

parser.add_argument("--stt-engine", type=_enum_arg(STTEngine),
                    default=STTEngine.VOSK)
```

### 3.3 Сделать `_default_workers` публичным

`config.py:17` — `def _default_workers()` импортируется в `cli.py:9` с подчёркиванием.

- Переименовать → `default_workers()` (убрать `_`)

---

## Phase 4 — Распиливание монолитных модулей

### 4.1 `cli.py` (523 строки) → пакет `cli/`

```
cli/
├── __init__.py    # main(), run_cli() — диспетчеризация режимов
├── parser.py      # build_parser() разбит на подфункции
└── builders.py    # config_from_args(), youtube_config_from_args(),
                   #   youtube_download_config_from_args()
```

**`parser.py`** — разбить `build_parser()` на:

```python
def build_parser() -> ArgumentParser:
    parser = ArgumentParser(...)
    _add_io_args(parser)          # -i, -o, -m, --seg-seconds, --burn-subs
    _add_stt_args(parser)         # --stt-engine, --language, --whisper-*
    _add_subtitle_args(parser)    # --font, --font-size, --pos-y, --fade-*
    _add_editing_args(parser)     # --mirror, --speed, --brightness, ...
    _add_encoder_args(parser)     # --hwaccel, --video-encoder, --crf, ...
    _add_youtube_args(parser)     # --upload, --upload-only, --yt-*
    _add_download_args(parser)    # --download, --dl-format, --dl-template
    return parser
```

**`builders.py`** — перенос `config_from_args()`, `youtube_config_from_args()`,
`youtube_download_config_from_args()` без изменений логики.

**`__init__.py`** — `main()` и `run_cli()`, импорт из `parser` и `builders`.

### 4.2 `ui.py` (567 строк) → пакет `ui/`

```
ui/
├── __init__.py        # run_gui()
├── app.py             # class Application — shell (notebook + Run + прогресс)
├── tab_process.py     # class ProcessTab(ttk.Frame)
├── tab_upload.py      # class UploadTab(ttk.Frame)
└── tab_download.py    # class DownloadTab(ttk.Frame)
```

Каждый таб — самостоятельный класс `ttk.Frame`:

```python
# tab_process.py
class ProcessTab(ttk.Frame):
    def __init__(self, parent, padding):
        super().__init__(parent, padding=10)
        self._build_widgets(padding)

    def _build_widgets(self, padding): ...

    def make_config(self) -> PipelineConfig: ...

    @property
    def input_path(self) -> str: ...
```

`app.py` композирует табы:

```python
class Application:
    def __init__(self, root):
        ...
        self.process_tab = ProcessTab(notebook, padding)
        notebook.add(self.process_tab, text="Process")
        self.upload_tab = UploadTab(notebook, padding)
        notebook.add(self.upload_tab, text="Upload")
        ...
```

### 4.3 `config.py` → вложенные dataclass'ы

Текущий `PipelineConfig` — 34 плоских поля, смешивающих STT, монтаж, кодирование.

**Новый дизайн:**

```python
@dataclass
class STTConfig:
    engine: STTEngine = STTEngine.VOSK
    language: str | None = None
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_compute_type: str | None = None

@dataclass
class SubtitleConfig:
    burn: bool = True
    font: str = field(default_factory=get_default_font_name)
    font_path: Path | None = field(default_factory=get_default_font_path)
    fontsize: int = 100
    pos_y: int = 1500
    fade_in_ms: int = 200
    fade_out_ms: int = 200

@dataclass
class EditConfig:
    mirror: bool = True
    speed: str = "0.95-1.05"
    seed: int | None = None
    brightness: float | None = None
    contrast: float | None = None
    saturation: float | None = None
    gamma: float | None = None
    hue: float | None = None
    sharpness: bool = False
    noise: int = 0
    overlay_text: str | None = None
    background_audio: Path | None = None
    background_audio_volume: float = 0.3

@dataclass
class EncodingConfig:
    hwaccel: HwAccel = HwAccel.AUTO
    encoder: VideoEncoder = VideoEncoder.LIBX264  # или AUTO
    preset: str | None = None
    crf: int = 23

@dataclass
class PipelineConfig:
    input: Path
    output_dir: Path = Path("out")
    model_dir: Path = field(default_factory=get_default_model_dir)
    seg_seconds: int = 60
    workers: int = field(default_factory=default_workers)
    ffmpeg: Path | str = field(default_factory=get_ffmpeg_path)
    ffprobe: Path | str = field(default_factory=get_ffprobe_path)
    stt: STTConfig = field(default_factory=STTConfig)
    subtitles: SubtitleConfig = field(default_factory=SubtitleConfig)
    editing: EditConfig = field(default_factory=EditConfig)
    encoding: EncodingConfig = field(default_factory=EncodingConfig)
```

**Каскадные изменения** (обновить во всех consumers):

| Файл | Было | Станет |
|---|---|---|
| `pipeline.py:173` | `config.stt_engine == "vosk"` | `config.stt.engine is STTEngine.VOSK` |
| `pipeline.py:174` | `config.model_dir` | `config.model_dir` (без изменений) |
| `ffmpeg.py:158` | `config.mirror` | `config.editing.mirror` |
| `ffmpeg.py:169` | `config.brightness` | `config.editing.brightness` |
| `ffmpeg.py:217` | `config.video_encoder` | `config.encoding.encoder` |
| `subtitles.py:41` | `config.subtitle_font` | `config.subtitles.font` |
| `transcribe.py:79-86` | `config.stt_engine` | `config.stt.engine` |
| `cli.py` builders | `burn_subs=args.burn_subs` | `subtitles=SubtitleConfig(burn=args.burn_subs, ...)` |
| `ui.py` _make_config | плоские поля | вложенные |

### 4.4 Подпакеты `stt/` и `youtube/`

**stt/** — слить `stt_vosk.py` + `stt_whisper.py`:

```
stt/
├── __init__.py    # реэкспорт VoskEngine, WhisperEngine
├── vosk.py        # бывший stt_vosk.py
└── whisper.py     # бывший stt_whisper.py
```

**youtube/** — слить конфиги с логикой (конфиг маленький, живёт рядом с потребителем):

```
youtube/
├── __init__.py    # реэкспорт upload_to_youtube, download_from_youtube,
│                  #   YouTubeUploadConfig, YouTubeDownloadConfig
├── upload.py      # бывший youtube.py + youtube_config.py (слиты)
└── download.py    # бывший youtube_download.py + youtube_download_config.py (слиты)
```

### 4.5 Переименовать приватные функции, используемые в тестах

Тесты импортируют приватные имена. Поскольку совместимость не нужна — сделать публичными:

| Файл | Было | Станет |
|---|---|---|
| `ffmpeg.py` | `_resolve_speed()` | `resolve_speed()` |
| `ffmpeg.py` | `_build_video_filter()` | `build_video_filter()` |
| `ffmpeg.py` | `_build_ffmpeg_cmd()` | `build_ffmpeg_cmd()` |
| `pipeline.py` | `_segment_rng()` | `segment_rng()` |
| `subtitles.py` | `_escape_ass_text()` | `escape_ass_text()` |

---

## Phase 5 — Minor Improvements

### 5.1 `constants.py` — magic numbers → именованные константы

```python
# video_processor/constants.py

# Выходное разрешение (9:16)
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
OUTPUT_CENTER_X = OUTPUT_WIDTH // 2  # 540

# Требования Vosk к WAV
WAV_SAMPLE_RATE = 16000
WAV_CHANNELS = 1
WAV_SAMPLE_WIDTH_BYTES = 2  # 16-bit

# drawtext overlay
OVERLAY_FONT_SIZE = 24
OVERLAY_BOTTOM_MARGIN = 50

# Прогресс-троттлинг
PROGRESS_BUCKET_PERCENT = 5
```

Применить в:
- `ffmpeg.py:140` — `OUTPUT_WIDTH`, `OUTPUT_HEIGHT`
- `ffmpeg.py:195` — `OVERLAY_FONT_SIZE`, `OVERLAY_BOTTOM_MARGIN`
- `subtitles.py:36-37` — `OUTPUT_WIDTH`, `OUTPUT_HEIGHT`
- `subtitles.py:57` — `OUTPUT_CENTER_X`
- `stt/vosk.py:31-33` — `WAV_*`

### 5.2 Единообразный прогресс в UI

`ui.py:519` переформатирует прогресс вручную вместо использования `default_message()`.

```python
# ДО
def _progress(self, step, current, total, message):
    text = f"[{current}/{total}] {step.value}: {message}"

# ПОСЛЕ
from .progress import default_message

def _progress(self, step, current, total, message):
    text = default_message(step, current, total, message)
```

### 5.3 Убрать мёртвый код

- `progress.py:31` — `StepFormatter = Callable[...]` type alias не используется нигде → удалить

### 5.4 Валидация строки `speed`

`ffmpeg.py:145-151` — `_resolve_speed()` падает с `ValueError` на мусорном вводе.

```python
def resolve_speed(speed_value: str, rng: random.Random) -> float:
    value = speed_value.strip()
    try:
        if "-" in value:
            lo_str, hi_str = value.split("-", 1)
            lo, hi = float(lo_str), float(hi_str)
            if lo > hi:
                raise ValueError(f"speed range lo > hi: {lo} > {hi}")
            return rng.uniform(lo, hi)
        return float(value)
    except ValueError as exc:
        raise PipelineError(
            f"Invalid speed value {speed_value!r}. "
            "Use a float (1.0) or range (0.95-1.05)."
        ) from exc
```

### 5.5 `py.typed` marker

- **Создать**: `video_processor/py.typed` (пустой файл)
- Объявляет пакет как PEP 561 typed

### 5.6 Наполнить `__init__.py` public API

```python
# video_processor/__init__.py
"""Video transcription pipeline package."""

from .config import PipelineConfig
from .enums import HwAccel, STTEngine, VideoEncoder
from .errors import PipelineError
from .pipeline import run_pipeline
from .progress import ProgressCallback, Step

__all__ = [
    "PipelineConfig",
    "PipelineError",
    "ProgressCallback",
    "Step",
    "STTEngine",
    "VideoEncoder",
    "HwAccel",
    "run_pipeline",
]

__version__ = "0.2.0"
```

### 5.7 Добавить `__all__` в ключевые модули

Для каждого публичного модуля — явный `__all__` список экспортируемых имён.

---

## Порядок выполнения

```
Phase 0  → ci.yml + baseline                       [safety net]
Phase 1  → drawtext fix + requirements.txt + spec   [быстрые wins]
Phase 2  → DRY (as_dict, paths, errors, deps, conftest)
Phase 3  → enums.py + интеграция в config/cli/hwaccel
Phase 4  → распил cli/ → ui/ → config nested → stt/ → youtube/
Phase 5  → constants, progress, dead code, py.typed, __all__
```

После **каждого** Phase — полный прогон:

```bash
ruff check . && mypy && pytest -v
```

---

## Верификация (итоговая)

```bash
# 1. Линт
ruff check .

# 2. Типы (strict)
mypy

# 3. Тесты
pytest tests/ -v

# 4. CLI smoke
python -m video_processor --help                     # exit 0, все аргументы на месте
python -m video_processor --download https://youtu.be/XXX -o ./out  # download mode

# 5. GUI smoke
python -m video_processor                            # открывается окно с 3 вкладками

# 6. Программный API (новый nested-стиль)
python -c "
from video_processor import PipelineConfig, STTEngine, run_pipeline
cfg = PipelineConfig(
    input=Path('test.mp4'),
    stt=STTConfig(engine=STTEngine.VOSK),
    subtitles=SubtitleConfig(fontsize=90),
)
print('OK:', cfg.stt.engine, cfg.subtitles.fontsize)
"

# 7. PyInstaller (опционально, на Windows/CI)
python build_windows.py
```

---

## Риски

| Риск | Вероятность | Митигация |
|---|---|---|
| Phase 4.3 (nested config) ломает много consumers | Высокая | Выполнять шаг за шагом; после каждого файла — `mypy` поймает все обращения |
| Enums не дружат с argparse напрямую | Средняя | `type=` конвертер с обработкой `ValueError` → понятное сообщение |
| PyInstaller hiddenimports при распиле `ui/` | Средняя | Обновить список в `.spec`: `video_processor.ui.app`, `video_processor.ui.tab_process`, ... |
| Monkeypatch-пути в тестах ломаются при переименовании | Высокая | Глобальный search-replace путей импортов; `mypy` + `pytest` выявят все |
| Тесты `_resolve_speed` ломаются при переименовании в `resolve_speed` | Низкая | Обновить импорты в `test_ffmpeg.py`, `test_pipeline.py` |
| `transcribe.py` теряет фабрику `create_stt_engine` при создании `stt/` | Низкая | Оставить `create_stt_engine` в `transcribe.py`, только адаптеры переносятся |

---

## Чек-лист завершения

- [ ] `.github/workflows/ci.yml` создан и green
- [ ] drawtext баг исправлен
- [ ] `requirements.txt` удалён
- [ ] PyInstaller spec вынесен в отдельный файл
- [ ] `as_dict()` удалён из всех датаклассов
- [ ] `collect_upload_paths()` в `paths.py`, используется в cli + ui
- [ ] try/except в cli.py обобщён через хелпер
- [ ] `conftest.py` с общей тестовой фабрикой
- [ ] `enums.py` создан (STTEngine, VideoEncoder, HwAccel)
- [ ] Enums интегрированы в config, cli, hwaccel, transcribe
- [ ] `cli/` пакет создан, `build_parser()` разбит
- [ ] `ui/` пакет создан, табы разделены
- [ ] `PipelineConfig` переработан во вложенные dataclass'ы
- [ ] Все consumers обновлены (`ffmpeg`, `subtitles`, `pipeline`, `cli`, `ui`)
- [ ] `stt/` подпакет создан
- [ ] `youtube/` подпакет создан (конфиги слиты с логикой)
- [ ] Приватные функции переименованы в публичные
- [ ] `constants.py` создан, magic numbers заменены
- [ ] UI прогресс использует `default_message()`
- [ ] Мёртвый код (`StepFormatter`) удалён
- [ ] `resolve_speed()` валидирует ввод
- [ ] `py.typed` marker добавлен
- [ ] `__init__.py` с public API
- [ ] `__all__` в ключевых модулях
- [ ] `ruff check .` — green
- [ ] `mypy` — green
- [ ] `pytest` — green
- [ ] `python -m video_processor --help` работает
- [ ] `python -m video_processor` (GUI) открывается
