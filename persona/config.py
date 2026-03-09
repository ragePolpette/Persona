from __future__ import annotations

from pathlib import Path

APP_NAME = "persona"
MAP_VERSION = 1
KEYSTORE_VERSION = 1
DEFAULT_SPACY_MODEL = "en_core_web_sm"
DEFAULT_ENABLED_ENTITIES = ("PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER")
CONFIG_DIR = Path.home() / ".persona"
KEYSTORE_PATH = CONFIG_DIR / "keystore.json"

