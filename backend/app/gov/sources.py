from __future__ import annotations

from app.constants import INTERNAL, PINNED


def get_internal(dataset_id: str) -> dict | None:
    return next((item for item in INTERNAL if item["id"] == dataset_id), None)


def get_pinned(provider: str, dataset_id: str) -> dict | None:
    return next((item for item in PINNED if item["provider"] == provider and item["id"] == dataset_id), None)
