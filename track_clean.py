from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from track_log import logger
from track_geo import CoordinateSystem, WGS84, haversine_distance, normalize_points

class InsufficientTrackError(ValueError):
    pass

@dataclass
class CleanOptions:
    min_segment_m: float = 0.5
    spike_ratio: float = 2.5
    spike_min_segment_m: float = 3.0
    max_spike_passes: int = 8
    min_points: int = 2

@dataclass
class RemovedPoint:
    index: int
    lon: float
    lat: float
    reason: str

@dataclass
class CleanResult:
    points: List[List[float]]
    removed: List[RemovedPoint] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    crs: CoordinateSystem = WGS84

    @property
    def removed_count(self) -> int:
        return len(self.removed)

    def removed_reason_counts(self) -> dict:
        counts: dict = {}
        for item in self.removed:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return counts

def _merge_duplicates(points: List[List[float]], min_segment_m: float, removed: List[RemovedPoint]) -> List[List[float]]:
    if not points:
        return []
    merged = [points[0]]
    for idx in range(1, len(points)):
        cur = points[idx]
        prev = merged[-1]
        dist = haversine_distance(prev[1], prev[0], cur[1], cur[0])
        if dist < min_segment_m:
            removed.append(RemovedPoint(idx, cur[0], cur[1], 'duplicate_or_too_close'))
            continue
        merged.append(cur)
    return merged

def _remove_spikes(points: List[List[float]], options: CleanOptions, removed: List[RemovedPoint]) -> List[List[float]]:
    current = points
    for _ in range(max(1, options.max_spike_passes)):
        if len(current) < 3:
            return current
        keep = [current[0]]
        found = False
        for i in range(1, len(current) - 1):
            prev, cur, nxt = (keep[-1], current[i], current[i + 1])
            d_prev = haversine_distance(prev[1], prev[0], cur[1], cur[0])
            d_next = haversine_distance(cur[1], cur[0], nxt[1], nxt[0])
            d_direct = haversine_distance(prev[1], prev[0], nxt[1], nxt[0])
            if d_prev >= options.spike_min_segment_m and d_next >= options.spike_min_segment_m and (d_direct > 0) and (d_prev + d_next > options.spike_ratio * d_direct):
                removed.append(RemovedPoint(i, cur[0], cur[1], 'geometric_spike'))
                found = True
                continue
            keep.append(cur)
        keep.append(current[-1])
        current = keep
        if not found:
            return current
    return current

def clean_track(points: Sequence[Sequence[float]], options: Optional[CleanOptions]=None, crs: CoordinateSystem=WGS84, strict: bool=True) -> CleanResult:
    options = options or CleanOptions()
    result = CleanResult(points=[], crs=crs)
    normalized = normalize_points(points)
    if not normalized:
        result.notes.append('输入轨迹为空')
        if strict:
            raise InsufficientTrackError('轨迹为空，无法生成跑步数据')
        return result
    if len(normalized) < options.min_points:
        result.notes.append(f'输入点数不足: {len(normalized)}')
        if strict:
            raise InsufficientTrackError(f'轨迹点数不足（{len(normalized)} < {options.min_points}）')
        result.points = normalized
        return result
    dereplicated = _merge_duplicates(normalized, options.min_segment_m, result.removed)
    despiked = _remove_spikes(dereplicated, options, result.removed)
    if len(despiked) < options.min_points:
        result.notes.append(f'清洗后点数不足: {len(despiked)}')
        if strict:
            raise InsufficientTrackError(f'清洗后轨迹点数不足（{len(despiked)}），原始 {len(normalized)} 点')
        result.points = despiked
        return result
    result.points = despiked
    if result.removed:
        result.notes.append(f'清洗剔除 {result.removed_count} 点: {result.removed_reason_counts()}')
        logger.info(f'轨迹清洗：原始 {len(normalized)} 点 -> {len(despiked)} 点，剔除 {result.removed_count} 点')
    return result
