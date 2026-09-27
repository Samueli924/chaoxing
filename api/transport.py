"""Optional system-curl transport for hosts with broken Python socket networking.

Requests still owns redirects and the cookie jar. Secrets travel through stdin,
never shell arguments or temporary files. Only buffered HTTP(S) is supported.
"""
import errno
import io
import math
import os
import shutil
import subprocess
from email.parser import BytesParser
from types import SimpleNamespace
from urllib.parse import urlsplit

from requests import Response
from requests.adapters import HTTPAdapter
from requests.cookies import extract_cookies_to_jar
from requests.exceptions import ConnectionError, SSLError, Timeout
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers, select_proxy
from urllib3.exceptions import NewConnectionError


def _quote(value):
    text = str(value)
    if '\x00' in text:
        raise ValueError('curl configuration cannot contain NUL')
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"'


def _connect_bad_fd(error):
    """Only retry failures proved to occur while opening a connection."""
    seen = set()
    todo = [error]
    while todo:
        item = todo.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, NewConnectionError):
            cause = item.__cause__
            if isinstance(cause, OSError) and cause.errno == errno.EBADF:
                return True
        todo.extend(x for x in (getattr(item, '__cause__', None), getattr(item, 'reason', None), *getattr(item, 'args', ())) if isinstance(x, BaseException))
    return False


class CurlAdapter(HTTPAdapter):
    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        executable = shutil.which('curl')
        if not executable:
            raise ConnectionError('System curl is unavailable', request=request)
        if urlsplit(request.url).scheme not in ('http', 'https'):
            raise ValueError('curl transport only supports HTTP(S)')
        if stream:
            raise ValueError('curl transport does not support streaming responses')
        if verify is False:
            raise ValueError('curl transport requires TLS verification')
        connect, read = timeout if isinstance(timeout, tuple) else (timeout, timeout)
        connect, read = float(connect or 15), float(read or 15)
        if not all(math.isfinite(v) and v > 0 for v in (connect, read)):
            raise ValueError('Invalid timeout')
        limit = connect + read
        config = ['silent', 'show-error', 'include', 'compressed', 'globoff', 'suppress-connect-headers',
                  'proto = "=http,https"', 'connect-timeout = ' + _quote(connect),
                  'max-time = ' + _quote(limit), 'url = ' + _quote(request.url),
                  'request = ' + _quote(request.method)]
        if request.method == 'HEAD':
            config.append('head')
        proxy = select_proxy(request.url, proxies or {})
        config.append('proxy = ' + _quote(proxy or ''))
        # Do not let the subprocess silently reinterpret proxy environment settings.
        config.append('noproxy = ' + _quote('' if proxy else '*'))
        if isinstance(verify, str):
            config.append(('capath' if os.path.isdir(verify) else 'cacert') + ' = ' + _quote(verify))
        if cert:
            cert, key = cert if isinstance(cert, tuple) else (cert, None)
            config.append('cert = ' + _quote(cert))
            if key:
                config.append('key = ' + _quote(key))
        for name, value in request.headers.items():
            if name.lower() == 'accept-encoding':
                continue  # curl negotiates only encodings supported by its own build.
            config.append('header = ' + _quote(f'{name}: {value}'))
        if request.body is not None:
            body = request.body
            if isinstance(body, bytes):
                body = body.decode('utf-8')
            if not isinstance(body, str):
                raise ValueError('curl transport only supports UTF-8 text request bodies')
            config.append('data-raw = ' + _quote(body))
        try:
            result = subprocess.run([executable, '--disable', '--config', '-'],
                                    input=('\n'.join(config) + '\n').encode(),
                                    capture_output=True, timeout=limit + 2, check=False)
        except subprocess.TimeoutExpired:
            raise Timeout('curl request exceeded its deadline', request=request) from None
        except OSError:
            raise ConnectionError('Could not start system curl', request=request) from None
        if result.returncode:
            cls = Timeout if result.returncode == 28 else SSLError if result.returncode in (35, 51, 58, 60, 77, 83, 90, 91) else ConnectionError
            # stderr can contain sensitive URLs; expose only the stable exit code.
            raise cls(f'curl transport failed (exit {result.returncode})', request=request)
        data = result.stdout
        while True:
            head, sep, data = data.partition(b'\r\n\r\n')
            first, _, headers = head.partition(b'\r\n')
            try:
                protocol, status, *reason = first.decode('iso-8859-1').split(' ', 2)
                status = int(status)
                if not protocol.startswith('HTTP/') or not sep:
                    raise ValueError
            except ValueError:
                raise ConnectionError('Invalid HTTP response from curl', request=request) from None
            if not 100 <= status < 200:
                break
        message = BytesParser().parsebytes(headers + b'\r\n\r\n')
        response = Response()
        response.status_code = status
        response.reason = reason[0] if reason else ''
        response.headers = CaseInsensitiveDict(message.items())
        response.url = request.url
        response.request = request
        response.connection = self
        response.encoding = get_encoding_from_headers(response.headers)
        response._content = data
        response._content_consumed = True
        # Preserve repeated Set-Cookie headers for Requests' redirect/session handling.
        response.raw = io.BytesIO(data)
        response.raw._original_response = SimpleNamespace(msg=message)
        extract_cookies_to_jar(response.cookies, request, response.raw)
        return response


class CompatibleHTTPAdapter(HTTPAdapter):
    """Fallback only for pre-send EBADF; never replay an ambiguous failed POST."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        mode = os.environ.get('CHAOXING_HTTP_TRANSPORT', 'auto').lower()
        if mode not in ('auto', 'requests', 'curl'):
            raise ValueError('CHAOXING_HTTP_TRANSPORT must be auto, requests or curl')
        self.mode = mode
        self._curl = CurlAdapter()
        self._fallback = mode == 'curl'

    def send(self, request, **kwargs):
        if self._fallback:
            return self._curl.send(request, **kwargs)
        try:
            return super().send(request, **kwargs)
        except ConnectionError as exc:
            if self.mode != 'auto' or not _connect_bad_fd(exc):
                raise
            self._fallback = True
            return self._curl.send(request, **kwargs)

    def close(self):
        super().close()
        self._curl.close()
