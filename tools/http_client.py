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
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise SafetyViolation("只允许 HTTP(S) 请求，其他协议已拦截")
        host = parsed.hostname or ""
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
        method = method.upper()
        req = requests.Request(method, url, headers=headers, data=data)
        prepared = self.session.prepare_request(req)
        redirects = 0
        while True:
            # 检查实际发送的 URL：重定向不能绕过白名单、限速或请求预算。
            self._check(prepared.url)
            wait = self.interval - (time.time() - self._last_ts)
            if wait > 0:
                time.sleep(wait)
            self._last_ts = time.time()
            self._count += 1
            raw_request = self._raw_request(prepared, prepared.body)
            try:
                resp = self.session.send(prepared, timeout=30, allow_redirects=False)
            except requests.RequestException as exc:
                self.traffic.append({
                    "method": prepared.method, "url": prepared.url, "status": 0,
                    "request": raw_request, "response": f"连接失败: {exc}",
                    "ts": time.time(),
                })
                raise
            self.traffic.append({
                "method": prepared.method, "url": resp.url, "status": resp.status_code,
                "request": raw_request, "response": self._raw_response(resp),
                "ts": time.time(),
            })
            if resp.next is None:
                return {"status": resp.status_code, "headers": dict(resp.headers),
                        "body": resp.text}
            if redirects >= self.session.max_redirects:
                raise requests.TooManyRedirects(
                    f"Exceeded {self.session.max_redirects} redirects.", response=resp
                )
            redirects += 1
            # Requests 负责相对 URL、Cookie、方法/请求体以及跨主机凭据处理。
            prepared = resp.next

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
