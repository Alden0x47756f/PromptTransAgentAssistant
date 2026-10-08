"""User-bound Windows DPAPI credentials; plaintext never enters config or UI."""
import base64
import ctypes as ct
from ctypes import wintypes as wt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time


class Blob(ct.Structure):
    _fields_ = [('size', wt.DWORD), ('data', ct.POINTER(ct.c_ubyte))]


crypt = ct.WinDLL('crypt32', use_last_error=True)
kernel = ct.WinDLL('kernel32', use_last_error=True)
crypt.CryptProtectData.argtypes = [ct.POINTER(Blob), wt.LPCWSTR, ct.POINTER(Blob), ct.c_void_p, ct.c_void_p, wt.DWORD, ct.POINTER(Blob)]
crypt.CryptUnprotectData.argtypes = [ct.POINTER(Blob), ct.c_void_p, ct.POINTER(Blob), ct.c_void_p, ct.c_void_p, wt.DWORD, ct.POINTER(Blob)]
crypt.CryptProtectData.restype = crypt.CryptUnprotectData.restype = wt.BOOL
kernel.LocalFree.argtypes = [ct.c_void_p]
kernel.LocalFree.restype = ct.c_void_p


def _protect(data, decrypt=False):
    buffer = (ct.c_ubyte * len(data)).from_buffer_copy(data)
    source, destination = Blob(len(data), buffer), Blob()
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    description = None if decrypt else 'PromptTransAgentAssistant API credential'
    if not function(ct.byref(source), description, None, None, None, 1, ct.byref(destination)):
        raise ValueError('无法解密已保存密钥，请在当前 Windows 账户重新填写。' if decrypt else 'Windows 密钥加密失败，请检查当前账户权限。')
    try:
        return ct.string_at(destination.data, destination.size)
    finally:
        kernel.LocalFree(destination.data)


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.settings-', delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class SecretStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ['LOCALAPPDATA']) / 'PromptTransAgentAssistant' / 'credentials.json'
        self.lock = threading.RLock()

    @staticmethod
    def identity(protocol, base_url):
        # A credential saved for one host/protocol is never sent to another.
        return hashlib.sha256((protocol + '\0' + base_url.rstrip('/')).encode('utf-8')).hexdigest()

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in data.items()):
                raise ValueError()
            return data
        except Exception as exc:
            raise ValueError('密钥存储文件损坏，请清除该地址的密钥并重新填写。') from exc

    def get(self, protocol, base_url):
        with self.lock:
            encoded = self._read().get(self.identity(protocol, base_url))
            if not encoded:
                return ''
            try:
                return _protect(base64.b64decode(encoded, validate=True), decrypt=True).decode('utf-8')
            except Exception as exc:
                raise ValueError('已保存密钥无法在当前账户读取，请重新填写密钥。') from exc

    def commit_with_config(self, protocol, base_url, new_key, config_path, config_content):
        """Replace both files, restoring the prior ciphertext if config writing fails."""
        with self.lock:
            old = self.path.read_bytes() if self.path.exists() else None
            if new_key:
                data = self._read()
                data[self.identity(protocol, base_url)] = base64.b64encode(_protect(new_key.encode('utf-8'))).decode('ascii')
                atomic_write(self.path, json.dumps(data).encode('utf-8'))
            try:
                atomic_write(config_path, config_content)
            except Exception:
                if new_key:
                    if old is None:
                        self.path.unlink(missing_ok=True)
                    else:
                        atomic_write(self.path, old)
                raise

    def clear(self, protocol, base_url):
        with self.lock:
            try:
                data = self._read()
            except ValueError:
                # Retain unreadable ciphertext for recovery before recreating the store.
                backup = self.path.with_name('credentials-corrupt-' + str(time.time_ns()) + '.json')
                atomic_write(backup, self.path.read_bytes())
                data = {}
            data.pop(self.identity(protocol, base_url), None)
            atomic_write(self.path, json.dumps(data).encode('utf-8'))
