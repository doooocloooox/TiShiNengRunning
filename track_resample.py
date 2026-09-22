from __future__ import annotations
import math
import random
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple
from track_log import logger
from track_clean import CleanOptions, clean_track
from track_geo import LocalProjection, haversine_distance, normalize_points
from track_metrics import steps_for_interval, stride_for_speed

class TrackGenerationError(ValueError):
    pass

@dataclass
class PointRisk:
    f: bool = False
    m: bool = False
    h: bool = False

    def as_dict(self) -> dict:
        return {'f': self.f, 'm': self.m, 'h': self.h}

@dataclass
class ResampleOptions:
    sample_interval_s: float = 1.0
    interval_jitter_s: float = 0.0
    speed_jitter: float = 0.08
    speed_min_factor: float = 0.8
    speed_max_factor: float = 1.25
    loop_mode: str = 'pingpong'
    stride_jitter: float = 0.0
    pause_tail_points: int = 2
    max_samples: int = 200000
    clean_options: Optional[CleanOptions] = None

@dataclass
class TrackSample:
    lon: float
    lat: float
    t_ms: float
    dt_ms: float
    offset_s: float
    distance_m: float
    cumulative_m: float
    speed_mps: float
    paused: bool = False
    risk: PointRisk = field(default_factory=PointRisk)

    def geo(self) -> List[float]:
        return [self.lon, self.lat]

@dataclass
class ResampledTrack:
    samples: List[TrackSample]
    target_distance_m: float
    base_speed_mps: float
    plan_use_time_s: float
    start_timestamp_ms: float
    source_point_count: int
    cleaned_point_count: int
    notes: List[str] = field(default_factory=list)

    @property
    def points(self) -> List[List[float]]:
        return [s.geo() for s in self.samples]

    @property
    def timestamps_ms(self) -> List[float]:
        return [s.t_ms for s in self.samples]

    @property
    def total_distance_m(self) -> float:
        return self.samples[-1].cumulative_m if self.samples else 0.0

    @property
    def start_timestamp(self) -> float:
        return self.samples[0].t_ms if self.samples else self.start_timestamp_ms

    @property
    def end_timestamp(self) -> float:
        return self.samples[-1].t_ms if self.samples else self.start_timestamp_ms

    @property
    def elapsed_s(self) -> float:
        return self.samples[-1].offset_s if self.samples else 0.0

    @property
    def avg_speed_mps(self) -> float:
        elapsed = self.elapsed_s
        return self.total_distance_m / elapsed if elapsed > 0 else 0.0

    @property
    def total_steps(self) -> int:
        return int(round(sum((s.distance_m / stride_for_speed(s.speed_mps) for s in self.samples))))

    def step_samples(self) -> List[Tuple[float, float, float]]:
        rows: List[Tuple[float, float, float]] = []
        for i, s in enumerate(self.samples):
            start = 0.0 if i == 0 else self.samples[i - 1].offset_s
            rows.append((start, s.offset_s - start, s.distance_m / stride_for_speed(s.speed_mps)))
        return rows

