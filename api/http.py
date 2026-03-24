# -*- coding: utf-8 -*-
import random
import time
from typing import Optional

from curl_cffi import requests as browser_requests
from curl_cffi.requests import Session as CurlSession
from curl_cffi.requests.exceptions import RequestException as BrowserRequestException

from api.config import GlobalConst as gc

SAFE_RETRY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
BrowserResponse = browser_requests.Response


class BrowserSession(CurlSession):
    def __init__(
            self,
            *args,
            retries: int = gc.REQUEST_RETRIES,
            retry_backoff: float = gc.REQUEST_RETRY_BACKOFF,
            **kwargs,
    ):
        kwargs.setdefault("impersonate", gc.BROWSER_IMPERSONATE)
        kwargs.setdefault("headers", gc.HEADERS)
        kwargs.setdefault("timeout", gc.REQUEST_TIMEOUT)
        kwargs.setdefault("default_headers", True)
        super().__init__(*args, **kwargs)
        self._retries = retries
        self._retry_backoff = retry_backoff

    def request(self, method, url, *args, **kwargs):
        retryable = kwargs.pop("retryable", method.upper() in SAFE_RETRY_METHODS)

        for attempt in range(self._retries + 1):
            try:
                return super().request(method, url, *args, **kwargs)
            except BrowserRequestException:
                if not retryable or attempt >= self._retries:
                    raise
                sleep_time = self._retry_backoff * (2 ** attempt) + random.uniform(0, self._retry_backoff)
                time.sleep(sleep_time)


def create_browser_session(
        cookies: Optional[dict] = None,
        headers: Optional[dict] = None,
        **kwargs,
) -> BrowserSession:
    merged_headers = gc.HEADERS.copy()
    if headers:
        merged_headers.update(headers)

    session = BrowserSession(headers=merged_headers, **kwargs)
    if cookies:
        session.cookies.update(cookies)
    return session
