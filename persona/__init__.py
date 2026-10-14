"""Persona: reversible anonymization for the "share with an AI, get the result back" loop."""

from persona.engine import anonymize_text, verify
from persona.restore import restore_text
from persona.vault import Vault

__version__ = "0.2.0"
__all__ = ["Vault", "__version__", "anonymize_text", "restore_text", "verify"]
