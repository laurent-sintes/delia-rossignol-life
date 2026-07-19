from __future__ import annotations


class DeliaLifeError(Exception):
    """Base exception for expected domain and application failures."""


class ValidationError(DeliaLifeError, ValueError):
    """Raised when an input violates a declared contract or invariant."""


class ConflictError(DeliaLifeError, ValueError):
    """Raised when a requested mutation conflicts with validated state."""


class TransitionError(DeliaLifeError, ValueError):
    """Raised when a workflow state transition is not allowed."""


class TransactionError(DeliaLifeError, RuntimeError):
    """Raised when a group of filesystem mutations cannot be committed."""
