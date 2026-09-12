import rsa
import base64
from typing import Union

class RSACrypto:

    def __init__(self, public_key: Union[str, bytes]):
        self.public_key: bytes = self._format_public_key(public_key)

    @staticmethod
    def _format_public_key(key: Union[str, bytes]) -> bytes:
        if isinstance(key, bytes):
            key = key.decode()
        header = '-----BEGIN PUBLIC KEY-----\n'
        footer = '-----END PUBLIC KEY-----'
        formatted_key = ''
        chunk_size = 64
        num_chunks = len(key) // chunk_size
        num_lines = num_chunks if len(key) % chunk_size == 0 else num_chunks + 1
        for i in range(num_lines):
            start_pos = i * chunk_size
            end_pos = (i + 1) * chunk_size
            formatted_key += key[start_pos:end_pos] + '\n'
        result = header + formatted_key + footer
        return result.encode()

    def encrypt_bytes(self, data: bytes) -> str:
        public_key = rsa.PublicKey.load_pkcs1_openssl_pem(self.public_key)
        encrypted_data = base64.b64encode(rsa.encrypt(data, public_key))
        return encrypted_data.decode()

    def encrypt(self, message: str) -> str:
        public_key = rsa.PublicKey.load_pkcs1_openssl_pem(self.public_key)
        encrypted_chunks = b''
        max_chunk_size = 117
        num_chunks = len(message) // max_chunk_size
        total_chunks = num_chunks if len(message) % max_chunk_size == 0 else num_chunks + 1
        for i in range(total_chunks):
            start_pos = i * max_chunk_size
            end_pos = (i + 1) * max_chunk_size
            chunk = message[start_pos:end_pos].encode()
            encrypted_chunks += rsa.encrypt(chunk, public_key)
        return base64.b64encode(encrypted_chunks).decode()
