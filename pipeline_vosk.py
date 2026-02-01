import json
import math
import os
import subprocess
import wave
from pathlib import Path

from vosk import Model, KaldiRecognizer


# --------- CONFIG ----------
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
MODEL_DIR = Path("vosk-model-small-ru-0.22")  # <-- путь к распакованной RU модели
INPUT = Path("assets/videoplayback.mp4")
OUTDIR = Path("out")
SEG_SECONDS = 60
LANG_HINT = "ru"
BURN_SUBS = True  # True = прожечь в картинку, False = оставить рядом .srt без прожига
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


def vosk_transcribe_to_srt(model: Model, wav_path: Path, srt_path: Path) -> None:
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
            # w: {"conf":..., "end":..., "start":..., "word":"..."}
            words.append(w)

    # Если ничего не распознано — всё равно создадим пустой SRT
    if not words:
        srt_path.write_text("", encoding="utf-8")
        return

    # Группировка слов в субтитры:
    # - максимум 2 строки / ~42 символа (упрощенно)
    # - либо пауза > 0.8s, либо длина текста > 80 символов
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

    # Пишем SRT
    lines = []
    for i, c in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{srt_time(c['start'])} --> {srt_time(c['end'])}")
        lines.append(c["text"])
        lines.append("")
    srt_path.write_text("\n".join(lines), encoding="utf-8")


def burn_subs(input_mp4: Path, srt_path: Path, out_mp4: Path) -> None:
    # Конвертируем в 9:16 (вертикальное видео) + прожигаем субтитры
    # crop=ih*9/16:ih - центральный кроп для 9:16 соотношения
    vf_filter = f"crop=ih*9/16:ih,subtitles={srt_path.as_posix()}"
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
    # Конвертация в 9:16 без субтитров (центральный кроп)
    run(
        [
            FFMPEG,
            "-hide_banner",
            "-y",
            "-i",
            str(input_mp4),
            "-vf",
            "crop=ih*9/16:ih",
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


def main():
    if not INPUT.exists():
        raise FileNotFoundError(f"Missing {INPUT}")
    if not MODEL_DIR.exists():
        raise FileNotFoundError(f"Missing model dir: {MODEL_DIR}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    segments_dir = OUTDIR / "segments"
    wav_dir = OUTDIR / "wav"
    srt_dir = OUTDIR / "srt"
    final_dir = OUTDIR / "final"
    for d in (segments_dir, wav_dir, srt_dir, final_dir):
        d.mkdir(parents=True, exist_ok=True)

    duration = get_duration_sec(INPUT)
    n = int(math.ceil(duration / SEG_SECONDS))

    print(f"Duration: {duration:.2f}s => segments: {n}")

    print("Loading Vosk model...")
    model = Model(str(MODEL_DIR))

    for idx in range(n):
        start = idx * SEG_SECONDS
        out_mp4 = segments_dir / f"clip_{idx:02d}.mp4"
        out_wav = wav_dir / f"clip_{idx:02d}.wav"
        out_srt = srt_dir / f"clip_{idx:02d}.srt"

        final_mp4 = (
            final_dir / f"clip_{idx:02d}_sub.mp4"
            if BURN_SUBS
            else final_dir / f"clip_{idx:02d}.mp4"
        )

        print(f"[{idx + 1}/{n}] segment {start}-{start + SEG_SECONDS}s")

        extract_segment(INPUT, start, SEG_SECONDS, out_mp4)
        extract_wav(out_mp4, out_wav)
        vosk_transcribe_to_srt(model, out_wav, out_srt)

        if BURN_SUBS:
            burn_subs(out_mp4, out_srt, final_mp4)
        else:
            # конвертируем в 9:16 без субтитров
            convert_to_9x16(out_mp4, final_mp4)

    print("Done.")
    print(f"Final videos: {final_dir}")
    print(f"SRT files:    {srt_dir}")


if __name__ == "__main__":
    main()
