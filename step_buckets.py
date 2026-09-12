from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple
DEFAULT_BUCKET_SECONDS = 60.0

@dataclass
class StepInterval:
    start_offset_s: float
    duration_s: float
    steps: float

    def __post_init__(self) -> None:
        for name, value in (('start_offset_s', self.start_offset_s), ('duration_s', self.duration_s), ('steps', self.steps)):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'{name} 必须是有限数值')
        if self.start_offset_s < 0:
            raise ValueError('start_offset_s 不能为负')
        if self.duration_s < 0:
            raise ValueError('duration_s 不能为负')
        if self.steps < 0:
            raise ValueError('steps 不能为负')

@dataclass
class BucketAllocation:
    buckets: List[int] = field(default_factory=list)
    total_steps: int = 0
    estimated: bool = False
    bucket_seconds: float = DEFAULT_BUCKET_SECONDS

    @property
    def bucket_count(self) -> int:
        return len(self.buckets)

def _bucket_index(offset_s: float, bucket_seconds: float) -> int:
    return int(offset_s // bucket_seconds)

def _largest_remainder(values: Sequence[float], target_total: int) -> List[int]:
    floors = [int(v) for v in values]
    remainder = target_total - sum(floors)
    if remainder == 0:
        return floors
    if remainder > 0:
        order = sorted(range(len(values)), key=lambda i: values[i] - floors[i], reverse=True)
        for i in order[:remainder]:
            floors[i] += 1
        return floors
    order = sorted(range(len(values)), key=lambda i: values[i] - floors[i])
    need = -remainder
    for i in order:
        if need == 0:
            break
        if floors[i] > 0:
            floors[i] -= 1
            need -= 1
    return floors

def allocate_steps(intervals: Sequence[StepInterval], bucket_seconds: float=DEFAULT_BUCKET_SECONDS, estimated: bool=False, total_steps: Optional[int]=None) -> BucketAllocation:
    if bucket_seconds <= 0:
        raise ValueError('bucket_seconds 必须为正')
    if not intervals:
        return BucketAllocation(buckets=[], total_steps=0, estimated=estimated, bucket_seconds=bucket_seconds)
    bucket_count = 1
    for iv in intervals:
        end_offset = iv.start_offset_s + iv.duration_s
        if iv.duration_s > 0:
            touched = max(1, int(math.ceil(end_offset / bucket_seconds)))
        else:
            touched = _bucket_index(iv.start_offset_s, bucket_seconds) + 1
        bucket_count = max(bucket_count, touched)
    acc = [0.0] * bucket_count
    for iv in intervals:
        if iv.duration_s <= 0 or iv.steps <= 0:
            if iv.steps > 0:
                acc[_bucket_index(iv.start_offset_s, bucket_seconds)] += iv.steps
            continue
        t = max(0.0, iv.start_offset_s)
        left = iv.duration_s
        while left > 1e-09:
            idx = _bucket_index(t, bucket_seconds)
            if idx >= bucket_count:
                idx = bucket_count - 1
            boundary = (idx + 1) * bucket_seconds
            seg = min(left, boundary - t)
            if seg <= 0:
                seg = left
            acc[idx] += iv.steps * (seg / iv.duration_s)
            t += seg
            left -= seg
    expected_total = int(round(sum((iv.steps for iv in intervals))))
    if total_steps is not None:
        if abs(int(total_steps) - expected_total) > 1:
            raise ValueError(f'total_steps({total_steps}) 与区间步数合计({expected_total}) 不一致；分桶不会凭空产生或丢弃步数')
        expected_total = int(total_steps)
    buckets = _largest_remainder(acc, expected_total)
    allocation = BucketAllocation(buckets=buckets, total_steps=sum(buckets), estimated=estimated, bucket_seconds=bucket_seconds)
    return allocation

def intervals_from_samples(samples: Sequence[Tuple[float, float, float]]) -> List[StepInterval]:
    return [StepInterval(start_offset_s=s, duration_s=d, steps=n) for s, d, n in samples]
