from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple
EARTH_RADIUS_M = 6371008.8
EARTH_RADIUS_KM = EARTH_RADIUS_M / 1000.0
METERS_PER_KM = 1000.0
MAX_LAT = 90.0
MAX_LON = 180.0

class CrsMismatchError(ValueError):
    pass

class InvalidCoordinateError(ValueError):
    pass

@dataclass(frozen=True)
class CoordinateSystem:
    name: str

    def __str__(self) -> str:
        return self.name
WGS84 = CoordinateSystem('WGS84')
GCJ02 = CoordinateSystem('GCJ02')
BD09 = CoordinateSystem('BD09')

def validate_lon_lat(lon: float, lat: float) -> Tuple[float, float]:
    try:
        lon_f = float(lon)
        lat_f = float(lat)
    except (TypeError, ValueError) as exc:
        raise InvalidCoordinateError(f'坐标不是数字: lon={lon!r} lat={lat!r}') from exc
    if math.isnan(lon_f) or math.isnan(lat_f) or math.isinf(lon_f) or math.isinf(lat_f):
        raise InvalidCoordinateError(f'坐标包含 NaN/Inf: lon={lon!r} lat={lat!r}')
    if not -MAX_LON <= lon_f <= MAX_LON:
        raise InvalidCoordinateError(f'经度越界: {lon_f}')
    if not -MAX_LAT <= lat_f <= MAX_LAT:
        raise InvalidCoordinateError(f'纬度越界: {lat_f}')
    return (lon_f, lat_f)

def assert_same_crs(*crs: CoordinateSystem) -> CoordinateSystem:
    given = [c for c in crs if c is not None]
    if not given:
        return WGS84
    first = given[0]
    for c in given[1:]:
        if c.name != first.name:
            raise CrsMismatchError(f'坐标系混用: {first.name} vs {c.name}')
    return first

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    d_lat = lat2_rad - lat1_rad
    d_lon = lon2_rad - lon1_rad
    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lon / 2) ** 2
    a = min(1.0, max(0.0, a))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c

class LocalProjection:

    def __init__(self, origin_lon: float, origin_lat: float):
        self.origin_lon, self.origin_lat = validate_lon_lat(origin_lon, origin_lat)
        self._cos_lat = math.cos(math.radians(self.origin_lat))
        self._m_per_deg_lon = math.radians(1.0) * EARTH_RADIUS_M * self._cos_lat
        self._m_per_deg_lat = math.radians(1.0) * EARTH_RADIUS_M

    def to_xy(self, lon: float, lat: float) -> Tuple[float, float]:
        lon_f, lat_f = validate_lon_lat(lon, lat)
        return ((lon_f - self.origin_lon) * self._m_per_deg_lon, (lat_f - self.origin_lat) * self._m_per_deg_lat)

    def to_lon_lat(self, x: float, y: float) -> Tuple[float, float]:
        lon = self.origin_lon + x / self._m_per_deg_lon
        lat = self.origin_lat + y / self._m_per_deg_lat
        return (lon, lat)

    def distance(self, lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        x1, y1 = self.to_xy(lon1, lat1)
        x2, y2 = self.to_xy(lon2, lat2)
        return math.hypot(x2 - x1, y2 - y1)

    def interpolate(self, lon1: float, lat1: float, lon2: float, lat2: float, ratio: float) -> Tuple[float, float]:
        x1, y1 = self.to_xy(lon1, lat1)
        x2, y2 = self.to_xy(lon2, lat2)
        return self.to_lon_lat(x1 + (x2 - x1) * ratio, y1 + (y2 - y1) * ratio)

def normalize_points(points: Iterable[Sequence[float]]) -> List[List[float]]:
    result: List[List[float]] = []
    for idx, p in enumerate(points):
        if p is None or len(p) < 2:
            raise InvalidCoordinateError(f'第 {idx} 个点缺少经纬度: {p!r}')
        lon, lat = validate_lon_lat(p[0], p[1])
        result.append([lon, lat])
    return result

def point_list_distance(point_list: Sequence[Sequence[float]]) -> float:
    total = 0.0
    for i in range(1, len(point_list)):
        pre = point_list[i - 1]
        cur = point_list[i]
        total += haversine_distance(pre[1], pre[0], cur[1], cur[0])
    return total
