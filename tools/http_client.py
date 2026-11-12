"""带白名单与限速的 HTTP 客户端。

所有 Agent 流量必须经过这里：
- 白名单：只允许访问配置后缀的域名（靶场实例 / 本地 mock 靶场）；
- 限速：两次请求之间强制最小间隔，对靶场服务保持礼貌；
- 捕获：每次请求的原始报文都存入 traffic，供回放界面展示。
"""

import time
from urllib.parse import urlparse

import requests


class SafetyViolation(Exception):
    """触犯安全约束（越出白名单 / 超请求上限）时抛出。"""


class SafeHTTP:
    def __init__(self, base_url, allowed_suffixes, interval=0.5,
                 max_requests=120, allow_hosts=None):
        self.base_url = (base_url or "").rstrip("/")
        self.allowed_suffixes = list(allowed_suffixes) + list(allow_hosts or [])
        self.interval = float(interval)
        self.max_requests = int(max_requests)
        self._last_ts = 0.0
        self._count = 0
        self.traffic = []  # [{method,url,status,request,response,ts}]
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "WebSecLabAgent/0.1 (educational use on authorized labs only)"
        )

    # ---------- 安全约束 ----------
    def _resolve(self, url: str) -> str:
        url = url.strip()
        if not url.startswith("http"):
            url = self.base_url + (url if url.startswith("/") else "/" + url)
        return url

    def _check(self, url: str) -> str:
        host = urlparse(url).hostname or ""
        if not host:
            raise SafetyViolation(f"无法解析的 URL: {url}")
        ok = any(host == s or host.endswith("." + s) for s in self.allowed_suffixes)
        if not ok:
            raise SafetyViolation(f"目标 {host} 不在白名单内，请求已拦截")
        if self._count >= self.max_requests:
            raise SafetyViolation(f"已达单次运行的最大请求数上限 {self.max_requests}")
        return url

    # ---------- 请求 ----------
    def request(self, method, url, headers=None, data=None):
        url = self._check(self._resolve(str(url)))
        wait = self.interval - (time.time() - self._last_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_ts = time.time()
        self._count += 1

        method = method.upper()
        req = requests.Request(method, url, headers=headers, data=data)
        prepared = self.session.prepare_request(req)
        raw_request = self._raw_request(prepared, data)
        try:
            resp = self.session.send(prepared, timeout=30, allow_redirects=True)
        except requests.RequestException as exc:
            entry = {"method": method, "url": url, "status": 0,
                     "request": raw_request, "response": f"连接失败: {exc}",
                     "ts": time.time()}
            self.traffic.append(entry)
            raise
        raw_response = self._raw_response(resp)
        self.traffic.append({
            "method": method, "url": resp.url, "status": resp.status_code,
            "request": raw_request, "response": raw_response, "ts": time.time(),
        })
        return {"status": resp.status_code, "headers": dict(resp.headers),
                "body": resp.text}

    # ---------- 原始报文渲染（回放用） ----------
    @staticmethod
    def _raw_request(prepared, data) -> str:
        lines = [f"{prepared.method} {prepared.url} HTTP/1.1"]
        lines += [f"{k}: {v}" for k, v in prepared.headers.items()]
        if data:
            lines += ["", str(data)]
        return "\n".join(lines)

    @staticmethod
    def _raw_response(resp, body_limit=4000) -> str:
        lines = [f"HTTP/1.1 {resp.status_code} {resp.reason}"]
        lines += [f"{k}: {v}" for k, v in resp.headers.items()]
        lines += ["", resp.text[:body_limit]]
        return "\n".join(lines)
