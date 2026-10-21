"""Hugging Face Spaces entry point (Gradio SDK).

A Gradio Space runs `python space_app.py` and serves whatever listens on port 7860. ReturnGuard is a Flask app,
so this just starts it with gunicorn: one worker, because the models live in memory and returns are processed
by an in-process background thread.
"""
import os
import sys

os.execvp(sys.executable, [
    sys.executable, "-m", "gunicorn",
    "--workers", "1", "--threads", "4", "--timeout", "180",
    "--bind", f"0.0.0.0:{os.getenv('PORT', '7860')}",
    "app:app",
])
