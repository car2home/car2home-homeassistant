"""Device slug builder — mirrors the app's Mqtt naming convention.

Identifier format: `car2home_{manufacturer}_{model}[_{N}]`
  - lowercase
  - non-alphanumeric characters collapsed to underscores
  - if the same slug already exists for another ConfigEntry, append `_2`, `_3`, ...

This is the canonical HA device identifier AND the prefix of every entity's
unique_id, so Entity IDs like `sensor.car2home_toyota_corolla_cross_rpm` are
human-readable and stable across restarts.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from .const import DEVICE_SLUG_PREFIX


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify_part(value: str | None) -> str:
    if not value:
        return ""
    s = _NON_ALNUM.sub("_", value.lower()).strip("_")
    return s


def build_base_slug(manufacturer: str | None, model: str | None) -> str:
    parts = [DEVICE_SLUG_PREFIX]
    mfg = slugify_part(manufacturer)
    mdl = slugify_part(model)
    if mfg:
        parts.append(mfg)
    if mdl:
        parts.append(mdl)
    if len(parts) == 1:
        parts.append("vehicle")
    return "_".join(parts)


def build_unique_slug(
    manufacturer: str | None,
    model: str | None,
    existing_slugs: Iterable[str],
) -> str:
    """Return a slug unique within ``existing_slugs`` by appending _2/_3/... if needed."""
    base = build_base_slug(manufacturer, model)
    taken = set(existing_slugs)
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"
