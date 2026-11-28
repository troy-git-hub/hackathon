"""Windows-current-user DPAPI backup. No plaintext token or portable decryption key."""
import ctypes
import hashlib
import json
import os
import tempfile
from pathlib import Path
from echo.backend import paths


def _file(service):
    return Path(paths.config_dir())/('credential-'+hashlib.sha256(service.encode()).hexdigest()[:16]+'.dpapi')


def _crypt(data,service,protect):
    if os.name!='nt':raise OSError('DPAPI is only available on Windows')
    from ctypes import wintypes
    class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    def blob(value):
        buffer=ctypes.create_string_buffer(value)
        return Blob(len(value),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte))),buffer
    source,source_buffer=blob(data);entropy,entropy_buffer=blob(service.encode());output=Blob()
    api=ctypes.WinDLL('crypt32',use_last_error=True)
    method=api.CryptProtectData if protect else api.CryptUnprotectData
    method.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR if protect else ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    method.restype=wintypes.BOOL
    if not method(ctypes.byref(source),None,ctypes.byref(entropy),None,None,1,ctypes.byref(output)):raise ctypes.WinError(ctypes.get_last_error())
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    try:return ctypes.string_at(output.data,output.size)
    finally:kernel.LocalFree(ctypes.cast(output.data,ctypes.c_void_p))


def save(service,value):
    encrypted=_crypt(json.dumps(value,ensure_ascii=False,allow_nan=False).encode(),service,True)
    file=_file(service);file.parent.mkdir(parents=True,exist_ok=True);temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=file.parent,mode='wb',delete=False) as stream:temp=Path(stream.name);stream.write(encrypted)
        os.replace(temp,file)
    finally:
        if temp:temp.unlink(missing_ok=True)


def load(service,max_bytes=65536):
    file=_file(service)
    if not file.exists():return None
    if not 0 < max_bytes <= 2*1024*1024 or file.stat().st_size>max_bytes:raise ValueError('Protected credential record is too large')
    return json.loads(_crypt(file.read_bytes(),service,False).decode())


def clear(service):_file(service).unlink(missing_ok=True)
