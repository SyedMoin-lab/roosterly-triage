from typing import ClassVar


class HelpdeskError(Exception):
    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class AuthenticationError(HelpdeskError):
    pass


class RequestRejectedError(HelpdeskError):
    pass


class NotFoundError(HelpdeskError):
    pass


class AlreadyHandledError(HelpdeskError):
    pass


class ProtocolViolationError(HelpdeskError):
    pass


class WriteOutcomeUnknownError(HelpdeskError):
    pass


class ValidationFailedError(HelpdeskError):
    def __init__(
        self,
        message: str,
        *,
        problems: list[object],
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code)
        self.problems = problems


class HelpdeskUnavailableError(HelpdeskError):
    retryable: ClassVar[bool] = True


class ServiceUnavailableError(HelpdeskUnavailableError):
    pass


class ConnectionFailedError(HelpdeskUnavailableError):
    pass


class RateLimitedError(HelpdeskUnavailableError):
    def __init__(
        self,
        message: str,
        *,
        retry_after: float,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code)
        self.retry_after = retry_after
