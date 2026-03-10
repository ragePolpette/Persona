from __future__ import annotations

from pathlib import Path

APP_NAME = "persona"
MAP_VERSION = 1
KEYSTORE_VERSION = 1
DEFAULT_SPACY_MODEL = "en_core_web_sm"
DEFAULT_ENABLED_ENTITIES = ("PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER")
CONFIG_DIR = Path.home() / ".persona"
KEYSTORE_PATH = CONFIG_DIR / "keystore.json"
LOCAL_APP_DATA_DIR = CONFIG_DIR / "workspace"
DOCUMENTS_INDEX_PATH = LOCAL_APP_DATA_DIR / "documents.json"
DEFAULT_LLM_BACKEND = "qwen-ollama"
DEFAULT_LLM_MODEL = "qwen3:4b"
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_LLM_CLI = "llama-cli"
