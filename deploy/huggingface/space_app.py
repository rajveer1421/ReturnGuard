"""Hugging Face Spaces entry point (Gradio SDK on ZeroGPU hardware).

On a free account a Gradio Space has to run on ZeroGPU, which needs a Gradio server and at least one
`@spaces.GPU` function. ReturnGuard runs on CPU and is a Flask app, so this file:
  - defines a no-op GPU function (never called, so no GPU quota is used),
  - starts Gradio's server, and
  - sends every request outside Gradio's own /gradio_api/ routes to the Flask app.
"""
import spaces  # must be imported before torch (the Flask app imports it)

import gradio as gr
from a2wsgi import WSGIMiddleware

from app import app as flask_app


@spaces.GPU(duration=1)
def _noop():
    """ZeroGPU refuses to start without one decorated function. ReturnGuard never calls it."""


flask_asgi = WSGIMiddleware(flask_app)


class FlaskFirst:
    """Route requests to Flask before Gradio's router, so the order routes are registered in doesn't matter."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not scope["path"].startswith("/gradio_api"):
            await flask_asgi(scope, receive, send)
        else:
            await self.app(scope, receive, send)


demo = gr.Server(title="ReturnGuard")
demo.add_middleware(FlaskFirst)

if __name__ == "__main__":
    demo.launch(ssr_mode=False)
