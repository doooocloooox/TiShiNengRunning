from track_geo import InvalidCoordinateError, point_list_distance, validate_lon_lat
from track_validate import validate_series

def test_coordinate_validation_and_distance():
    assert validate_lon_lat(116.4, 39.9) == (116.4, 39.9)
    try:
        validate_lon_lat(181, 0)
    except InvalidCoordinateError:
        pass
    else:
        raise AssertionError('out-of-range longitude accepted')
    assert point_list_distance([[0, 0], [0.001, 0]]) > 100

def test_validate_series_rejects_non_monotonic_timestamps():
    report = validate_series(points=[[116.0, 39.0], [116.001, 39.0]], timestamps_ms=[1000, 900])
    assert not report.ok
    assert any(issue.code == 'timestamp_not_increasing' for issue in report.errors)