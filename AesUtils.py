import os
from typing import Union, Optional
from Crypto.Cipher import AES
from base64 import b64decode, b64encode
BLOCK_SIZE = AES.block_size
pad = lambda s: s + (BLOCK_SIZE - len(s.encode()) % BLOCK_SIZE) * chr(BLOCK_SIZE - len(s.encode()) % BLOCK_SIZE)
unpad = lambda s: s[:-ord(s[len(s) - 1:])]
zero_pad = lambda s: s + (BLOCK_SIZE - len(s.encode()) % BLOCK_SIZE) * chr(0)

def bytes_pad(data: bytes) -> bytes:
    pad_length = BLOCK_SIZE - len(data) % BLOCK_SIZE
    return data + bytes([pad_length] * pad_length)

class AESCrypto:

    def __init__(self, key: Union[str, bytes], iv: Union[str, bytes], ecb_mode: bool=False):
        if isinstance(key, str):
            key = key.encode()
        if isinstance(iv, str):
            iv = iv.encode()
        self.key = key
        self.iv = iv
        self.ecb_mode = ecb_mode

    def encrypt(self, text: Union[str, bytes], zero_padding: bool=False, is_bytes: bool=False) -> str:
        if is_bytes:
            padded_data = bytes_pad(text)
        elif zero_padding:
            padded_data = zero_pad(text).encode()
        else:
            padded_data = pad(text).encode()
        if self.ecb_mode:
            cipher = AES.new(key=self.key, mode=AES.MODE_ECB)
        else:
            cipher = AES.new(key=self.key, mode=AES.MODE_CBC, IV=self.iv)
        encrypted_data = cipher.encrypt(padded_data)
        return b64encode(encrypted_data).decode('utf-8')

    def decrypt(self, encrypted_text: str, return_bytes: bool=False) -> Union[str, bytes]:
        encrypted_data = b64decode(encrypted_text)
        if self.ecb_mode:
            cipher = AES.new(key=self.key, mode=AES.MODE_ECB)
        else:
            cipher = AES.new(key=self.key, mode=AES.MODE_CBC, IV=self.iv)
        decrypted_data = cipher.decrypt(encrypted_data)
        if return_bytes:
            return unpad(decrypted_data)
        else:
            return unpad(decrypted_data).decode('utf-8')
