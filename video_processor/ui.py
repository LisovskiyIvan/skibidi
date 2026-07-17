"""Tkinter GUI for the video transcription pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False
    tk = None  # type: ignore[assignment]
    filedialog = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]

from .config import PipelineConfig
from .paths import collect_upload_paths
from .pipeline import run_pipeline
from .progress import Step
from .resources import (
    get_default_credentials_path,
    get_default_font_path,
    get_default_model_dir,
    get_default_token_path,
)
from .youtube import upload_to_youtube
from .youtube_config import YouTubeUploadConfig
from .youtube_download import download_from_youtube
from .youtube_download_config import YouTubeDownloadConfig


def run_gui() -> int:
    """Launch the Tkinter GUI."""
    if not TKINTER_AVAILABLE:
        print("Cannot initialize GUI: tkinter is not available.", file=sys.stderr)
        print("Use the CLI mode: python -m video_processor -i <video>", file=sys.stderr)
        return 1

    try:
        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot initialize GUI: {exc}", file=sys.stderr)
        print("Use the CLI mode: python -m video_processor -i <video>", file=sys.stderr)
        return 1

    Application(root)
    root.mainloop()
    return 0


if TKINTER_AVAILABLE:
    import threading

    class Application:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.root.title("Video Processor")
            self.root.geometry("900x700")
            self.root.minsize(800, 600)

            self._build_widgets()

        def _build_widgets(self) -> None:
            padding = {"padx": 10, "pady": 5}

            frame = ttk.Frame(self.root, padding=15)
            frame.pack(fill=tk.BOTH, expand=True)
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)

            notebook = ttk.Notebook(frame)
            notebook.grid(row=0, column=0, sticky=tk.NSEW)

            process_tab = ttk.Frame(notebook, padding=10)
            notebook.add(process_tab, text="Process")
            self._build_process_tab(process_tab, padding)

            upload_tab = ttk.Frame(notebook, padding=10)
            notebook.add(upload_tab, text="Upload")
            self._build_upload_tab(upload_tab, padding)

            download_tab = ttk.Frame(notebook, padding=10)
            notebook.add(download_tab, text="Download")
            self._build_download_tab(download_tab, padding)

            self.run_button = ttk.Button(frame, text="Run", command=self._run)
            self.run_button.grid(row=1, column=0, pady=15)

            self.progress_var = tk.StringVar(value="Ready")
            ttk.Label(frame, textvariable=self.progress_var, wraplength=850).grid(
                row=2, column=0, sticky=tk.W, **padding
            )

        def _build_process_tab(self, tab: ttk.Frame, padding: dict[str, int]) -> None:
            # Input
            ttk.Label(tab, text="Input video:").grid(row=0, column=0, sticky=tk.W, **padding)
            self.input_var = tk.StringVar()
            ttk.Entry(tab, textvariable=self.input_var, width=50).grid(row=0, column=1, **padding)
            ttk.Button(tab, text="Browse", command=self._browse_input).grid(row=0, column=2, **padding)

            # Output
            ttk.Label(tab, text="Output folder:").grid(row=1, column=0, sticky=tk.W, **padding)
            self.output_var = tk.StringVar(value="out")
            ttk.Entry(tab, textvariable=self.output_var, width=50).grid(row=1, column=1, **padding)
            ttk.Button(tab, text="Browse", command=self._browse_output).grid(row=1, column=2, **padding)

            # Speech-to-text engine selection
            stt_frame = ttk.LabelFrame(tab, text="Speech-to-text", padding=10)
            stt_frame.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=5)
            stt_frame.columnconfigure(1, weight=1)

            ttk.Label(stt_frame, text="Engine:").grid(row=0, column=0, sticky=tk.W, **padding)
            self.stt_engine_var = tk.StringVar(value="vosk")
            engine_combo = ttk.Combobox(
                stt_frame,
                textvariable=self.stt_engine_var,
                values=["vosk", "whisper"],
                state="readonly",
                width=12,
            )
            engine_combo.grid(row=0, column=1, sticky=tk.W, **padding)
            engine_combo.bind("<<ComboboxSelected>>", lambda _e: self._toggle_stt_engine())

            # Vosk options (shown when engine=vosk)
            self.vosk_frame = ttk.Frame(stt_frame)
            self.vosk_frame.grid(row=1, column=0, columnspan=3, sticky=tk.EW, **padding)
            self.vosk_frame.columnconfigure(1, weight=1)
            ttk.Label(self.vosk_frame, text="Vosk model:").grid(
                row=0, column=0, sticky=tk.W, **padding
            )
            self.model_var = tk.StringVar(value=str(get_default_model_dir()))
            ttk.Entry(self.vosk_frame, textvariable=self.model_var, width=46).grid(
                row=0, column=1, sticky=tk.EW, **padding
            )
            ttk.Button(self.vosk_frame, text="Browse", command=self._browse_model).grid(
                row=0, column=2, **padding
            )

            # Whisper options (hidden by default)
            self.whisper_frame = ttk.Frame(stt_frame)
            self.whisper_frame.columnconfigure(1, weight=1)
            ttk.Label(self.whisper_frame, text="Language:").grid(
                row=0, column=0, sticky=tk.W, **padding
            )
            self.language_var = tk.StringVar()
            ttk.Entry(self.whisper_frame, textvariable=self.language_var, width=12).grid(
                row=0, column=1, sticky=tk.W, **padding
            )
            ttk.Label(self.whisper_frame, text="e.g. ru, en; blank = auto-detect").grid(
                row=0, column=2, sticky=tk.W, **padding
            )

            ttk.Label(self.whisper_frame, text="Whisper model:").grid(
                row=1, column=0, sticky=tk.W, **padding
            )
            self.whisper_model_var = tk.StringVar(value="small")
            ttk.Combobox(
                self.whisper_frame,
                textvariable=self.whisper_model_var,
                values=["tiny", "base", "small", "medium", "large-v3"],
                state="readonly",
                width=12,
            ).grid(row=1, column=1, sticky=tk.W, **padding)

            ttk.Label(self.whisper_frame, text="Device:").grid(
                row=2, column=0, sticky=tk.W, **padding
            )
            self.whisper_device_var = tk.StringVar(value="auto")
            ttk.Combobox(
                self.whisper_frame,
                textvariable=self.whisper_device_var,
                values=["auto", "cpu", "cuda"],
                state="readonly",
                width=12,
            ).grid(row=2, column=1, sticky=tk.W, **padding)

            self._toggle_stt_engine()

            # Settings
            ttk.Label(tab, text="Segment seconds:").grid(row=3, column=0, sticky=tk.W, **padding)
            self.seg_var = tk.IntVar(value=60)
            ttk.Spinbox(tab, from_=10, to=600, textvariable=self.seg_var, width=10).grid(
                row=3, column=1, sticky=tk.W, **padding
            )

            self.burn_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(tab, text="Burn subtitles", variable=self.burn_var).grid(
                row=4, column=1, sticky=tk.W, **padding
            )

            ttk.Label(tab, text="Font name:").grid(row=5, column=0, sticky=tk.W, **padding)
            self.font_var = tk.StringVar(value="Oswald")
            ttk.Entry(tab, textvariable=self.font_var, width=20).grid(
                row=5, column=1, sticky=tk.W, **padding
            )

            ttk.Label(tab, text="Font size:").grid(row=6, column=0, sticky=tk.W, **padding)
            self.font_size_var = tk.IntVar(value=100)
            ttk.Spinbox(tab, from_=10, to=300, textvariable=self.font_size_var, width=10).grid(
                row=6, column=1, sticky=tk.W, **padding
            )

            ttk.Label(tab, text="Position Y:").grid(row=7, column=0, sticky=tk.W, **padding)
            self.pos_y_var = tk.IntVar(value=1500)
            ttk.Spinbox(tab, from_=0, to=1920, textvariable=self.pos_y_var, width=10).grid(
                row=7, column=1, sticky=tk.W, **padding
            )

            # Fingerprint / editing options
            edit_frame = ttk.LabelFrame(tab, text="Fingerprint evasion / editing", padding=10)
            edit_frame.grid(row=8, column=0, columnspan=3, sticky=tk.EW, pady=10)

            self.mirror_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(edit_frame, text="Mirror horizontally", variable=self.mirror_var).grid(
                row=0, column=0, sticky=tk.W, **padding
            )

            ttk.Label(edit_frame, text="Speed:").grid(row=1, column=0, sticky=tk.W, **padding)
            self.speed_var = tk.StringVar(value="0.95-1.05")
            ttk.Entry(edit_frame, textvariable=self.speed_var, width=20).grid(
                row=1, column=1, sticky=tk.W, **padding
            )
            ttk.Label(edit_frame, text="e.g. 1.0 or 0.95-1.05 (1.0 = original)").grid(
                row=1, column=2, sticky=tk.W, **padding
            )

            ttk.Label(edit_frame, text="Brightness:").grid(row=2, column=0, sticky=tk.W, **padding)
            self.brightness_var = tk.StringVar()
            ttk.Entry(edit_frame, textvariable=self.brightness_var, width=10).grid(
                row=2, column=1, sticky=tk.W, **padding
            )
            ttk.Label(edit_frame, text="0 = original, -1.0 to 1.0").grid(
                row=2, column=2, sticky=tk.W, **padding
            )

            ttk.Label(edit_frame, text="Contrast:").grid(row=3, column=0, sticky=tk.W, **padding)
            self.contrast_var = tk.StringVar()
            ttk.Entry(edit_frame, textvariable=self.contrast_var, width=10).grid(
                row=3, column=1, sticky=tk.W, **padding
            )
            ttk.Label(edit_frame, text="1.0 = original, range -1000 to 1000").grid(
                row=3, column=2, sticky=tk.W, **padding
            )

            ttk.Label(edit_frame, text="Saturation:").grid(row=4, column=0, sticky=tk.W, **padding)
            self.saturation_var = tk.StringVar()
            ttk.Entry(edit_frame, textvariable=self.saturation_var, width=10).grid(
                row=4, column=1, sticky=tk.W, **padding
            )
            ttk.Label(edit_frame, text="1.0 = original, 0 = grayscale, 0 to 3").grid(
                row=4, column=2, sticky=tk.W, **padding
            )

            ttk.Label(edit_frame, text="Gamma:").grid(row=5, column=0, sticky=tk.W, **padding)
            self.gamma_var = tk.StringVar()
            ttk.Entry(edit_frame, textvariable=self.gamma_var, width=10).grid(
                row=5, column=1, sticky=tk.W, **padding
            )
            ttk.Label(edit_frame, text="1.0 = original, range 0.1 to 10").grid(
                row=5, column=2, sticky=tk.W, **padding
            )

            ttk.Label(edit_frame, text="Hue:").grid(row=6, column=0, sticky=tk.W, **padding)
            self.hue_var = tk.StringVar()
            ttk.Entry(edit_frame, textvariable=self.hue_var, width=10).grid(
                row=6, column=1, sticky=tk.W, **padding
            )
            ttk.Label(edit_frame, text="0 = original, 0 to 360 degrees").grid(
                row=6, column=2, sticky=tk.W, **padding
            )

            self.sharpness_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(edit_frame, text="Sharpen", variable=self.sharpness_var).grid(
                row=7, column=0, sticky=tk.W, **padding
            )

            ttk.Label(edit_frame, text="Noise:").grid(row=8, column=0, sticky=tk.W, **padding)
            self.noise_var = tk.StringVar(value="0")
            ttk.Entry(edit_frame, textvariable=self.noise_var, width=10).grid(
                row=8, column=1, sticky=tk.W, **padding
            )
            ttk.Label(edit_frame, text="0 = off, higher = stronger grain").grid(
                row=8, column=2, sticky=tk.W, **padding
            )

            ttk.Label(edit_frame, text="Overlay text:").grid(
                row=9, column=0, sticky=tk.W, **padding
            )
            self.overlay_text_var = tk.StringVar()
            ttk.Entry(edit_frame, textvariable=self.overlay_text_var, width=40).grid(
                row=9, column=1, columnspan=2, sticky=tk.W, **padding
            )

            ttk.Label(edit_frame, text="Background audio:").grid(
                row=10, column=0, sticky=tk.W, **padding
            )
            self.bg_audio_var = tk.StringVar()
            ttk.Entry(edit_frame, textvariable=self.bg_audio_var, width=40).grid(
                row=10, column=1, sticky=tk.W, **padding
            )
            ttk.Button(edit_frame, text="Browse", command=self._browse_bg_audio).grid(
                row=10, column=2, sticky=tk.W, **padding
            )

            ttk.Label(edit_frame, text="BG volume:").grid(row=11, column=0, sticky=tk.W, **padding)
            self.bg_volume_var = tk.StringVar(value="0.3")
            ttk.Entry(edit_frame, textvariable=self.bg_volume_var, width=10).grid(
                row=11, column=1, sticky=tk.W, **padding
            )
            ttk.Label(edit_frame, text="0.0 = silent, 1.0 = full").grid(
                row=11, column=2, sticky=tk.W, **padding
            )

            edit_frame.columnconfigure(1, weight=1)
            tab.columnconfigure(1, weight=1)

        def _build_upload_tab(self, tab: ttk.Frame, padding: dict[str, int]) -> None:
            self.yt_upload_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                tab, text="Upload to YouTube after processing", variable=self.yt_upload_var
            ).grid(row=0, column=0, columnspan=3, sticky=tk.W, **padding)

            ttk.Label(tab, text="Credentials:").grid(row=1, column=0, sticky=tk.W, **padding)
            self.yt_credentials_var = tk.StringVar(value=str(get_default_credentials_path()))
            ttk.Entry(tab, textvariable=self.yt_credentials_var, width=50).grid(
                row=1, column=1, **padding
            )
            ttk.Button(tab, text="Browse", command=self._browse_yt_credentials).grid(
                row=1, column=2, sticky=tk.W, **padding
            )

            ttk.Label(tab, text="Title:").grid(row=2, column=0, sticky=tk.W, **padding)
            self.yt_title_var = tk.StringVar(value="{name}")
            ttk.Entry(tab, textvariable=self.yt_title_var, width=50).grid(
                row=2, column=1, columnspan=2, sticky=tk.W, **padding
            )

            ttk.Label(tab, text="Description:").grid(row=3, column=0, sticky=tk.W, **padding)
            self.yt_description_var = tk.StringVar()
            ttk.Entry(tab, textvariable=self.yt_description_var, width=50).grid(
                row=3, column=1, columnspan=2, sticky=tk.W, **padding
            )

            ttk.Label(tab, text="Tags:").grid(row=4, column=0, sticky=tk.W, **padding)
            self.yt_tags_var = tk.StringVar()
            ttk.Entry(tab, textvariable=self.yt_tags_var, width=50).grid(
                row=4, column=1, columnspan=2, sticky=tk.W, **padding
            )

            ttk.Label(tab, text="Privacy:").grid(row=5, column=0, sticky=tk.W, **padding)
            self.yt_privacy_var = tk.StringVar(value="private")
            ttk.Combobox(
                tab,
                textvariable=self.yt_privacy_var,
                values=["private", "unlisted", "public"],
                width=12,
                state="readonly",
            ).grid(row=5, column=1, sticky=tk.W, **padding)

            tab.columnconfigure(1, weight=1)

        def _build_download_tab(self, tab: ttk.Frame, padding: dict[str, int]) -> None:
            ttk.Label(tab, text="URLs (one per line):").grid(
                row=0, column=0, sticky=tk.NW, **padding
            )
            self.dl_urls_text = tk.Text(tab, width=50, height=3, wrap=tk.NONE)
            self.dl_urls_text.grid(row=0, column=1, columnspan=2, sticky=tk.EW, **padding)

            ttk.Label(tab, text="Format:").grid(row=1, column=0, sticky=tk.W, **padding)
            self.dl_format_var = tk.StringVar()
            ttk.Entry(tab, textvariable=self.dl_format_var, width=50).grid(
                row=1, column=1, columnspan=2, sticky=tk.W, **padding
            )

            ttk.Label(tab, text="Template:").grid(row=2, column=0, sticky=tk.W, **padding)
            self.dl_template_var = tk.StringVar()
            ttk.Entry(tab, textvariable=self.dl_template_var, width=50).grid(
                row=2, column=1, columnspan=2, sticky=tk.W, **padding
            )

            self.dl_button = ttk.Button(tab, text="Download", command=self._run_download)
            self.dl_button.grid(row=3, column=0, columnspan=3, pady=5)

            tab.columnconfigure(1, weight=1)

        def _browse_input(self) -> None:
            path = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi"), ("All files", "*.*")])
            if path:
                self.input_var.set(path)

        def _browse_output(self) -> None:
            path = filedialog.askdirectory()
            if path:
                self.output_var.set(path)

        def _browse_model(self) -> None:
            path = filedialog.askdirectory()
            if path:
                self.model_var.set(path)

        def _toggle_stt_engine(self) -> None:
            """Show the options relevant to the selected STT engine."""
            if self.stt_engine_var.get() == "whisper":
                self.vosk_frame.grid_remove()
                self.whisper_frame.grid(row=1, column=0, columnspan=3, sticky=tk.EW)
            else:
                self.whisper_frame.grid_remove()
                self.vosk_frame.grid(row=1, column=0, columnspan=3, sticky=tk.EW)

        def _browse_bg_audio(self) -> None:
            path = filedialog.askopenfilename(filetypes=[("Audio files", "*.mp3 *.wav *.aac *.ogg *.m4a"), ("All files", "*.*")])
            if path:
                self.bg_audio_var.set(path)

        def _browse_yt_credentials(self) -> None:
            path = filedialog.askopenfilename(filetypes=[("OAuth secret", "client_secret.json"), ("JSON files", "*.json"), ("All files", "*.*")])
            if path:
                self.yt_credentials_var.set(path)

        def _float_or_none(self, var: tk.StringVar) -> float | None:
            value = var.get().strip()
            return float(value) if value else None

        def _make_config(self) -> PipelineConfig:
            return PipelineConfig(
                input=Path(self.input_var.get()),
                output_dir=Path(self.output_var.get()),
                model_dir=Path(self.model_var.get()),
                stt_engine=self.stt_engine_var.get(),
                language=self.language_var.get().strip() or None,
                whisper_model=self.whisper_model_var.get(),
                whisper_device=self.whisper_device_var.get(),
                seg_seconds=self.seg_var.get(),
                burn_subs=self.burn_var.get(),
                subtitle_font=self.font_var.get(),
                subtitle_font_path=get_default_font_path(),
                subtitle_fontsize=self.font_size_var.get(),
                subtitle_pos_y=self.pos_y_var.get(),
                mirror=self.mirror_var.get(),
                speed=self.speed_var.get(),
                brightness=self._float_or_none(self.brightness_var),
                contrast=self._float_or_none(self.contrast_var),
                saturation=self._float_or_none(self.saturation_var),
                gamma=self._float_or_none(self.gamma_var),
                hue=self._float_or_none(self.hue_var),
                sharpness=self.sharpness_var.get(),
                noise=int(self.noise_var.get() or 0),
                overlay_text=self.overlay_text_var.get() or None,
                background_audio=Path(self.bg_audio_var.get()) if self.bg_audio_var.get() else None,
                background_audio_volume=float(self.bg_volume_var.get() or 0.3),
            )

        def _make_yt_config(self, video_paths: list[Path]) -> YouTubeUploadConfig:
            tags = [tag.strip() for tag in self.yt_tags_var.get().split(",") if tag.strip()]
            return YouTubeUploadConfig(
                video_paths=video_paths,
                credentials_path=Path(self.yt_credentials_var.get()),
                token_path=get_default_token_path(),
                title=self.yt_title_var.get(),
                description=self.yt_description_var.get(),
                tags=tags,
                privacy_status=self.yt_privacy_var.get(),
            )

        def _make_download_config(self) -> YouTubeDownloadConfig:
            raw = self.dl_urls_text.get("1.0", "end")
            urls = [line.strip() for line in raw.splitlines() if line.strip()]
            cfg = YouTubeDownloadConfig(
                urls=urls,
                output_dir=Path(self.output_var.get()),
            )
            format_value = self.dl_format_var.get().strip()
            template_value = self.dl_template_var.get().strip()
            if format_value:
                cfg.format = format_value
            if template_value:
                cfg.outtmpl = template_value
            return cfg

        def _run_download(self) -> None:
            if not self.dl_urls_text.get("1.0", "end").strip():
                messagebox.showerror("Error", "Please enter at least one YouTube URL.")
                return

            self.dl_button.config(state=tk.DISABLED)
            self.run_button.config(state=tk.DISABLED)
            self.progress_var.set("Starting download...")

            def target() -> None:
                paths: list[Path] = []
                try:
                    dl_config = self._make_download_config()
                    paths = download_from_youtube(dl_config, self._progress)
                    self.root.after(0, lambda ps=paths: self._on_download_success(ps))
                except Exception as exc:  # noqa: BLE001
                    self.root.after(0, lambda e=exc: self._on_download_error(e))

            thread = threading.Thread(target=target, daemon=True)
            thread.start()

        def _on_download_success(self, paths: list[Path]) -> None:
            self.dl_button.config(state=tk.NORMAL)
            self.run_button.config(state=tk.NORMAL)
            links = "\n".join(str(p) for p in paths)
            messagebox.showinfo(
                "Download complete",
                f"Downloaded {len(paths)} video(s):\n\n{links}",
            )

        def _on_download_error(self, exc: Exception) -> None:
            self.dl_button.config(state=tk.NORMAL)
            self.run_button.config(state=tk.NORMAL)
            messagebox.showerror("Error", f"Download failed:\n{exc}")

        def _progress(self, step: Step, current: int, total: int, message: str) -> None:
            text = f"[{current}/{total}] {step.value}: {message}"
            # Marshal to the Tk main thread: Tkinter is not thread-safe, and this
            # callback is invoked from the worker thread that runs the pipeline.
            self.root.after(0, self.progress_var.set, text)

        def _run(self) -> None:
            if not self.input_var.get():
                messagebox.showerror("Error", "Please select an input video.")
                return

            self.run_button.config(state=tk.DISABLED)
            self.progress_var.set("Starting...")

            config = self._make_config()
            should_upload = self.yt_upload_var.get()

            def target() -> None:
                video_ids: list[str] = []
                try:
                    run_pipeline(config, self._progress)
                    if should_upload:
                        upload_paths = collect_upload_paths(config)
                        if not upload_paths:
                            raise RuntimeError("No final clips found to upload.")
                        yt_config = self._make_yt_config(upload_paths)
                        video_ids = upload_to_youtube(yt_config, self._progress)
                    self.root.after(0, lambda ids=video_ids: self._on_success(ids))
                except Exception as exc:  # noqa: BLE001
                    self.root.after(0, lambda e=exc: self._on_error(e))

            thread = threading.Thread(target=target, daemon=True)
            thread.start()

        def _on_success(self, video_ids: list[str] | None = None) -> None:
            self.run_button.config(state=tk.NORMAL)
            if video_ids:
                links = "\n".join(f"https://youtu.be/{vid}" for vid in video_ids)
                messagebox.showinfo("Done", f"Pipeline completed and uploaded {len(video_ids)} video(s):\n\n{links}")
            else:
                messagebox.showinfo("Done", "Pipeline completed successfully.")

        def _on_error(self, exc: Exception) -> None:
            self.run_button.config(state=tk.NORMAL)
            messagebox.showerror("Error", f"Pipeline failed:\n{exc}")
