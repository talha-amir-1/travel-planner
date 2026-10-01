"""Typed errors raised by the tools."""


class ToolError(Exception):
    """Base class for all tool failures."""


class NotFoundError(ToolError):
    """The requested entity (city, route, ...) does not exist."""


class ExternalAPIError(ToolError):
    """An upstream API call failed."""

    def __init__(self, service: str, message: str, status_code: int | None = None):
        self.service = service
        self.status_code = status_code
        super().__init__(f"{service}: {message}")
