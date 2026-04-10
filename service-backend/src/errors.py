"""
Application-wide exception hierarchy.

Raise the most specific subclass so callers can handle categories of failures
without catching bare `Exception`.
"""


class FinAnalysisError(Exception):
    """Base exception for all application errors."""


class ConfigurationError(FinAnalysisError):
    """Raised when required configuration (API keys, paths) is missing or invalid."""


class ExtractionError(FinAnalysisError):
    """Raised when financial data cannot be extracted from a source document."""


class ValidationError(FinAnalysisError):
    """
    Raised when a document is rejected because it does not contain
    readable financial statements or extraction confidence is too low.
    """


class AnalysisError(FinAnalysisError):
    """Raised when the AI commentary or next-steps generation fails."""


class ReportError(FinAnalysisError):
    """Raised when the Word report cannot be generated."""
