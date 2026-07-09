"""Pydantic data contracts (design section 3), serialized as JSON.

M0 exports only the :class:`Blueprint`. The world-bible, screenplay,
storyboard and timeline schemas (3.2-3.5) arrive in later milestones.
"""

from __future__ import annotations

from ..blueprint import Blueprint

__all__ = ["Blueprint"]
