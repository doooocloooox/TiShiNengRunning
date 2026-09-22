"""Offline trajectory pipeline for reproducible coursework experiments."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional, Sequence

from track_clean import CleanOptions, CleanResult, clean_track
from track_resample import ResampleOptions, ResampledTrack, resample_track
from track_validate import ValidationReport, validate_track

@dataclass
class OfflineTrackResult:
    cleaned: CleanResult
    track: ResampledTrack
    validation: ValidationReport
    seed: int
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.validation.ok

    def summary(self) -> dict:
        return {"ok": self.ok, "seed": self.seed, "source_points": self.track.source_point_count, "cleaned_points": self.track.cleaned_point_count, "generated_points": len(self.track.samples), "distance_m": self.track.total_distance_m, "elapsed_s": self.track.elapsed_s, "avg_speed_mps": self.track.avg_speed_mps, "validation": self.validation.metrics, "issues": [issue.code for issue in self.validation.issues]}

def generate_offline_track(points: Sequence[Sequence[float]], *, target_distance_m: float, plan_use_time_s: float, start_timestamp_ms: float = 0.0, seed: int = 0, clean_options: Optional[CleanOptions] = None, resample_options: Optional[ResampleOptions] = None) -> OfflineTrackResult:
    """Generate and validate a track without network, account, or upload side effects."""
    cleaned = clean_track(points, options=clean_options, strict=True)
    options = resample_options or ResampleOptions()
    options.clean_options = None
    track = resample_track(cleaned.points, need_distance_m=target_distance_m, start_timestamp_ms=start_timestamp_ms, plan_use_time_s=plan_use_time_s, options=options, rng=random.Random(seed), clean=False)
    validation = validate_track(track)
    notes = list(cleaned.notes)
    if not validation.ok:
        notes.append("生成结果未通过轨迹校验")
    return OfflineTrackResult(cleaned, track, validation, seed, notes)
