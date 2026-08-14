"""Benchmark and detector reports, served straight from disk.

Neither file is generated on request -- both are produced by an explicit run of
`app.eval.harness` and `app.detect.train`. If a report is missing the endpoint
says exactly which command produces it, rather than the UI inventing a number
or silently showing an empty chart.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app.config import settings

router = APIRouter()


def _read(path, command: str) -> dict:
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"{path.name} has not been generated yet. Run: {command}",
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not read {path.name}: {exc}"
        ) from exc


@router.get("/evaluate")
def get_benchmark() -> dict:
    """The 200-incident benchmark across all four policies."""
    return _read(settings.benchmark_path, "python -m app.eval.harness")


@router.get("/detector")
def get_detector_report() -> dict:
    """Rules vs LightGBM vs GNN on held-out rings, plus ring ARI."""
    return _read(settings.detector_report_path, "python -m app.detect.train")
