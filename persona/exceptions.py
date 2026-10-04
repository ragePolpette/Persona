from __future__ import annotations


class PersonaError(Exception):
    """Base class for errors that should be shown to the user as a clean message."""


class InputError(PersonaError):
    """Bad input: unsupported file, unknown kind, missing file."""


class VaultError(PersonaError):
    """Problems opening, reading or writing a vault."""


class WrongPasswordError(VaultError):
    """The password is wrong, or the vault was tampered with (AES-GCM cannot tell them apart)."""
