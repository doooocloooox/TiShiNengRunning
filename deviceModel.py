import os
from dataclasses import dataclass

@dataclass(frozen=True)
class DeviceModel:
    brand: str = os.getenv('TSN_DEVICE_BRAND', 'Xiaomi')
    model: str = os.getenv('TSN_DEVICE_MODEL', '25042PN24C')
    osver: str = os.getenv('TSN_DEVICE_OS_VERSION', '16')
    a_list: str = os.getenv('TSN_DEVICE_ABIS', 'arm64-v8a')
deviceModel = DeviceModel()
