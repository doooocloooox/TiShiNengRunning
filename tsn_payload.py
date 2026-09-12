from __future__ import annotations
import base64
import hashlib
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence
KNOWN_APP_SIGN_HASH = 'd2tnIyqximO/L8Y4MzfRELa1hSAtSRxzmvXlcOCzRyk='

def colon_hex_upper(digest: bytes) -> str:
    return ':'.join((f'{b:02X}' for b in digest))

def app_sign_hash(cert_der: bytes) -> str:
    if not cert_der:
        raise ValueError('cert_der 不能为空')
    c_hex = colon_hex_upper(hashlib.sha256(cert_der).digest())
    return base64.b64encode(hashlib.sha256(c_hex.encode()).digest()).decode()

def app_sign_hash_from_cert_b64(cert_b64: str) -> str:
    compact = ''.join(cert_b64.split())
    return app_sign_hash(base64.b64decode(compact))

def session_key(token: str, timestamp: str) -> str:
    return hashlib.md5(f'{token}{timestamp}'.encode('utf-8')).hexdigest()[0:16]

def _cbc_key_iv(token: str) -> tuple:
    md5_token = hashlib.md5(token.encode('utf-8')).hexdigest()
    return (md5_token[0:16].encode(), md5_token[16:32].encode())

def sign_auth_info(auth_info: str, token: str) -> str:
    import urllib.parse
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    key, iv = _cbc_key_iv(token)
    plain = urllib.parse.unquote(auth_info)
    cipher = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(plain.encode('utf-8'), 16))
    return hashlib.md5(base64.b64encode(cipher)).hexdigest()

def old_sign(auth_info: str, token: str) -> str:
    import urllib.parse
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    key, iv = _cbc_key_iv(token)
    plain = urllib.parse.unquote(auth_info)
    cipher = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(plain.encode('utf-8'), 16))
    return base64.b64encode(cipher).decode()

def build_auth_info(params: Mapping[str, Any]) -> str:
    parts = []
    for key in sorted(params.keys()):
        value = params[key]
        if value is None:
            text = 'null'
        elif isinstance(value, bool):
            text = 'true' if value else 'false'
        else:
            text = str(value)
        parts.append(f'{key}={text}')
    return '&'.join(parts)

def decrypt_param(param_b64: str, key_b64: str) -> str:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    key = base64.b64decode(key_b64)
    data = base64.b64decode(param_b64)
    return unpad(AES.new(key, AES.MODE_ECB).decrypt(data), 16).decode('utf-8')

def _as_int(value: Any, default: int=0) -> int:
    try:
        if value is None or value == '':
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default

def _as_float(value: Any, default: float=0.0) -> float:
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'y')
    return bool(value)

def point_risk_flags(point: Mapping[str, Any]) -> Dict[str, bool]:
    return {'f': _truthy(point.get('f')), 'm': _truthy(point.get('m')), 'h': _truthy(point.get('h'))}

def aggregate_risk_flags(points: Optional[Iterable[Mapping[str, Any]]]=None, user_open_develop: Any=False, offline: Any=0) -> Dict[str, int]:
    f_count = m_count = h_count = 0
    if points:
        for point in points:
            flags = point_risk_flags(point)
            f_count += 1 if flags['f'] else 0
            m_count += 1 if flags['m'] else 0
            h_count += 1 if flags['h'] else 0
    d_value = (1 if _truthy(user_open_develop) else 0) + _as_int(offline, 0)
    return {'d': d_value, 'f': f_count, 'm': m_count, 'h': h_count}

def total_range_meters(setting: Mapping[str, Any]) -> float:
    return _as_float(setting.get('totalRange'), 0.0) * 1000.0

def required_steps(setting: Mapping[str, Any], distance_m: float) -> int:
    step = _as_int(setting.get('step'), 0)
    is_step_recursion = _as_int(setting.get('isStepRecursion'), 0)
    total = total_range_meters(setting)
    if is_step_recursion and total > 0 and (distance_m > total):
        try:
            return int(math.ceil(step * (distance_m / total)))
        except (OverflowError, ValueError):
            return step
    return step

def adaptive_end_qualified_time(setting: Mapping[str, Any], distance_m: float) -> int:
    end_q = _as_int(setting.get('endQualifiedTime'), -1)
    total = total_range_meters(setting)
    if end_q != -1 and total > 0 and (distance_m > total):
        try:
            return int(math.ceil(end_q * (distance_m / total)))
        except (OverflowError, ValueError):
            return end_q
    return end_q

def is_valid_qualified(setting: Mapping[str, Any], elapsed_s: float, distance_m: float, steps: int) -> bool:
    start_q = _as_int(setting.get('startQualifiedTime'), 0)
    end_q = adaptive_end_qualified_time(setting, distance_m)
    ok_time = elapsed_s >= start_q * 60
    if not ok_time and end_q != -1:
        ok_time = elapsed_s <= end_q * 60
    ok_distance = distance_m >= total_range_meters(setting)
    ok_steps = steps >= required_steps(setting, distance_m)
    return bool(ok_time and ok_distance and ok_steps)

def compute_is_valid(setting: Mapping[str, Any], elapsed_s: float, distance_m: float, steps: int) -> int:
    return 1 if is_valid_qualified(setting, elapsed_s, distance_m, steps) else 0

def qualification_detail(setting: Mapping[str, Any], elapsed_s: float, distance_m: float, steps: int) -> Dict[str, Any]:
    return {'startQualifiedTime_min': _as_int(setting.get('startQualifiedTime'), 0), 'endQualifiedTime_min': adaptive_end_qualified_time(setting, distance_m), 'elapsed_s': round(elapsed_s, 1), 'totalRange_m': total_range_meters(setting), 'distance_m': round(distance_m, 1), 'required_steps': required_steps(setting, distance_m), 'steps': steps, 'isValid': compute_is_valid(setting, elapsed_s, distance_m, steps)}

def remark_options(setting: Mapping[str, Any]) -> list:
    remarks = setting.get('remarks')
    if isinstance(remarks, list):
        return remarks
    return []

def remark_id(setting: Mapping[str, Any]) -> Optional[str]:
    value = setting.get('remarkId')
    if value in (None, '', 0, '0'):
        return None
    return str(value)

def select_remark(setting: Mapping[str, Any], name_or_id: str) -> Optional[str]:
    for item in remark_options(setting):
        if not isinstance(item, Mapping):
            continue
        if str(item.get('id')) == str(name_or_id) or str(item.get('name')) == str(name_or_id):
            return str(item.get('id')) if item.get('id') is not None else None
    return None

def build_submit_extras(setting: Mapping[str, Any], points: Optional[Sequence[Mapping[str, Any]]]=None, elapsed_s: float=0.0, distance_m: float=0.0, steps: int=0, user_open_develop: Any=None, offline: Any=0, include_is_valid: bool=True) -> Dict[str, Any]:
    if user_open_develop is None:
        user_open_develop = setting.get('userOpenDevelop', False) if setting else False
    extras: Dict[str, Any] = aggregate_risk_flags(points, user_open_develop=user_open_develop, offline=offline)
    if include_is_valid:
        extras['isValid'] = compute_is_valid(setting, elapsed_s, distance_m, steps)
    rid = remark_id(setting)
    if rid is not None:
        extras['remarkId'] = rid
    return extras
