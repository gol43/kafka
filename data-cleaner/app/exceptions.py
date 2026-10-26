class DataCleanerError(Exception):
    """Base exception for expected Data Cleaner failures."""


class InvalidDialogError(DataCleanerError):
    """The received dialog does not contain all mandatory data."""


class UcpUnavailableError(DataCleanerError):
    """UCP could not enrich the dialog with mandatory information."""
