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
from .pipeline import run_pipeline
from .progress import Step
from .resources import get_default_font_path, get_default_model_dir


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
            self.root.geometry("600")
            self.root.minsize(500, 400)

            self._build_widgets()

        def _build_widgets(self) -> None:
            padding = {"padx": 10, "pady": 5}

            frame = ttk.Frame(self.root, padding=15)
            frame.pack(fill=tk.BOTH, expand=True)

            # Input
            ttk.Label(frame, text="Input video:").grid(row=0, column=0, sticky=tk.W, **padding)
            self.input_var = tk.StringVar()
            ttk.Entry(frame, textvariable=self.input_var, width=50).grid(row=0, column=1, **padding)
            ttk.Button(frame, text="Browse", command=self._browse_input).grid(row=0, column=2, **padding)

            # Output
            ttk.Label(frame, text="Output folder:").grid(row=1, column=0, sticky=tk.W, **padding)
            self.output_var = tk.StringVar(value="out")
            ttk.Entry(frame, textvariable=self.output_var, width=50).grid(row=1, column=1, **padding)
            ttk.Button(frame, text="Browse", command=self._browse_output).grid(row=1, column=2, **padding)

            # Model
            ttk.Label(frame, text="Vosk model:").grid(row=2, column=0, sticky=tk.W, **padding)
            self.model_var = tk.StringVar(value=str(get_default_model_dir()))
            ttk.Entry(frame, textvariable=self.model_var, width=50).grid(row=2, column=1, **padding)
            ttk.Button(frame, text="Browse", command=self._browse_model).grid(row=2, column=2, **padding)

            # Settings
            ttk.Label(frame, text="Segment seconds:").grid(row=3, column=0, sticky=tk.W, **padding)
            self.seg_var = tk.IntVar(value=60)
            ttk.Spinbox(frame, from_=10, to=600, textvariable=self.seg_var, width=10).grid(row=3, column=1, sticky=tk.W, **padding)

            self.burn_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(frame, text="Burn subtitles", variable=self.burn_var).grid(row=4, column=1, sticky=tk.W, **padding)

            ttk.Label(frame, text="Font name:").grid(row=5, column=0, sticky=tk.W, **padding)
            self.font_var = tk.StringVar(value="Oswald")
            ttk.Entry(frame, textvariable=self.font_var, width=20).grid(row=5, column=1, sticky=tk.W, **padding)

            ttk.Label(frame, text="Font size:").grid(row=6, column=0, sticky=tk.W, **padding)
            self.font_size_var = tk.IntVar(value=100)
            ttk.Spinbox(frame, from_=10, to=300, textvariable=self.font_size_var, width=10).grid(row=6, column=1, sticky=tk.W, **padding)

            ttk.Label(frame, text="Position Y:").grid(row=7, column=0, sticky=tk.W, **padding)
            self.pos_y_var = tk.IntVar(value=1500)
            ttk.Spinbox(frame, from_=0, to=1920, textvariable=self.pos_y_var, width=10).grid(row=7, column=1, sticky=tk.W, **padding)

            # Run button
            self.run_button = ttk.Button(frame, text="Run", command=self._run)
            self.run_button.grid(row=8, column=0, columnspan=3, pady=15)

            # Progress
            self.progress_var = tk.StringVar(value="Ready")
            ttk.Label(frame, textvariable=self.progress_var, wraplength=550).grid(row=9, column=0, columnspan=3, sticky=tk.W, **padding)

            frame.columnconfigure(1, weight=1)

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

        def _make_config(self) -> PipelineConfig:
            return PipelineConfig(
                input=Path(self.input_var.get()),
                output_dir=Path(self.output_var.get()),
                model_dir=Path(self.model_var.get()),
                seg_seconds=self.seg_var.get(),
                burn_subs=self.burn_var.get(),
                subtitle_font=self.font_var.get(),
                subtitle_font_path=get_default_font_path(),
                subtitle_fontsize=self.font_size_var.get(),
                subtitle_pos_y=self.pos_y_var.get(),
            )

        def _progress(self, step: Step, current: int, total: int, message: str) -> None:
            text = f"[{current}/{total}] {step.value}: {message}"
            self.progress_var.set(text)
            self.root.update_idletasks()

        def _run(self) -> None:
            if not self.input_var.get():
                messagebox.showerror("Error", "Please select an input video.")
                return

            self.run_button.config(state=tk.DISABLED)
            self.progress_var.set("Starting...")

            config = self._make_config()

            def target() -> None:
                try:
                    run_pipeline(config, self._progress)
                    self.root.after(0, self._on_success)
                except Exception as exc:  # noqa: BLE001
                    self.root.after(0, lambda e=exc: self._on_error(e))

            thread = threading.Thread(target=target, daemon=True)
            thread.start()

        def _on_success(self) -> None:
            self.run_button.config(state=tk.NORMAL)
            messagebox.showinfo("Done", "Pipeline completed successfully.")

        def _on_error(self, exc: Exception) -> None:
            self.run_button.config(state=tk.NORMAL)
            messagebox.showerror("Error", f"Pipeline failed:\n{exc}")
