"""ASGI entrypoint: ``uvicorn chama.main:app``."""

from .api import create_app

app = create_app()
