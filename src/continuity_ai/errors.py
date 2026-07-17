"""Controlled public errors for the vertical skeleton."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class PublicError(Exception):
    code: str
    public_message: str
    object_id: str | None = None
    def __str__(self) -> str:
        suffix = f" ({self.object_id})" if self.object_id else ""
        return f"{self.code}: {self.public_message}{suffix}"
    def to_dict(self) -> dict[str, str | None]:
        return {"code": self.code, "message": self.public_message, "object_id": self.object_id}

class ValidationError(PublicError):
    def __init__(self, object_id: str | None = None) -> None:
        super().__init__("validation_error", "Continuity AI couldn’t complete this request safely. Nothing was changed.", object_id)
class VaultLockedError(PublicError):
    def __init__(self) -> None:
        super().__init__("vault_locked", "Unlock the project vault to continue.")
class VaultAuthError(PublicError):
    def __init__(self) -> None:
        super().__init__("vault_auth_failed", "Continuity AI couldn’t complete this request safely. Nothing was changed.")
class VaultAlreadyExistsError(PublicError):
    def __init__(self) -> None:
        super().__init__("vault_already_exists", "A project vault already exists at this location. Unlock it instead of creating a new one.")
class InsufficientEvidenceError(PublicError):
    def __init__(self) -> None:
        super().__init__("insufficient_evidence", "I couldn’t find that document in the project sources currently available to Continuity AI.")
class ProviderError(PublicError):
    def __init__(self) -> None:
        super().__init__("provider_error", "Continuity AI couldn’t complete this request safely. Nothing was changed.")
class ExternalInformationUnavailableError(PublicError):
    def __init__(self) -> None:
        super().__init__("external_information_unavailable", "I can’t check current external information because web access is not available in this version.")
