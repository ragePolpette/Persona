class PersonaError(Exception):
    """Base exception for Persona."""


class UnsupportedFormatError(PersonaError):
    """Raised when a file format is unsupported."""


class ReviewAbortedError(PersonaError):
    """Raised when the interactive review is aborted."""


class PlaceholderValidationError(PersonaError):
    """Raised when a placeholder is invalid or tampered with."""


class DetectionUnavailableError(PersonaError):
    """Raised when local detection cannot be initialized."""

