"""Minimal HTTP client for scripted smoke tests of the AVDP GIS Portal.

GeoNode marks its session and CSRF cookies ``Secure``. Browsers still send
them to http://localhost, but ``requests`` does not, so this helper re-adds
the cookies to the jar without the Secure flag for local HTTP testing only.
"""

import re

import requests


class PortalClient:
    def __init__(self, base_url="http://localhost"):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()

    def _unsecure_cookies(self):
        for c in list(self.s.cookies):
            if c.secure:
                self.s.cookies.set(c.name, c.value, domain=c.domain, path=c.path)
                c.secure = False

    def get(self, path, **kw):
        r = self.s.get(self.base + path, **kw)
        self._unsecure_cookies()
        return r

    def csrf(self):
        return self.s.cookies.get("csrftoken")

    def request(self, method, path, **kw):
        headers = kw.pop("headers", {})
        headers.setdefault("X-CSRFToken", self.csrf() or "")
        headers.setdefault("Referer", self.base + "/")
        r = self.s.request(method, self.base + path, headers=headers, **kw)
        self._unsecure_cookies()
        return r

    def login(self, username, password):
        r = self.get("/account/login/")
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text).group(1)
        r = self.s.post(
            self.base + "/account/login/",
            data={"login": username, "password": password, "csrfmiddlewaretoken": token},
            headers={"Referer": self.base + "/account/login/"},
            allow_redirects=False,
        )
        self._unsecure_cookies()
        return r.status_code == 302 and "/account/login" not in (r.headers.get("Location") or "")
