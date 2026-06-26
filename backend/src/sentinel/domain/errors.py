class DomainError(Exception):
    """Base class for all domain-level errors. The API layer maps these to the
    SPEC §5 error envelope; they are never leaked as raw 500s."""


class ValidationError(DomainError):
    """An entity or value object violated one of its invariants."""


class NotFoundError(DomainError):
    """A requested entity does not exist. Mapped to a 404 at the API boundary."""
