from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    OPERATIONAL_ERROR = 1
    INPUT_ERROR = 2
    DECRYPTION_ERROR = 3
    RESTORE_INTEGRITY_ERROR = 4
    USER_ABORT = 5


class PersonaError(Exception):
    """Base exception for Persona."""

    exit_code = ExitCode.OPERATIONAL_ERROR


class UnsupportedFormatError(PersonaError):
    """Raised when a file format is unsupported."""

    exit_code = ExitCode.INPUT_ERROR


class InputFileError(PersonaError):
    """Raised when an input file is missing, unreadable, or invalid for its declared format."""

    exit_code = ExitCode.INPUT_ERROR


class InputValidationError(PersonaError):
    """Raised when user-supplied CLI options are invalid."""

    exit_code = ExitCode.INPUT_ERROR


class PasswordResolutionError(PersonaError):
    """Raised when the password cannot be resolved from prompt or environment."""

    exit_code = ExitCode.DECRYPTION_ERROR


class KeystoreError(PersonaError):
    """Base class for keystore-related failures."""

    exit_code = ExitCode.DECRYPTION_ERROR


class CorruptKeystoreError(KeystoreError):
    """Raised when the keystore structure is malformed or unreadable."""


class KeystoreDecryptionError(KeystoreError):
    """Raised when the keystore cannot be decrypted with the supplied password."""


class MapError(PersonaError):
    """Base class for encrypted map failures."""


class CorruptMapError(MapError):
    """Raised when the map file or decrypted payload is malformed."""

    exit_code = ExitCode.INPUT_ERROR


class MapDecryptionError(MapError):
    """Raised when the encrypted map cannot be decrypted with the supplied password."""

    exit_code = ExitCode.DECRYPTION_ERROR


class ReviewAbortedError(PersonaError):
    """Raised when the interactive review is aborted."""

    exit_code = ExitCode.USER_ABORT


class PlaceholderValidationError(PersonaError):
    """Raised when a placeholder is invalid or tampered with."""

    exit_code = ExitCode.RESTORE_INTEGRITY_ERROR


class RestoreIntegrityError(PersonaError):
    """Raised when restore encounters integrity failures severe enough to stop processing."""

    exit_code = ExitCode.RESTORE_INTEGRITY_ERROR


class StrictBindingFailureError(RestoreIntegrityError):
    """Raised when strict document binding checks refuse the restore before output generation."""


class DetectionUnavailableError(PersonaError):
    """Raised when local detection cannot be initialized."""


class LLMBackendError(PersonaError):
    """Raised when the configured local LLM backend is unavailable or fails."""


class LLMOutputValidationError(LLMBackendError):
    """Raised when the local LLM returns output that cannot be validated."""


class DocumentProcessingError(PersonaError):
    """Raised when a supported file cannot be processed reliably."""

    exit_code = ExitCode.INPUT_ERROR


class StorageError(PersonaError):
    """Raised when Persona local-app storage cannot be read or written."""
