from __future__ import annotations
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional
OPPO_FIELDS = ('root', 'selinux', 'xposed', 'proxy', 'vpn', 'separation', 'emulator', 'ptrace', 'frida', 'hook', 'breakpoint')
_DETAIL_FIELDS = ('selinux', 'frida', 'hook', 'breakpoint')
CLEAN_SELINUX_DETAIL = ['Enforcing\n']

@dataclass
class EnvSignals:
    root: bool = False
    selinux: bool = False
    xposed: bool = False
    proxy: bool = False
    vpn: bool = False
    separation: bool = False
    emulator: bool = False
    ptrace: bool = False
    frida: bool = False
    hook: bool = False
    breakpoint: bool = False
    details: Dict[str, List[str]] = field(default_factory=dict)
    source: str = 'none'
    raw: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, bool]:
        return {name: bool(getattr(self, name)) for name in OPPO_FIELDS}

def clean_device_signals() -> EnvSignals:
    return EnvSignals(source='clean-profile', details={'selinux': list(CLEAN_SELINUX_DETAIL), 'frida': [], 'hook': [], 'breakpoint': []})

def checksum(data: Mapping[str, Any]) -> str:
    temp = {k: v for k, v in data.items() if k != 'checksum'}
    raw = json.dumps(temp, separators=(',', ':'), ensure_ascii=False)
    return hashlib.md5(raw.encode('utf-8')).hexdigest()

def _bool_str(value: Any) -> str:
    return 'true' if value else 'false'

def build_environment_payload(device_id: str, signals: Optional[EnvSignals]=None, abis: Optional[List[str]]=None, nonce: Optional[str]=None, timestamp_ms: Optional[int]=None, signed: bool=True, debug: bool=False) -> Dict[str, Any]:
    if signals is None:
        signals = clean_device_signals()
    oppo: Dict[str, Any] = {'auth': 'success'}
    for name in OPPO_FIELDS:
        entry: Dict[str, Any] = {'result': _bool_str(getattr(signals, name))}
        if name in _DETAIL_FIELDS:
            entry['detail'] = list(signals.details.get(name, []))
        oppo[name] = entry
    oppo['nonce'] = nonce or str(uuid.uuid4())
    oppo['timestamp'] = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
    oppo['checksum'] = checksum(oppo)
    safe = {'sign': _bool_str(signed), 'root': _bool_str(signals.root), 'emulator': _bool_str(signals.emulator), 'hook': _bool_str(signals.hook), 'debug': _bool_str(debug), 'breakpoint': _bool_str(signals.breakpoint), 'supported_abis': list(abis or [])}
    return {'deviceId': device_id, 'oppo': json.dumps(oppo, separators=(',', ':'), ensure_ascii=False), 'safe': json.dumps(safe, separators=(',', ':'), ensure_ascii=False)}

def _run(cmd: List[str], timeout: float=8.0) -> Optional[str]:
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    for stream in (result.stdout, result.stderr):
        if stream:
            try:
                return stream.decode('utf-8', 'replace')
            except Exception:
                continue
    return ''

