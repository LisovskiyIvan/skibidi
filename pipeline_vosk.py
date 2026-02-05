import argparse
import json
import math
import os
import subprocess
import sys
import wave
from pathlib import Path
from tkinter import Tk, filedialog, messagebox

from vosk import Model, KaldiRecognizer


def select_input_file() -> Path:
    """Open file dialog to select input video file."""
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    file_path = filedialog.askopenfilename(
        title="Выберите исходное видео",
        filetypes=[
            ("Video files", "*.mp4 *.avi *.mov *.mkv *.webm"),
            ("All files", "*.*"),
        ],
    )
    root.destroy()
    if not file_path:
        raise ValueError("Input file not selected")
    return Path(file_path)


def select_output_dir() -> Path:
    """Open directory dialog to select output folder."""
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    dir_path = filedialog.askdirectory(
        title="Выберите папку для сохранения результатов"
    )
    root.destroy()
    if not dir_path:
        raise ValueError("Output directory not selected")
    return Path(dir_path)


# --------- CONFIG ----------
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
MODEL_DIR = Path("vosk-model-small-ru-0.22")  # <-- путь к распакованной RU модели
INPUT = Path("assets/videoplayback.mp4")
OUTDIR = Path("out")
SEG_SECONDS = 60
LANG_HINT = "ru"
BURN_SUBS = True  # True = прожечь в картинку, False = оставить рядом без прожига

# Настройки субтитров
SUBTITLE_FONT = "assets/oswald/static/Oswald-Bold.ttf"  # Шрифт для субтитров
SUBTITLE_FONTSIZE = 100  # Размер шрифта
SUBTITLE_POS_Y = (
    1500  # Y координата (0=верх, 960=центр, 1920=низ). 1300 = чуть ниже центра
)
SUBTITLE_FADE_IN = 200  # ms - плавное появление
SUBTITLE_FADE_OUT = 200  # ms - плавное исчезновение
# --------------------------


def run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed:\n{' '.join(cmd)}\n\nSTDERR:\n{p.stderr}")


def get_duration_sec(path: Path) -> float:
    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed:\n{p.stderr}")
    return float(p.stdout.strip())


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def extract_segment(input_path: Path, start: int, dur: int, out_mp4: Path) -> None:
    # реэнкод не делаем (быстро). Если на границах будут артефакты — скажешь, дам вариант с reencode.
    run(
        [
            FFMPEG,
            "-hide_banner",
            "-y",
            "-ss",
            str(start),
            "-t",
            str(dur),
            "-i",
            str(input_path),
            "-map",
            "0",
            "-c",
            "copy",
            "-reset_timestamps",
            "1",
            str(out_mp4),
        ]
    )


def extract_wav(input_mp4: Path, out_wav: Path) -> None:
    # 16kHz mono PCM — оптимально для Vosk
    run(
        [
            FFMPEG,
            "-hide_banner",
            "-y",
            "-i",
            str(input_mp4),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            str(out_wav),
        ]
    )


def ass_time(t: float) -> str:
    """Convert seconds to ASS time format: H:MM:SS.cc"""
    ms = int(round(t * 100))
    h = ms // 360000
    ms %= 360000
    m = ms // 6000
    ms %= 6000
    s = ms // 100
    ms %= 100
    return f"{h}:{m:02d}:{s:02d}.{ms:02d}"


