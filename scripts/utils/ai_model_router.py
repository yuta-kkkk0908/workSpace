#!/usr/bin/env python3
from __future__ import annotations

from utils.platform_core_bootstrap import ensure_platform_core_importable

ensure_platform_core_importable()

from platform_core.model_router import resolve_model