def _port_open(host: str, port: int, timeout: float=0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def _path_exists_any(paths: List[str]) -> Optional[str]:
    for path in paths:
        try:
            if os.path.exists(path):
                return path
        except OSError:
            continue
    return None

def _proc_status() -> Dict[str, str]:
    status: Dict[str, str] = {}
    try:
        with open('/proc/self/status', 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if ':' in line:
                    key, value = line.split(':', 1)
                    status[key.strip()] = value.strip()
    except OSError:
        pass
    return status

def _detect_host_breakpoint() -> bool:
    status = _proc_status()
    if status:
        return status.get('TracerPid', '0') not in ('0', '')
    if sys.platform.startswith('win'):
        try:
            import ctypes
            return bool(ctypes.windll.kernel32.IsDebuggerPresent())
        except Exception:
            return False
    return False

def _detect_host_vpn() -> bool:
    try:
        names = [name for _, name in socket.if_nameindex()]
    except (AttributeError, OSError):
        return False
    return any((name.startswith(('tun', 'tap', 'ppp')) for name in names))

def probe_host() -> EnvSignals:
    signals = EnvSignals(source='host')
    su_hit = _path_exists_any(['/system/bin/su', '/system/xbin/su', '/sbin/su', '/su/bin/su', '/magisk/.core/bin/su'])
    if shutil.which('su'):
        su_hit = 'PATH:su'
    signals.root = bool(su_hit)
    xposed_hit = _path_exists_any(['/system/framework/XposedBridge.jar', '/system/lib/libxposed_art.so', '/system/lib64/libxposed_art.so'])
    signals.xposed = bool(xposed_hit)
    signals.proxy = any((os.environ.get(name) for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy')))
    signals.vpn = _detect_host_vpn()
    signals.ptrace = bool(_proc_status().get('TracerPid', '0') not in ('0', '')) if _proc_status() else False
    signals.breakpoint = _detect_host_breakpoint()
    frida_hits: List[str] = []
    if _port_open('127.0.0.1', 27042):
        frida_hits.append('tcp:27042 open')
    try:
        for entry in os.listdir('/proc'):
            if entry.isdigit():
                try:
                    with open(f'/proc/{entry}/comm', 'r', encoding='utf-8', errors='replace') as fh:
                        name = fh.read().strip()
                except OSError:
                    continue
                if 'frida' in name.lower():
                    frida_hits.append(f'proc:{name}')
                    break
    except OSError:
        pass
    signals.frida = bool(frida_hits)
    signals.details['frida'] = frida_hits
    return signals

def probe_adb(serial: Optional[str]=None, timeout: float=8.0) -> Optional[EnvSignals]:
    if not shutil.which('adb'):
        return None
    base = ['adb']
    if serial:
        base += ['-s', serial]
    devices = _run(base + ['devices'], timeout=timeout)
    if not devices or '\tdevice' not in devices:
        return None

    def sh(command: str) -> str:
        return _run(base + ['shell', command], timeout=timeout) or ''
    signals = EnvSignals(source='adb')
    props = sh('getprop')

    def prop(name: str) -> str:
        for line in props.splitlines():
            if line.startswith(f'[{name}]:'):
                return line.split(':', 1)[1].strip().strip('[]')
        return ''
    tags = prop('ro.build.tags')
    debuggable = prop('ro.debuggable')
    signals.root = bool(sh('which su').strip() or 'test-keys' in tags or debuggable == '1')
    signals.emulator = bool(prop('ro.hardware') in ('goldfish', 'ranchu', 'vbox86') or 'generic' in prop('ro.product.model').lower() or 'sdk' in prop('ro.product.model').lower())
    signals.selinux = 'permissive' in sh('getenforce').lower()
    signals.xposed = bool(sh('ls /system/framework/XposedBridge.jar 2>/dev/null').strip())
    signals.frida = bool(sh('ps -A 2>/dev/null | grep -i frida').strip())
    signals.hook = bool(sh("grep -iE 'frida|xposed|substrate|epic|dobby' /proc/self/maps 2>/dev/null").strip())
    signals.ptrace = 'TracerPid' in sh('cat /proc/self/status 2>/dev/null')
    signals.breakpoint = bool(sh("ps -A 2>/dev/null | grep -E 'gdbserver|lldb-server'").strip())
    proxy_setting = sh('settings get global http_proxy').strip()
    signals.proxy = bool(proxy_setting and proxy_setting not in ('null', ':0'))
    signals.vpn = bool(sh("ip link show 2>/dev/null | grep -E 'tun|ppp'").strip())
    signals.separation = bool(sh("pm list packages 2>/dev/null | grep -E 'parallel|dual|clone'").strip())
    signals.details['frida'] = [line.strip() for line in sh('ps -A 2>/dev/null | grep -i frida').splitlines()[:5]]
    signals.details['hook'] = []
    signals.details['breakpoint'] = []
    signals.details['selinux'] = [sh('getenforce').strip() or 'unknown']
    signals.raw = {'ro.build.tags': tags, 'ro.debuggable': debuggable, 'ro.build.type': prop('ro.build.type'), 'ro.product.model': prop('ro.product.model'), 'ro.hardware': prop('ro.hardware')}
    return signals

def probe_device(prefer_adb: bool=True, serial: Optional[str]=None, timeout: float=8.0) -> EnvSignals:
    if prefer_adb:
        try:
            adb_signals = probe_adb(serial=serial, timeout=timeout)
        except Exception:
            adb_signals = None
        if adb_signals is not None:
            return adb_signals
    return probe_host()