class _PathWalker:

    def __init__(self, points: Sequence[Sequence[float]], loop_mode: str):
        self.points = [list(p) for p in points]
        self.loop_mode = loop_mode
        if loop_mode == 'repeat':
            closing_distance = haversine_distance(self.points[-1][1], self.points[-1][0], self.points[0][1], self.points[0][0])
            if closing_distance > 1e-09:
                self.points.append(list(self.points[0]))
        self.seg_lengths: List[float] = []
        for i in range(len(self.points) - 1):
            a, b = (self.points[i], self.points[i + 1])
            self.seg_lengths.append(haversine_distance(a[1], a[0], b[1], b[0]))
        self.seg_index = 0
        self.offset_in_seg = 0.0
        self.direction = 1
        self.laps = 0
        self._projection = LocalProjection(self.points[0][0], self.points[0][1])

    def current_point(self) -> List[float]:
        if self.seg_index >= len(self.seg_lengths):
            return list(self.points[-1])
        a = self.points[self.seg_index]
        b = self.points[self.seg_index + 1]
        seg_len = self.seg_lengths[self.seg_index]
        if seg_len <= 0:
            return list(a)
        ratio = min(1.0, max(0.0, self.offset_in_seg / seg_len))
        lon, lat = self._projection.interpolate(a[0], a[1], b[0], b[1], ratio)
        return [lon, lat]

    def advance(self, distance_m: float) -> None:
        remaining = distance_m
        while remaining > 1e-09:
            if self.seg_index >= len(self.seg_lengths):
                self._handle_path_end()
                continue
            seg_len = self.seg_lengths[self.seg_index]
            if seg_len <= 0:
                self.seg_index += 1
                self.offset_in_seg = 0.0
                continue
            available = seg_len - self.offset_in_seg
            if available > remaining:
                self.offset_in_seg += remaining
                remaining = 0.0
            else:
                remaining -= available
                self.seg_index += 1
                self.offset_in_seg = 0.0

    def _handle_path_end(self) -> None:
        if self.loop_mode == 'pingpong':
            self.points = list(reversed(self.points))
            self.seg_lengths = list(reversed(self.seg_lengths))
            self.seg_index = 0
            self.offset_in_seg = 0.0
            self.direction *= -1
            self._projection = LocalProjection(self.points[0][0], self.points[0][1])
            self.laps += 1
            return
        if self.loop_mode == 'repeat':
            self.seg_index = 0
            self.offset_in_seg = 0.0
            self.laps += 1
            return
        raise TrackGenerationError(f'未知的 loop_mode: {self.loop_mode}')



def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)

def _phase_factor(distance_m: float, total_distance_m: float, transition_ratio: float = 0.04) -> float:
    ratio = distance_m / total_distance_m if total_distance_m > 0 else 0.0
    boundaries = (0.12, 0.25, 0.48, 0.60, 0.86)
    factors = (0.90, 1.12, 0.96, 1.18, 0.94, 0.88)
    index = next((i for i, boundary in enumerate(boundaries) if ratio < boundary), len(factors) - 1)
    for boundary_index, boundary in enumerate(boundaries, start=1):
        if abs(ratio - boundary) <= transition_ratio:
            progress = _smoothstep((ratio - boundary + transition_ratio) / (2.0 * transition_ratio))
            return factors[boundary_index - 1] + (factors[boundary_index] - factors[boundary_index - 1]) * progress
    return factors[index]

def _make_factor_sampler(rng: random.Random, options: ResampleOptions) -> Callable[[], float]:
    if options.speed_jitter <= 0:
        return lambda: 1.0
    low = max(options.speed_min_factor, 1.0 - 3 * options.speed_jitter)
    high = min(options.speed_max_factor, 1.0 + 3 * options.speed_jitter)

    def sampler() -> float:
        return min(high, max(low, rng.gauss(1.0, options.speed_jitter)))
    return sampler

