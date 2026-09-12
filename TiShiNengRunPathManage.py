from __future__ import annotations
import random
from typing import List, Optional, Sequence, Tuple
from track_log import logger
from step_buckets import DEFAULT_BUCKET_SECONDS, BucketAllocation, StepInterval, allocate_steps
from track_clean import CleanOptions, InsufficientTrackError, clean_track
from track_geo import EARTH_RADIUS_KM, EARTH_RADIUS_M, METERS_PER_KM, LocalProjection, haversine_distance, normalize_points, point_list_distance
from track_metrics import cadence_spm, compute_metrics, cumulative_distances, format_pace, pace_seconds_per_km, stride_for_speed, steps_for_interval
from track_resample import PointRisk, ResampleOptions, ResampledTrack, TrackGenerationError, TrackSample, resample_track
from track_validate import ValidationReport, validate_track
__all__ = ['EARTH_RADIUS_KM', 'EARTH_RADIUS_M', 'METERS_PER_KM', 'TsnRunPolyline', 'genTiShiNengRunPathRepeat', 'generate_run_track', 'to_legacy_points', 'haversine_distance', 'getPointListDistance', 'LocalProjection', 'ResampleOptions', 'ResampledTrack', 'TrackGenerationError', 'InsufficientTrackError']

def getPointListDistance(pointList: Sequence[Sequence[float]]) -> float:
    return point_list_distance(pointList)

class TsnRunPolyline:

    def __init__(self, points: Sequence[Sequence[float]]):
        self.points = normalize_points(points)
        self.distances = [haversine_distance(self.points[i][1], self.points[i][0], self.points[i + 1][1], self.points[i + 1][0]) for i in range(len(self.points) - 1)]
        self.total_length = sum(self.distances)

    def haversine_distance(self, point1: Sequence[float], point2: Sequence[float]) -> float:
        return haversine_distance(point1[1], point1[0], point2[1], point2[0])

    def interpolate_point(self, point1: Sequence[float], point2: Sequence[float], ratio: float) -> Tuple[float, float]:
        projection = LocalProjection(point1[0], point1[1])
        return projection.interpolate(point1[0], point1[1], point2[0], point2[1], ratio)

    def simulate_motion(self, avg_speed: float, distance: float):
        if avg_speed <= 0:
            raise TrackGenerationError(f'平均速度必须为正: {avg_speed}')
        plan_use_time = distance / avg_speed
        track = resample_track(points=self.points, need_distance_m=distance, start_timestamp_ms=0.0, plan_use_time_s=plan_use_time, options=ResampleOptions(speed_jitter=0.08))
        sampled = [{'lat': s.lat, 'lon': s.lon, 'millisecond': s.dt_ms, 'speed': s.speed_mps, 'distance': s.distance_m} for s in track.samples]
        logger.info(f'traveled_distance:{track.total_distance_m}')
        return (sampled, track.total_distance_m)

def to_legacy_points(track: ResampledTrack, isPublic: bool=True, coord_decimals: int=7, speed_decimals: int=6) -> List[dict]:
    result: List[dict] = []
    cumulative_steps = 0.0
    for sample in track.samples:
        cumulative_steps += steps_for_interval(sample.distance_m, sample.speed_mps)
        lat = round(sample.lat, coord_decimals)
        lon = round(sample.lon, coord_decimals)
        speed = round(sample.speed_mps, speed_decimals)
        steps_int = int(round(cumulative_steps))
        if isPublic:
            result.append({'a': lat, 'c': int(sample.offset_s), 'e': steps_int, 'i': bool(sample.paused), 'l': 1, 'o': lon, 's': speed, 't': int(sample.t_ms), 'distance': sample.distance_m})
        else:
            result.append({'countTime': 0, 'latitude': lat, 'locationType': 1, 'longitude': lon, 'puase': bool(sample.paused), 'speed': speed, 'stability': 0, 'time': int(sample.t_ms), 'distance': sample.distance_m})
    if len(result) >= 2 and isPublic:
        result[-1]['c'] = result[-2]['c']
        result[-1]['e'] = result[-2]['e']
        result[-1]['i'] = True
        result[-2]['i'] = True
    return result

def generate_run_track(pointList: Sequence[Sequence[float]], needDistance: float, startTimeStamp: float, planUseTime: float, isPublic: bool=True, options: Optional[ResampleOptions]=None, rng: Optional[random.Random]=None, risk_resolver=None) -> Tuple[ResampledTrack, BucketAllocation, ValidationReport]:
    track = resample_track(points=pointList, need_distance_m=needDistance, start_timestamp_ms=startTimeStamp, plan_use_time_s=planUseTime, options=options, rng=rng, risk_resolver=risk_resolver)
    intervals = [StepInterval(start_offset_s=start, duration_s=duration, steps=steps) for start, duration, steps in track.step_samples()]
    allocation = allocate_steps(intervals, bucket_seconds=DEFAULT_BUCKET_SECONDS, estimated=False, total_steps=int(round(sum((iv.steps for iv in intervals)))))
    report = validate_track(track, bucket_allocation=allocation, total_steps=allocation.total_steps, summary_coords=[track.points[0], track.points[-1]])
    if not report.ok:
        logger.warning(report.summary())
    return (track, allocation, report)

def genTiShiNengRunPathRepeat(pointList: Sequence[Sequence[float]], needDistance: float, startTimeStamp: float, planUseTime: float, isPublic: bool=True) -> Tuple[List[dict], List[int], float]:
    track, allocation, report = generate_run_track(pointList=pointList, needDistance=needDistance, startTimeStamp=startTimeStamp, planUseTime=planUseTime, isPublic=isPublic)
    if not report.ok:
        report.raise_if_failed()
    result = to_legacy_points(track, isPublic=isPublic)
    logger.info(f'needDistance:{needDistance},sumDistance:{track.total_distance_m} stepBuckets:{len(allocation.buckets)}/{allocation.total_steps}')
    return (result, list(allocation.buckets), track.total_distance_m)

def describe_track(track: ResampledTrack) -> dict:
    chord = compute_metrics(track.points, track.timestamps_ms)
    elapsed = track.elapsed_s
    avg_speed = track.total_distance_m / elapsed if elapsed > 0 else 0.0
    return {'distance_m': round(track.total_distance_m, 3), 'chord_distance_m': round(chord.distance_m, 3), 'elapsed_s': round(elapsed, 1), 'point_count': len(track.samples), 'avg_speed_mps': round(avg_speed, 4), 'pace': format_pace(pace_seconds_per_km(track.total_distance_m, elapsed)), 'cadence_spm': round(cadence_spm(avg_speed), 1), 'stride_m': round(stride_for_speed(avg_speed), 3), 'steps': track.total_steps, 'cleaned_points': track.cleaned_point_count, 'source_points': track.source_point_count, 'notes': track.notes}
