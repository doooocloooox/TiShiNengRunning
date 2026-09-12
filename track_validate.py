from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from track_geo import haversine_distance
from step_buckets import BucketAllocation

@dataclass
class Issue:
    code: str
    message: str
    severity: str = 'error'
    context: dict = field(default_factory=dict)

@dataclass
class ValidationReport:
    ok: bool
    issues: List[Issue] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == 'error']

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == 'warning']

    def summary(self) -> str:
        head = '通过' if self.ok else '未通过'
        return f'轨迹校验{head}：error={len(self.errors)} warning={len(self.warnings)} 指标={self.metrics}'

    def raise_if_failed(self) -> None:
        if not self.ok:
            detail = '; '.join((f'{i.code}: {i.message}' for i in self.errors))
            raise ValueError(f'轨迹校验未通过 -> {detail}')

def _is_finite(value: float) -> bool:
    return isinstance(value, (int, float)) and (not (math.isnan(value) or math.isinf(value)))

def validate_series(points: Sequence[Sequence[float]], timestamps_ms: Sequence[float], distances_m: Optional[Sequence[float]]=None, speeds_mps: Optional[Sequence[float]]=None, cumulative_m: Optional[Sequence[float]]=None, target_distance_m: Optional[float]=None, bucket_allocation: Optional[BucketAllocation]=None, total_steps: Optional[int]=None, summary_coords: Optional[Sequence[Sequence[float]]]=None, distance_eps_m: float=0.5, speed_tolerance_ratio: float=0.001, chord_warning_ratio: float=0.15, initial_interval_s: float=0.0) -> ValidationReport:
    issues: List[Issue] = []
    if len(points) != len(timestamps_ms):
        issues.append(Issue('length_mismatch', f'点数 {len(points)} 与时间戳数 {len(timestamps_ms)} 不一致'))
        return ValidationReport(ok=False, issues=issues, metrics={})
    if not points:
        issues.append(Issue('empty_track', '轨迹为空'))
        return ValidationReport(ok=False, issues=issues, metrics={})
    for idx, p in enumerate(points):
        if not (_is_finite(p[0]) and _is_finite(p[1])):
            issues.append(Issue('non_finite_coord', f'第 {idx} 点坐标非有限值', context={'index': idx}))
    for i in range(1, len(timestamps_ms)):
        dt = timestamps_ms[i] - timestamps_ms[i - 1]
        if not _is_finite(dt) or dt <= 0:
            issues.append(Issue('timestamp_not_increasing', f'第 {i} 点时间戳未严格递增: dt={dt}', context={'index': i, 'dt': dt}))
    computed_cumulative: List[float] = [distances_m[0] if distances_m and len(distances_m) else 0.0]
    chord_total = 0.0
    budget_total = computed_cumulative[0]
    chord_deviations: List[tuple] = []
    if distances_m is not None and speeds_mps is not None and (initial_interval_s > 0):
        first_distance = distances_m[0]
        first_speed = speeds_mps[0]
        expected = first_speed * initial_interval_s
        tol = max(distance_eps_m, abs(expected) * speed_tolerance_ratio)
        if abs(first_distance - expected) > tol:
            issues.append(Issue('speed_distance_mismatch', f'首段 |distance - speed×dt| = {abs(first_distance - expected):.6f} > {tol:.6f}', context={'index': 0, 'distance': first_distance, 'speed': first_speed, 'dt': initial_interval_s}))
    for i in range(1, len(points)):
        chord = haversine_distance(points[i - 1][1], points[i - 1][0], points[i][1], points[i][0])
        chord_total += chord
        dt = (timestamps_ms[i] - timestamps_ms[i - 1]) / 1000.0
        budget = None
        if distances_m is not None:
            budget = distances_m[i] if i < len(distances_m) else None
        speed = None
        if speeds_mps is not None:
            speed = speeds_mps[i] if i < len(speeds_mps) else None
        if budget is not None:
            if budget < -distance_eps_m:
                issues.append(Issue('negative_distance', f'第 {i} 段距离为负: {budget}', context={'index': i}))
            budget_total += budget
            computed_cumulative.append(computed_cumulative[-1] + budget)
            if speed is not None and dt > 0:
                expected = speed * dt
                tol = max(distance_eps_m, abs(expected) * speed_tolerance_ratio)
                if abs(budget - expected) > tol:
                    issues.append(Issue('speed_distance_mismatch', f'第 {i} 段 |distance - speed×dt| = {abs(budget - expected):.6f} > {tol:.6f}', context={'index': i, 'distance': budget, 'speed': speed, 'dt': dt}))
                if chord > 0:
                    chord_deviations.append((i, budget, chord, abs(budget - chord) / chord))
        else:
            computed_cumulative.append(computed_cumulative[-1] + chord)
    if chord_deviations:
        worst = max(chord_deviations, key=lambda x: x[3])
        if worst[3] > chord_warning_ratio:
            issues.append(Issue('chord_deviation', f'{len(chord_deviations)} 段推进量与弦长偏差超过 {chord_warning_ratio * 100:.0f}%，最大在第 {worst[0]} 段：推进 {worst[1]:.3f}m vs 弦长 {worst[2]:.3f}m（{worst[3] * 100:.1f}%，折返/密集折点属正常）', severity='warning', context={'segments': len(chord_deviations), 'worst_index': worst[0]}))
    if cumulative_m is not None:
        for i in range(0, min(len(cumulative_m), len(computed_cumulative))):
            if i > 0 and cumulative_m[i] < cumulative_m[i - 1] - distance_eps_m:
                issues.append(Issue('cumulative_not_monotonic', f'第 {i} 点累计距离回退', context={'index': i}))
            if abs(cumulative_m[i] - computed_cumulative[i]) > max(distance_eps_m, 0.01 * computed_cumulative[i]):
                issues.append(Issue('cumulative_mismatch', f'第 {i} 点累计距离 {cumulative_m[i]:.3f} 与逐段累加 {computed_cumulative[i]:.3f} 不一致', context={'index': i}))
    if target_distance_m is not None:
        actual = budget_total if distances_m is not None else chord_total
        if actual > target_distance_m + distance_eps_m:
            issues.append(Issue('target_distance_exceeded', f'实际距离 {actual:.3f}m 超过目标 {target_distance_m:.3f}m', context={'actual': actual, 'target': target_distance_m}))
    if summary_coords is not None and len(summary_coords) >= 2 and (len(points) >= 1):
        diff_start = haversine_distance(points[0][1], points[0][0], summary_coords[0][1], summary_coords[0][0])
        diff_end = haversine_distance(points[-1][1], points[-1][0], summary_coords[-1][1], summary_coords[-1][0])
        if diff_start > 1.0:
            issues.append(Issue('summary_start_mismatch', f'首点与摘要起点相差 {diff_start:.2f}m'))
        if diff_end > 1.0:
            issues.append(Issue('summary_end_mismatch', f'末点与摘要终点相差 {diff_end:.2f}m'))
    if bucket_allocation is not None:
        expected_total = total_steps if total_steps is not None else bucket_allocation.total_steps
        if sum(bucket_allocation.buckets) != expected_total:
            issues.append(Issue('step_bucket_sum_mismatch', f'步数桶合计 {sum(bucket_allocation.buckets)} != 期望 {expected_total}', context={'buckets': bucket_allocation.buckets}))
    elapsed = ((timestamps_ms[-1] - timestamps_ms[0]) / 1000.0 if len(timestamps_ms) > 1 else 0.0) + initial_interval_s
    distance_total = budget_total if distances_m is not None else chord_total
    metrics = {'points': len(points), 'budget_distance_m': budget_total, 'chord_distance_m': chord_total, 'elapsed_s': elapsed, 'avg_speed_mps': distance_total / elapsed if elapsed > 0 else 0.0}
    ok = not any((i.severity == 'error' for i in issues))
    return ValidationReport(ok=ok, issues=issues, metrics=metrics)

def validate_track(track, bucket_allocation: Optional[BucketAllocation]=None, total_steps: Optional[int]=None, summary_coords: Optional[Sequence[Sequence[float]]]=None, distance_eps_m: float=0.5) -> ValidationReport:
    samples = track.samples
    return validate_series(points=[s.geo() for s in samples], timestamps_ms=[s.t_ms for s in samples], distances_m=[s.distance_m for s in samples], speeds_mps=[s.speed_mps for s in samples], cumulative_m=[s.cumulative_m for s in samples], target_distance_m=track.target_distance_m, bucket_allocation=bucket_allocation, total_steps=total_steps, summary_coords=summary_coords, distance_eps_m=distance_eps_m, initial_interval_s=samples[0].dt_ms / 1000.0 if samples else 0.0)
