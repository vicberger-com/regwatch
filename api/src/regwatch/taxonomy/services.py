"""Service layer; other modules call this module only through here (ADR-0001)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from regwatch.taxonomy.attribute_validator import (
    AttributeValidationError,
    AttributeValidator,
    FieldError,
    ValidatedAttributes,
)
from regwatch.taxonomy.cache import TaxonomyCache, bump_version

__all__ = [
    "AttributeValidationError", "AttributeValidator", "FieldError", "ValidatedAttributes",
    "commit_change", "taxonomy_cache", "validate_attributes",
]  # fmt: skip

# One per process: the api today, Celery workers when they land (BL-64).
taxonomy_cache = TaxonomyCache()


async def validate_attributes(session: AsyncSession, attributes: object) -> ValidatedAttributes:
    """Validate ``item.attributes``; raises :class:`AttributeValidationError` naming fields."""
    return (await taxonomy_cache.validator(session)).validate(attributes)


async def commit_change(session: AsyncSession) -> int:
    """Bump ``taxonomy.version``, commit the caller's taxonomy write, drop this process's cache."""
    version = await bump_version(session)
    await session.commit()
    taxonomy_cache.invalidate()
    return version
