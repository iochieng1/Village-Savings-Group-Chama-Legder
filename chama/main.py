"""ASGI entrypoint: ``uvicorn chama.main:app``."""

import logging

from .api import create_app

# Show SMS messages from the development gateway in the server log.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = create_app()
