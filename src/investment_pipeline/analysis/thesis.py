"""Thesis loading (YAML-configured investment thesis)."""

from __future__ import annotations

from pathlib import Path

import yaml

from investment_pipeline.config import ROOT
from investment_pipeline.models import Thesis

DEFAULT_THESIS_PATH = ROOT / "thesis" / "ai_workflow_automation.yaml"


def load_thesis(path: Path | None = None) -> Thesis:
    p = path or DEFAULT_THESIS_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return Thesis.model_validate(data)
