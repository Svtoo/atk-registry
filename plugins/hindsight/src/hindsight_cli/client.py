"""HTTP access to the hindsight API."""
import json
import urllib.request


def http(method, url, timeout=30, body=None):
    """Performs an HTTP request; returns the response body as text, or raises."""
    headers = {}
    if isinstance(body, (dict, list)):
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    else:
        data = body.encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode()