def vosk_transcribe_to_ass(model: Model, wav_path: Path, ass_path: Path) -> None:
    """Transcribe audio to ASS format with custom styling and fade animations."""
    wf = wave.open(str(wav_path), "rb")
    if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
        wf.close()
        raise ValueError("WAV must be mono 16-bit PCM @16kHz. (Use extract_wav step)")

    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(True)

    results = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            results.append(json.loads(rec.Result()))
    results.append(json.loads(rec.FinalResult()))
    wf.close()

    # Собираем слова с таймингами
    words = []
    for r in results:
        for w in r.get("result", []):
            words.append(w)

    # Если ничего не распознано — создадим пустой ASS
    if not words:
        ass_path.write_text("", encoding="utf-8")
        return

    # Группировка слов в субтитры
    max_chars = 60
    max_gap = 0.8

    cues = []
    cur = {"start": words[0]["start"], "end": words[0]["end"], "text": words[0]["word"]}
    for w in words[1:]:
        gap = w["start"] - cur["end"]
        next_text = (cur["text"] + " " + w["word"]).strip()
        if gap > max_gap or len(next_text) > max_chars:
            cues.append(cur)
            cur = {"start": w["start"], "end": w["end"], "text": w["word"]}
        else:
            cur["text"] = next_text
            cur["end"] = w["end"]
    cues.append(cur)

    # Генерируем ASS файл с кастомным стилем
    ass_header = f"""[Script Info]
Title: Auto-generated subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{SUBTITLE_FONT},{SUBTITLE_FONTSIZE},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Генерируем Dialogue строки с fade анимацией и точным позиционированием
    dialogue_lines = []
    center_x = 1080 // 2  # Центр по ширине
    for c in cues:
        start = ass_time(c["start"])
        end = ass_time(c["end"])
        # \pos(x,y) - точная позиция, \fad() - плавное появление
        text = f"{{\\pos({center_x},{SUBTITLE_POS_Y})\\fad({SUBTITLE_FADE_IN},{SUBTITLE_FADE_OUT})}}{c['text']}"
        dialogue_lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    ass_content = ass_header + "\n".join(dialogue_lines)
    ass_path.write_text(ass_content, encoding="utf-8")


def burn_subs(input_mp4: Path, ass_path: Path, out_mp4: Path) -> None:
    # Конвертируем в 9:16 (1080x1920) + прожигаем ASS субтитры с кастомным стилем и fade
    # Стиль уже задан в ASS файле: шрифт Arial, размер 48, fade анимация
    vf_filter = f"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,ass={ass_path.as_posix()}"
    run(
        [
            FFMPEG,
            "-hide_banner",
            "-y",
            "-i",
            str(input_mp4),
            "-vf",
            vf_filter,
            "-c:a",
            "copy",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            str(out_mp4),
        ]
    )


def convert_to_9x16(input_mp4: Path, out_mp4: Path) -> None:
    # Конвертация в 9:16 (1080x1920) с сохранением пропорций через паддинг
    vf_filter = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    run(
        [
            FFMPEG,
            "-hide_banner",
            "-y",
            "-i",
            str(input_mp4),
            "-vf",
            vf_filter,
            "-c:a",
            "copy",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            str(out_mp4),
        ]
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Video Processing Pipeline with Vosk transcription",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Launch GUI mode
  %(prog)s -i video.mp4 -o ./out   # CLI mode
  %(prog)s --input video.mp4 --output ./results
        """,
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        help="Input video file path (CLI mode). If not provided, GUI will be used.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output directory path (CLI mode). If not provided, GUI will be used.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print("=== Video Processing Pipeline ===")

    # Determine input file
    if args.input:
        input_file = args.input
        if not input_file.exists():
            print(f"✗ Input file not found: {input_file}")
            sys.exit(1)
        print(f"✓ Input file: {input_file}")
    else:
        print("\nШаг 1: Выбор исходного видео...")
        try:
            input_file = select_input_file()
            print(f"✓ Выбран файл: {input_file}")
        except ValueError as e:
            print(f"✗ {e}")
            sys.exit(1)

    # Determine output directory
    if args.output:
        output_dir = args.output
        print(f"✓ Output directory: {output_dir}")
    else:
        print("\nШаг 2: Выбор папки для результатов...")
        try:
            output_dir = select_output_dir()
            print(f"✓ Папка вывода: {output_dir}")
        except ValueError as e:
            print(f"✗ {e}")
            sys.exit(1)

    if not MODEL_DIR.exists():
        raise FileNotFoundError(f"Missing model dir: {MODEL_DIR}")

    outdir = output_dir
    outdir.mkdir(parents=True, exist_ok=True)
    segments_dir = outdir / "segments"
    wav_dir = outdir / "wav"
    srt_dir = outdir / "srt"
    final_dir = outdir / "final"
    for d in (segments_dir, wav_dir, srt_dir, final_dir):
        d.mkdir(parents=True, exist_ok=True)

    duration = get_duration_sec(input_file)
    n = int(math.ceil(duration / SEG_SECONDS))

    print(f"\nDuration: {duration:.2f}s => segments: {n}")

    print("Loading Vosk model...")
    model = Model(str(MODEL_DIR))

    for idx in range(n):
        start = idx * SEG_SECONDS
        out_mp4 = segments_dir / f"clip_{idx:02d}.mp4"
        out_wav = wav_dir / f"clip_{idx:02d}.wav"
        out_ass = srt_dir / f"clip_{idx:02d}.ass"

        final_mp4 = (
            final_dir / f"clip_{idx:02d}_sub.mp4"
            if BURN_SUBS
            else final_dir / f"clip_{idx:02d}.mp4"
        )

        print(f"[{idx + 1}/{n}] segment {start}-{start + SEG_SECONDS}s")

        extract_segment(input_file, start, SEG_SECONDS, out_mp4)
        extract_wav(out_mp4, out_wav)
        vosk_transcribe_to_ass(model, out_wav, out_ass)

        if BURN_SUBS:
            burn_subs(out_mp4, out_ass, final_mp4)
        else:
            # конвертируем в 9:16 без субтитров
            convert_to_9x16(out_mp4, final_mp4)

    print("\n" + "=" * 50)
    print("Done!")
    print(f"Final videos: {final_dir}")
    print(f"ASS files:    {srt_dir}")
    print("=" * 50)


if __name__ == "__main__":
    main()
