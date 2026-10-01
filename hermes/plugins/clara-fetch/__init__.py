"""clara-fetch: web_extract without a paid API.

Hermes's free search backends (SearXNG, DuckDuckGo) can only search; reading a page needs Exa, Firecrawl, Tavily or
Parallel, all paid. This provider fetches the page itself and turns it into text with trafilatura (falling back to a
plain HTML-to-text pass). It never fetches loopback, private, link-local or reserved addresses, including after a
redirect, so a web page can't steer Clara into the PC's own services.
"""
from __future__ import annotations

import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse

from agent.web_search_provider import WebSearchProvider

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = 20.0
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


def _public(host: str) -> bool:
    """True if every address the host resolves to is on the public internet."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            return False
    return bool(infos)


class _Text(HTMLParser):
    """Fallback HTML-to-text when trafilatura isn't installed."""
    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"}
    BLOCK = {"p", "div", "li", "br", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.out.append("\n")
            if tag in ("h1", "h2", "h3"):
                self.out.append("## ")
            elif tag == "li":
                self.out.append("- ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)

    def text(self) -> str:
        t = re.sub(r"[ \t]+", " ", "".join(self.out))
        lines = [ln.strip() for ln in t.split("\n")]
        lines = [ln for ln in lines if ln not in ("-", "##", "- ##")]   # empty list items and headings (icons, menus)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _to_text(page: str, url: str) -> tuple[str, str]:
    try:
        import trafilatura
        body = trafilatura.extract(page, url=url, output_format="markdown", include_links=True, include_tables=True) or ""
        meta = trafilatura.extract_metadata(page)
        title = (meta.title if meta and meta.title else "") or ""
        if body:
            return title, body
    except ImportError:
        pass
    p = _Text()
    p.feed(page)
    return html.unescape(p.title.strip()), p.text()


class ClaraFetchProvider(WebSearchProvider):
    @property
    def name(self) -> str:
        return "clara-fetch"

    @property
    def display_name(self) -> str:
        return "Clara page reader (local)"

    def is_available(self) -> bool:
        return True

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    async def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        import httpx
        out = []
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": UA}) as client:
            for url in urls:
                out.append(await self._one(client, url))
        return out

    async def _one(self, client, url: str) -> Dict[str, Any]:
        current = url
        try:
            for _ in range(6):
                u = urlparse(current)
                if u.scheme not in ("http", "https") or not u.hostname:
                    return {"url": url, "title": "", "content": "", "raw_content": "", "error": "Only http(s) web addresses can be read."}
                if not _public(u.hostname):
                    return {"url": url, "title": "", "content": "", "raw_content": "",
                            "error": "That address is on a private or local network; Clara only reads public web pages."}
                async with client.stream("GET", current) as r:
                    if r.is_redirect and r.headers.get("location"):
                        current = urljoin(current, r.headers["location"])
                        continue
                    if r.status_code >= 400:
                        return {"url": url, "title": "", "content": "", "raw_content": "", "error": f"HTTP {r.status_code}"}
                    kind = r.headers.get("content-type", "")
                    if "html" not in kind and "text" not in kind:
                        return {"url": url, "title": "", "content": "", "raw_content": "",
                                "error": f"Not a web page ({kind or 'unknown type'}); open it with the browser tool instead."}
                    data = b""
                    async for chunk in r.aiter_bytes():
                        data += chunk
                        if len(data) > MAX_BYTES:
                            break
                    page = data.decode(r.encoding or "utf-8", errors="replace")
                title, text = _to_text(page, current)
                if not text:
                    return {"url": url, "title": title, "content": "", "raw_content": "",
                            "error": "No readable text (the page may need JavaScript); use the browser tool instead."}
                return {"url": url, "title": title, "content": text, "raw_content": text, "metadata": {"final_url": current}}
            return {"url": url, "title": "", "content": "", "raw_content": "", "error": "Too many redirects."}
        except Exception as e:  # network errors, timeouts
            return {"url": url, "title": "", "content": "", "raw_content": "", "error": f"Couldn't fetch the page: {e}"}


def register(ctx) -> None:
    ctx.register_web_search_provider(ClaraFetchProvider())
