"""Loopback-only update transport fixture for desktop tests, not a deployable service."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit


def create_server(directory,host='127.0.0.1',port=0):
    if host!='127.0.0.1' or port!=0:raise ValueError('Test fixture requires loopback and an ephemeral port')
    class Handler(SimpleHTTPRequestHandler):
        def send_head(self):
            path=urlsplit(self.path).path
            names={'/v1/releases/stable/windows-x64':'/stable.json','/v2/releases/stable/windows-x64':'/stable-v2.json'}
            if path in names:self.path=names[path]
            elif not path.startswith('/artifacts/') or '..' in path or '\\' in path:
                self.send_error(404);return None
            return super().send_head()
        def copyfile(self,source,outputfile):
            try:super().copyfile(source,outputfile)
            except (BrokenPipeError,ConnectionResetError):pass
        def log_message(self,*args):pass
    return ThreadingHTTPServer((host,port),partial(Handler,directory=str(directory)))
