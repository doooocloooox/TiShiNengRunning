from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union
MIN_RATIO = 0.05
MAX_RATIO = 1.2
MIN_GAP_S = 5.0

@dataclass
class FacePoint:
    timestamp_ms: int
    latitude: float
    longitude: float
    face_type: int = 2

    def as_dict(self) -> Dict[str, Any]:
        return {'timestamp': self.timestamp_ms, 'latitude': self.latitude, 'longitude': self.longitude}

def normalize_middle_faces(raw: Optional[Iterable]) -> List[Union[float, Dict[str, Any]]]:
    faces: List[Union[float, Dict[str, Any]]] = []
    for item in raw or []:
        if isinstance(item, dict):
            faces.append(item)
            continue
        try:
            ratio = float(item)
        except (TypeError, ValueError):
            continue
        faces.append(max(MIN_RATIO, min(MAX_RATIO, ratio)))
    return faces

def _point_time(point: Dict[str, Any], is_public: bool) -> Optional[int]:
    value = point.get('t') if is_public else point.get('time')
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _point_lon_lat(point: Dict[str, Any], is_public: bool):
    if is_public:
        return (point.get('o'), point.get('a'))
    return (point.get('longitude'), point.get('latitude'))

def _pick_point_at(path: Sequence[Dict[str, Any]], target_ms: int, is_public: bool) -> Optional[Dict[str, Any]]:
    fallback = None
    for point in path:
        ts = _point_time(point, is_public)
        if ts is None:
            continue
        fallback = point
        if ts >= target_ms:
            return point
    return fallback

def build_middle_face_points(path: Sequence[Dict[str, Any]], start_timestamp_ms: int, end_timestamp_ms: int, middle_faces: Optional[Iterable], is_public: bool=True, face_type: int=2, min_gap_s: float=MIN_GAP_S) -> List[FacePoint]:
    faces = normalize_middle_faces(middle_faces)
    if not faces or not path:
        return []
    total_ms = max(0, int(end_timestamp_ms) - int(start_timestamp_ms))
    points: List[FacePoint] = []
    for face in faces:
        if isinstance(face, dict):
            timestamp = face.get('timestamp')
            latitude = face.get('latitude')
            longitude = face.get('longitude')
            if timestamp is None or latitude is None or longitude is None:
                continue
            try:
                points.append(FacePoint(int(timestamp), float(latitude), float(longitude), face_type))
            except (TypeError, ValueError):
                continue
            continue
        target_ms = int(start_timestamp_ms) + int(total_ms * float(face))
        chosen = _pick_point_at(path, target_ms, is_public)
        if chosen is None:
            continue
        lon, lat = _point_lon_lat(chosen, is_public)
        if lon is None or lat is None:
            continue
        ts = _point_time(chosen, is_public)
        try:
            points.append(FacePoint(int(ts if ts is not None else target_ms), float(lat), float(lon), face_type))
        except (TypeError, ValueError):
            continue
    points.sort(key=lambda item: item.timestamp_ms)
    deduped: List[FacePoint] = []
    gap_ms = int(min_gap_s * 1000)
    for point in points:
        if deduped and point.timestamp_ms - deduped[-1].timestamp_ms < gap_ms:
            continue
        deduped.append(point)
    return deduped
