from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from track_geo import haversine_distance, normalize_points, point_list_distance
from track_pipeline import OfflineTrackResult, generate_offline_track
from track_resample import ResampleOptions

@dataclass(frozen=True)
class HistoricalRoutePool:
    routes: Tuple[Tuple[Tuple[float, float], ...], ...]
    bounds: Tuple[float, float, float, float]

    @classmethod
    def from_routes(cls, routes: Sequence[Sequence[Sequence[float]]]) -> 'HistoricalRoutePool':
        valid = []
        for route in routes:
            points = normalize_points(route)
            if len(points) >= 2 and point_list_distance(points) > 0:
                valid.append(tuple((p[0], p[1]) for p in points))
        if not valid:
            raise ValueError('至少需要一条有效历史路线')
        all_points = [p for route in valid for p in route]
        return cls(tuple(valid), (min(p[0] for p in all_points), min(p[1] for p in all_points), max(p[0] for p in all_points), max(p[1] for p in all_points)))

    @staticmethod
    def _quality(route: Sequence[Sequence[float]]) -> float:
        length = point_list_distance(route)
        chord = haversine_distance(route[0][1], route[0][0], route[-1][1], route[-1][0])
        return max(1.0, length / max(chord, 1.0)) * math.log1p(len(route))

    def choose(self, rng: random.Random) -> List[List[float]]:
        weights = [self._quality(route) for route in self.routes]
        selected = rng.choices(self.routes, weights=weights, k=1)[0]
        points = [list(p) for p in selected]
        if rng.random() < 0.5:
            points.reverse()
        return points

    def contains(self, point: Sequence[float], margin_m: float = 30.0) -> bool:
        lon, lat = point
        min_lon, min_lat, max_lon, max_lat = self.bounds
        lat_margin = margin_m / 111320.0
        lon_margin = margin_m / max(111320.0 * math.cos(math.radians(lat)), 1.0)
        return min_lon - lon_margin <= lon <= max_lon + lon_margin and min_lat - lat_margin <= lat <= max_lat + lat_margin

def generate_historical_pool_track(pool: HistoricalRoutePool, *, target_distance_m: float, plan_use_time_s: float, start_timestamp_ms: float = 0.0, seed: int = 0, resample_options: Optional[ResampleOptions] = None, area_margin_m: float = 30.0) -> OfflineTrackResult:
    route = pool.choose(random.Random(seed))
    result = generate_offline_track(route, target_distance_m=target_distance_m, plan_use_time_s=plan_use_time_s, start_timestamp_ms=start_timestamp_ms, seed=seed, resample_options=resample_options)
    outside = sum(1 for sample in result.track.samples if not pool.contains(sample.geo(), area_margin_m))
    if outside:
        result.notes.append(f'区域包络外点数: {outside}')
    return result