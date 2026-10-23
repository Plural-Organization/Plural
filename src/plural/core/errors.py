from typing import ClassVar

from plural.protocol.envelope import ErrorCode, ErrorInfo


class DomainError(Exception):
    code: ClassVar[ErrorCode] = ErrorCode.INTERNAL

    def info(self) -> ErrorInfo:
        return ErrorInfo(code=self.code, message=str(self) or self.code.value)


class Unauthorized(DomainError):
    code = ErrorCode.UNAUTHORIZED


class Forbidden(DomainError):
    code = ErrorCode.FORBIDDEN


class Invalid(DomainError):
    code = ErrorCode.INVALID


class Conflict(DomainError):
    code = ErrorCode.CONFLICT


class NotFound(DomainError):
    code = ErrorCode.NOT_FOUND
