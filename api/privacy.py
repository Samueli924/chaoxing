"""Redaction shared by console logs, file logs and local review records."""

import re
import threading
from urllib.parse import urlsplit

_secrets = set()
_lock = threading.RLock()
_fields = r"(?:password|passwd|pwd|cookies?|authorization|api[_-]?key|key|token|[a-z_]*token|enc|aienc|urltoken|username|account|_?uid|fid|cpi|clazzid|classid|courseid|chat_id|tg_chat_id)"
_assignment = re.compile(
    rf"(?i)([\"']?\b{_fields}[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;&}}\]]+)")
_url = re.compile(r"https?://[^\s<>\"']+", re.I)
_phone = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def register_secret(value):
    """Remember configured secrets so even unlabeled exception messages are safe."""
    if value is not None and len(str(value)) >= 4:
        with _lock:
            _secrets.add(str(value))


def register_config(config):
    for key, value in (config or {}).items():
        if isinstance(value, dict):
            register_config(value)
        elif re.fullmatch(_fields, str(key), re.I) or str(key).lower() in {"url", "tokens"}:
            for item in value if isinstance(value, (list, tuple)) else [value]:
                register_secret(item)
                if str(key).lower() == "tokens":
                    for token in re.split(r"[,;\s]+", str(item)):
                        register_secret(token)


def redact(value):
    text = str(value)
    with _lock:
        secrets = sorted(_secrets, key=len, reverse=True)
    for secret in secrets:
        text = text.replace(secret, "[redacted]")
    text = re.sub(r"<RequestsCookieJar\[.*?\]>", "[redacted cookies]", text, flags=re.S)
    text = re.sub(r"(?i)\bBearer\s+[^\s,;\"']+", "Bearer [redacted]", text)
    # Headers and cookie containers can contain several unnamed credentials.
    text = re.sub(r"(?is)([\"']?\b(?:set-cookie|cookies?)[\"']?\s*[:=]\s*).*", lambda m: m.group(1) + "[redacted cookies]", text)
    text = re.sub(rf"(?is)([\"']?\b{_fields}[\"']?\s*[:=]\s*)[{{\[].*", lambda m: m.group(1) + "[redacted container]", text)
    text = _assignment.sub(lambda m: m.group(1) + "[redacted]", text)
    # Notification keys can be in path segments, userinfo or arbitrary query keys.
    def hide_url(match):
        try:
            host = urlsplit(match.group()).hostname or "service"
            return "https://" + host + "/[redacted]"
        except ValueError:
            return "[redacted URL]"
    text = _url.sub(hide_url, text)
    return _phone.sub("[redacted account]", text)


def _safe_extra(value):
    if isinstance(value, dict):
        return {key: "[redacted]" if re.fullmatch(_fields, str(key), re.I) else _safe_extra(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_extra(item) for item in value]
    return redact(value) if isinstance(value, str) else value


def patch_record(record):
    record["message"] = redact(record["message"])
    record["extra"] = {key: ("[redacted]" if re.fullmatch(_fields, key, re.I)
                              else _safe_extra(value))
                       for key, value in record["extra"].items()}
    if record.get("exception"):
        # Tracebacks can expose request URLs and locals even with a safe message.
        exc = record["exception"]
        record["message"] += " | " + redact(str(exc.value))
        record["exception"] = None