def resample_track(points: Sequence[Sequence[float]], need_distance_m: float, start_timestamp_ms: float, plan_use_time_s: float, options: Optional[ResampleOptions]=None, rng: Optional[random.Random]=None, risk_resolver: Optional[Callable[[TrackSample], PointRisk]]=None, clean: bool=True) -> ResampledTrack:
    options = options or ResampleOptions()
    rng = rng or random.Random()
    numeric_args = {'need_distance_m': need_distance_m, 'start_timestamp_ms': start_timestamp_ms, 'plan_use_time_s': plan_use_time_s, 'sample_interval_s': options.sample_interval_s, 'interval_jitter_s': options.interval_jitter_s, 'speed_jitter': options.speed_jitter, 'speed_min_factor': options.speed_min_factor, 'speed_max_factor': options.speed_max_factor}
    for name, value in numeric_args.items():
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise TrackGenerationError(f'{name} 必须是有限数值: {value}')
    if need_distance_m <= 0:
        raise TrackGenerationError(f'目标距离必须为正: {need_distance_m}')
    if plan_use_time_s <= 0:
        raise TrackGenerationError(f'计划用时必须为正: {plan_use_time_s}')
    if options.sample_interval_s <= 0:
        raise TrackGenerationError(f'采样间隔必须为正: {options.sample_interval_s}')
    if options.interval_jitter_s < 0:
        raise TrackGenerationError(f'interval_jitter_s 不能为负: {options.interval_jitter_s}')
    if options.speed_jitter < 0:
        raise TrackGenerationError(f'speed_jitter 不能为负: {options.speed_jitter}')
    if options.speed_min_factor <= 0 or options.speed_max_factor <= 0:
        raise TrackGenerationError('速度系数上下限必须为正')
    if options.speed_min_factor > options.speed_max_factor:
        raise TrackGenerationError('speed_min_factor 不能大于 speed_max_factor')
    if not isinstance(options.max_samples, int) or options.max_samples <= 0:
        raise TrackGenerationError(f'max_samples 必须是正整数: {options.max_samples}')
    if not isinstance(options.pause_tail_points, int) or options.pause_tail_points < 0:
        raise TrackGenerationError(f'pause_tail_points 必须是非负整数: {options.pause_tail_points}')
    if options.loop_mode not in ('pingpong', 'repeat'):
        raise TrackGenerationError(f'loop_mode 只能是 pingpong/repeat: {options.loop_mode}')
    normalized = normalize_points(points)
    source_count = len(normalized)
    if clean:
        cleaned = clean_track(normalized, options.clean_options)
        path_points = cleaned.points
        clean_notes = list(cleaned.notes)
        cleaned_count = len(path_points)
    else:
        if len(normalized) < 2:
            raise TrackGenerationError('至少需要两个坐标点')
        path_points = normalized
        clean_notes = []
        cleaned_count = len(path_points)
    if len(path_points) < 2:
        raise TrackGenerationError('清洗后不足以构成折线')
    base_speed = need_distance_m / plan_use_time_s
    if base_speed <= 0 or math.isnan(base_speed) or math.isinf(base_speed):
        raise TrackGenerationError('基准速度非法')
    walker = _PathWalker(path_points, options.loop_mode)
    factor = _make_factor_sampler(rng, options)
    samples: List[TrackSample] = []
    traveled = 0.0
    offset_s = 0.0
    current = walker.current_point()
    while traveled < need_distance_m - 1e-09:
        if len(samples) >= options.max_samples:
            raise TrackGenerationError(f'采样点数量超过上限 {options.max_samples}，请检查目标距离/速度参数')
        phase_factor = _phase_factor(traveled, need_distance_m)
        speed = base_speed * phase_factor * factor()
        if speed <= 0:
            raise TrackGenerationError('采样速度非正')
        if options.interval_jitter_s > 0:
            jitter = rng.uniform(-options.interval_jitter_s, options.interval_jitter_s)
            dt_s = max(0.05, options.sample_interval_s + jitter)
        else:
            dt_s = options.sample_interval_s
        remaining = need_distance_m - traveled
        nominal_distance = speed * dt_s
        if nominal_distance >= remaining:
            distance = remaining
            dt_s = distance / speed
        else:
            distance = nominal_distance
        walker.advance(distance)
        offset_s += dt_s
        traveled += distance
        current = walker.current_point()
        sample = TrackSample(lon=current[0], lat=current[1], t_ms=start_timestamp_ms + offset_s * 1000.0, dt_ms=dt_s * 1000.0, offset_s=offset_s, distance_m=distance, cumulative_m=traveled, speed_mps=speed)
        if risk_resolver is not None:
            sample.risk = risk_resolver(sample) or PointRisk()
        samples.append(sample)
    track = ResampledTrack(samples=samples, target_distance_m=need_distance_m, base_speed_mps=base_speed, plan_use_time_s=plan_use_time_s, start_timestamp_ms=start_timestamp_ms, source_point_count=source_count, cleaned_point_count=cleaned_count, notes=clean_notes)
    if options.pause_tail_points > 0 and len(samples) > 1:
        for s in samples[-options.pause_tail_points:]:
            s.paused = True
    logger.info(f'轨迹重采样完成：目标 {need_distance_m:.1f}m / 计划 {plan_use_time_s:.0f}s，实际 {track.total_distance_m:.1f}m / {track.elapsed_s:.0f}s，采样 {len(samples)} 点，均速 {track.avg_speed_mps:.2f} m/s')
    return track

def iter_stride_steps(track: ResampledTrack) -> List[float]:
    return [s.distance_m / stride_for_speed(s.speed_mps) for s in track.samples]
