from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ExtractResult:
    text: str
    confidence: float
    dropped_reason: Optional[str] = None


@dataclass
class PipelineResult:
    status: str
    message: str
    chars: int = 0
