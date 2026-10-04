#!/usr/bin/env python3
"""Capture public Microsoft Learn lessons and render one combined PDF."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

VERSION = "1.0.0"
MAX_MODULES, MAX_UNITS = 100, 500
MAX_IMAGE_BYTES, MAX_TOTAL_IMAGE_BYTES = 15_000_000, 100_000_000
BODY_SELECTORS = (
    "#unit-inner-section", "#unit-body", "#unit-content", ".unit-content",
    "[data-bi-name='unit-content']", "main .content", "article .content",
    "main article", "article", "main",
)
REMOVE_SELECTORS = (
    "script, style, link, base, meta, noscript, nav, footer, "
    "[role='navigation'], [role='dialog'], .visually-hidden, .sr-only, "
    "#unit-top-nav, #unit-bottom-nav, #unit-controls, #unit-completion, #next-section, "
    "#unit-feedback, #feedback, .feedback, .unit-feedback, .next-unit, "
    ".pagination, .metadata, .unit-metadata, .page-metadata, .xp-tag, "
    ".xp-icon, .duration, .reading-time, .content-header, "
    "[data-bi-name='unit-continue'], [data-bi-name='feedback']"
)
FONT_STACKS = {
    "Times New Roman": '"Times New Roman", "Liberation Serif", serif',
    "Arial": 'Arial, "Liberation Sans", sans-serif',
    "Oswald": 'Oswald, sans-serif',
}
CSS = """
@page { size: PAPER; margin: 18mm 17mm 19mm;
    @bottom-left { content: "Microsoft Learn / local study copy";
                   font: 8px PDFFONT; color: #617283; }
    @bottom-right { content: counter(page) " / " counter(pages);
                    font: 8px PDFFONT; color: #617283; }
}
@page:first { @bottom-left { content: none; } @bottom-right { content: none; } }
* { box-sizing: border-box; }
body { font-family: PDFFONT; font-size: FONTSIZEpt; line-height: LINEHEIGHT;
       color: #17212b; margin: 0; overflow-wrap: anywhere; }
h1,h2,h3,h4,h5,h6 { line-height: 1.22; color: #142f43;
                   break-after: avoid-page; page-break-after: avoid; }
h1 { font-size: 26pt; } h2 { font-size: 18pt; }
h3 { font-size: 16pt; } h4 { font-size: 14pt; }
h5,h6 { font-size: 12pt; }
p { margin: 0 0 9pt; orphans: 3; widows: 3; }
li { margin: 3pt 0; } ul,ol { padding-left: 21pt; }
a { color: #125a8b; text-decoration: none; }
.cover { min-height: 230mm; display: flex; align-items: center;
         justify-content: center; text-align: center; break-after: page; }
.eyebrow { font: bold 10pt PDFFONT; letter-spacing: 1.2px;
           color: #426278; margin-bottom: 14pt; }
.cover h1 { margin: 0; font-size: 32pt; }
.small,.source { font-size: 9pt; line-height: 1.4; color: #526373; }
.source { margin: 5pt 0 13pt; overflow-wrap: anywhere; }
.toc { break-after: page; }
.toc ol { margin-top: 5pt; } .toc li { margin: 4pt 0; }
.module { break-before: page; }
.module-heading { border-bottom: 1pt solid #b9ccd8; padding-bottom: 9pt; }
.unit { margin-top: 20pt; }
.unit-title { margin-bottom: 5pt; }
.unit.new-page { break-before: page; }
.lesson h2 { font-size: 16pt; } .lesson h3 { font-size: 14pt; }
.lesson h4 { font-size: 12pt; }
.lesson p, .lesson li { text-align: justify; text-align-last: left;
    text-justify: inter-word; hyphens: auto; }
.lesson th p, .lesson td p, .lesson figcaption p { text-align: left; }
.source { text-align: left; hyphens: none; }
img,svg { max-width: 100%; height: auto; }
img { display: block; margin: 12pt auto; max-height: 218mm; object-fit: contain;
      break-inside: avoid; }
figure { margin: 12pt 0; } figcaption { font-size: 10pt; color: #526373; }
table { width: 100%; border-collapse: collapse; margin: 12pt 0;
        table-layout: auto; font-size: 10.5pt; line-height: 1.35; }
thead { display: table-header-group; } tfoot { display: table-footer-group; }
th,td { border: 0.6pt solid #cbd5df; padding: 7pt 8pt;
        vertical-align: middle; overflow-wrap: anywhere; }
th { background: #edf2f6; text-align: left; }
th:first-child,td:first-child { min-width: 18mm; }
tr { break-inside: avoid; }
pre { background: #f2f5f7; border: 0.6pt solid #d5dfe5; padding: 10pt;
      white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
      font: 9pt/1.45 Consolas, "Liberation Mono", monospace; text-align: left; }
code { font-family: Consolas, "Liberation Mono", monospace; font-size: 0.9em; }
blockquote,.NOTE,.TIP,.IMPORTANT,.WARNING,.CAUTION,.notice,.missing-media {
    border-left: 3pt solid #547c98; background: #f2f6f9;
    margin: 12pt 0; padding: 10pt 12pt; }
.WARNING,.CAUTION,.error { border-left-color: #a94f18; background: #fff4e9; }
.notice { font-size: 10pt; line-height: 1.45; }
fieldset { border: 0; padding: 0; margin: 10pt 0; }
legend { font-weight: bold; }
label { display: block; margin: 5pt 0; }
details { margin: 8pt 0; } summary { font-weight: bold; }
.tab-label { font-weight: bold; margin-top: 14pt; }
hr { border: 0; border-top: 1pt solid #d5dfe5; margin: 16pt 0; }
"""


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def soup_of(markup: str) -> Any:
    from bs4 import BeautifulSoup
    return BeautifulSoup(markup, "html.parser")


def canonical_url(value: str, base: str = "") -> str:
    """Accept actual HTTPS Learn path/module/unit links; never invent unit URLs."""
    u = urlsplit(urljoin(base, html.unescape(value.strip())))
    if (u.scheme != "https" or u.hostname != "learn.microsoft.com"
            or u.username or u.password or u.port not in (None, 443)):
        raise ValueError("Use an HTTPS URL on learn.microsoft.com.")
    parts = [p for p in u.path.split("/") if p]
    if (len(parts) not in (4, 5) or parts[1] != "training"
            or parts[2] not in ("paths", "modules")
            or (parts[2] == "paths" and len(parts) != 4)
            or any(p in (".", "..") or "/" in unquote(p)
                   or "\\" in unquote(p) for p in parts)):
        raise ValueError("Use a Microsoft Learn learning-path or module URL.")
    path = "/" + "/".join(parts) + ("/" if len(parts) == 4 else "")
    return urlunsplit(("https", "learn.microsoft.com", path, "", ""))


def url_kind(url: str) -> str:
    parts = urlsplit(url).path.strip("/").split("/")
    return "unit" if len(parts) == 5 else ("path" if parts[2] == "paths" else "module")


def input_urls(text: str) -> list[str]:
    urls = list(dict.fromkeys(canonical_url(x) for x in text.splitlines() if x.strip()))
    if not urls:
        raise ValueError("Paste at least one learning-path or module URL.")
    if len(urls) > 10:
        raise ValueError("Use at most 10 input URLs per export.")
    if any(url_kind(x) == "unit" for x in urls):
        raise ValueError("Paste the parent module URL, not a single lesson URL.")
    return urls


def title_of(soup: Any, default: str = "Microsoft Learn") -> str:
    node = soup.select_one("main h1, h1")
    return node.get_text(" ", strip=True) if node else default


def advertised_count(soup: Any, noun: str) -> int | None:
    text = (soup.select_one("main") or soup).get_text(" ", strip=True)
    match = re.search(r"\b(\d+)\s+" + noun + r"\b", text, flags=re.I)
    return int(match.group(1)) if match else None


def link_list(soup: Any, base: str, wanted: str) -> list[str]:
    root = soup.select_one("main") or soup
    parent = urlsplit(base).path.rstrip("/") + "/"

    def collect(node: Any) -> list[str]:
        result = []
        for a in node.select("a[href]"):
            try:
                url = canonical_url(a["href"], base)
            except (ValueError, TypeError):
                continue
            if url_kind(url) != wanted:
                continue
            if wanted == "unit" and not urlsplit(url).path.startswith(parent):
                continue
            if url not in result:
                result.append(url)
        return result

    # Prefer a curriculum list over a Resume/Start link elsewhere on the page.
    if wanted == "unit":
        candidates = [collect(n) for n in root.select("ol, ul, #unit-list, .unit-list")]
        best = max(candidates, key=len, default=[])
        all_links = collect(root)
        if best and set(best) == set(all_links):
            return best
        if best:
            return best + [u for u in all_links if u not in best]
    return collect(root)


class ExportError(RuntimeError):
    pass


class Exporter:
    def __init__(self, page: Any, context: Any, config: dict, emit: Callable):
        self.page, self.context, self.config, self.emit = page, context, config, emit
        self.warnings: list[dict] = []
        self.images: dict[str, str] = {}
        self.image_bytes = 0
        self.last_request = 0.0
        self.robots: RobotFileParser | None = None

    def warn(self, url: str, message: str) -> None:
        item = {"url": url, "message": message}
        if item not in self.warnings:
            self.warnings.append(item)
            self.emit("warning", message=f"{message} | {url}")

    def load_robots(self) -> None:
        try:
            response = self.context.request.get(
                "https://learn.microsoft.com/robots.txt", timeout=20000)
            try:
                if response.ok:
                    self.robots = RobotFileParser()
                    self.robots.parse(response.text().splitlines())
                elif response.status != 404:
                    self.warn("https://learn.microsoft.com/robots.txt",
                              "Could not verify robots.txt; review site access rules.")
            finally:
                response.dispose()
        except Exception:
            self.warn("https://learn.microsoft.com/robots.txt",
                      "Could not retrieve robots.txt; review site access rules.")

    def visit(self, url: str) -> tuple[Any, str]:
        from playwright.sync_api import Error as BrowserError
        if self.robots and not self.robots.can_fetch("LearnPDFExporter", url):
            raise ExportError(f"Crawling disallowed by robots.txt: {url}")
        delay = max(0.5, float(self.config.get("delay", 1.0)))
        last_error = "Unknown navigation error"
        for attempt in range(3):
            remaining = delay - (time.monotonic() - self.last_request)
            if remaining > 0:
                self.page.wait_for_timeout(int(remaining * 1000))
            self.last_request = time.monotonic()
            try:
                response = self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if response and response.status in (429, 500, 502, 503, 504):
                    retry = response.headers.get("retry-after", "")
                    pause = max(3 * (attempt + 1), int(retry) if retry.isdigit() else 0)
                    self.emit("log", message=f"HTTP {response.status}; retrying {url}")
                    self.page.wait_for_timeout(min(120, pause) * 1000)
                    last_error = f"HTTP {response.status}"
                    continue
                if response and response.status >= 400:
                    raise ExportError(f"HTTP {response.status}: {url}")
                final = canonical_url(self.page.url)
                if url_kind(final) != url_kind(url):
                    raise ExportError(f"Unexpected redirect: {url} -> {final}")
                self.page.wait_for_selector("main, article", state="attached", timeout=20000)
                # Allow the public curriculum/assessment scripts to populate their DOM.
                self.page.wait_for_timeout(1000)
                soup = soup_of(self.page.content())
                heading = title_of(soup, "").lower()
                if heading in ("access denied", "sign in", "404 - page not found", "page not found"):
                    raise ExportError(f"Page unavailable or sign-in required: {url}")
                return soup, final
            except ExportError:
                raise
            except (BrowserError, ValueError) as exc:
                last_error = str(exc)
                if attempt < 2:
                    self.page.wait_for_timeout((attempt + 1) * 2500)
        raise ExportError(f"Could not load {url}: {last_error}")

    def children(self, soup: Any, url: str, kind: str) -> list[str]:
        noun = "Modules" if kind == "module" else "Units"
        expected = advertised_count(soup, noun)
        links = link_list(soup, url, kind)
        # A second DOM read covers slower dynamically populated lists.
        if not links or (expected is not None and len(links) != expected):
            self.page.wait_for_timeout(3500)
            soup = soup_of(self.page.content())
            expected = advertised_count(soup, noun)
            links = link_list(soup, url, kind)
        if not links:
            raise ExportError(f"No {noun.lower()} discovered: {url}. The page layout may have changed.")
        if expected is not None and len(links) != expected:
            raise ExportError(f"Incomplete discovery: page says {expected} {noun.lower()}, "
                              f"but found {len(links)}. Refusing to call this complete: {url}")
        if expected is None:
            self.warn(url, f"No readable {noun.lower()} count; curriculum coverage needs review.")
        return links

    def discover(self, roots: list[str]) -> tuple[list[dict], list[dict], list[dict]]:
        sources, modules, errors = [], [], []
        pending: dict[str, list[str]] = {}
        for index, root in enumerate(roots, 1):
            self.emit("progress", message=f"Reading input {index}/{len(roots)}", fraction=0.03)
            try:
                soup, final = self.visit(root)
                name = title_of(soup)
                children = self.children(soup, final, "module") if url_kind(final) == "path" else [final]
                sources.append({"url": final, "title": name, "modules": children})
                for child in children:
                    pending.setdefault(child, []).append(name)
            except Exception as exc:
                errors.append({"url": root, "stage": "discovery", "message": str(exc)})
        if len(pending) > MAX_MODULES:
            raise ExportError(f"Limit: {MAX_MODULES} modules per export. Use fewer input URLs.")
        for index, (url, paths) in enumerate(pending.items(), 1):
            self.emit("progress", message=f"Discovering module {index}/{len(pending)}",
                      fraction=0.05 + 0.10 * index / max(1, len(pending)))
            try:
                soup, final = self.visit(url)
                units = self.children(soup, final, "unit")
                # Redirected aliases should not duplicate an already discovered module.
                existing = next((m for m in modules if m["url"] == final), None)
                if existing:
                    existing["paths"] = list(dict.fromkeys(existing["paths"] + paths))
                    continue
                modules.append({"title": title_of(soup), "url": final, "paths": paths,
                                "expected_units": advertised_count(soup, "Units"),
                                "unit_urls": units, "units": []})
            except Exception as exc:
                errors.append({"url": url, "stage": "discovery", "message": str(exc)})
        if sum(len(m["unit_urls"]) for m in modules) > MAX_UNITS:
            raise ExportError(f"Limit: {MAX_UNITS} lesson pages per export. Use fewer input URLs.")
        return sources, modules, errors

    def content_fragment(self, soup: Any, url: str) -> tuple[str, str, bool]:
        custom = self.config.get("selector", "").strip()
        selectors = (custom,) if custom else BODY_SELECTORS
        selected, selector = None, ""
        for selector in selectors:
            candidates = soup.select(selector)
            if candidates:
                selected = max(candidates, key=lambda e: len(e.get_text(" ", strip=True)))
                if len(selected.get_text(" ", strip=True)) >= 35 or selected.find("img"):
                    break
                selected = None
        if selected is None:
            raise ExportError(f"Lesson content not found: {url}. Try an explicit CSS selector in Advanced options.")
        if selector == "main":
            self.warn(url, "Used main-content fallback; check this lesson for leftover interface text.")
        # Clone the selected element. Drop screen-hidden UI/answer feedback, but keep
        # inactive instructional tabs and expandable lesson explanations.
        index = soup.select(selector).index(selected)
        fragment = self.page.locator(selector).nth(index).evaluate(r"""el => {
            const copy = el.cloneNode(true);
            const a = [el, ...el.querySelectorAll('*')];
            const b = [copy, ...copy.querySelectorAll('*')];
            for (let i = 1; i < a.length; i++) {
                const n = a[i], c = b[i], s = getComputedStyle(n);
                if ((s.display === 'none' || s.visibility === 'hidden' || n.hidden) &&
                    !n.closest('[role="tabpanel"], details')) c.setAttribute('data-export-remove', '1');
                if (n.tagName === 'IMG') {
                    c.setAttribute('src', n.currentSrc || n.getAttribute('data-src') || n.src);
                }
                if (n.getAttribute('role') === 'tabpanel') {
                    const label = document.getElementById(n.getAttribute('aria-labelledby'));
                    if (label) c.setAttribute('data-export-tab', label.textContent.trim());
                }
            }
            copy.querySelectorAll('[data-export-remove]').forEach(n => n.remove());
            return copy.outerHTML;
        }""")
        doc = soup_of(fragment)
        for node in list(doc.select(REMOVE_SELECTORS)):
            if node.parent is not None:
                node.decompose()
        # The unit title is printed separately by the book template.
        for node in list(doc.select("h1")):
            node.decompose()
        for node in list(doc.select("[role='tablist']")):
            node.decompose()
        for panel in doc.select("[data-export-tab]"):
            label = doc.new_tag("p", attrs={"class": "tab-label"})
            label.string = panel["data-export-tab"]
            panel.insert(0, label)
        interactive = False
        for node in list(doc.select("iframe, video, audio, object, embed, canvas")):
            if node.parent is None:
                continue
            interactive = True
            raw = node.get("src") or node.get("data") or ""
            source = node.find("source", src=True)
            if not raw and source:
                raw = source["src"]
            target = urljoin(url, raw) if raw else url
            if urlsplit(target).scheme not in ("https", "http"):
                target = url
            note = doc.new_tag("p", attrs={"class": "notice"})
            note.append("Interactive media is not embedded in this PDF. ")
            a = doc.new_tag("a", href=target)
            a.string = "Open the original media or lesson online."
            note.append(a)
            node.replace_with(note)
        if interactive:
            self.warn(url, "Video, audio, or interactive media is represented by an online link.")
        # Keep visible assessment questions/options, not submit buttons or inputs.
        for node in list(doc.select("input, select, textarea, button")):
            if node.parent is not None:
                node.decompose()
        for node in list(doc.select("form")):
            node.unwrap()
        for node in list(doc.select("picture")):
            for source in node.find_all("source"):
                source.decompose()
            node.unwrap()
        for node in list(doc.select("a")):
            text = node.get_text(" ", strip=True)
            if re.fullmatch(r"(Next unit.*|Continue|Check your answers|Sign in|Expand table|"
                            r"Collapse table|Copy|Read in English)", text, flags=re.I):
                node.decompose()
        # Sanitize attributes. In particular, never execute copied page JavaScript.
        for node in doc.find_all(True):
            if node.parent is None:
                continue
            if node.name in ("script", "foreignobject"):
                node.decompose()
                continue
            if node.name == "svg" and not (node.get("viewBox") or node.get("viewbox")):
                width, height = node.get("width", ""), node.get("height", "")
                if str(width).isdigit() and str(height).isdigit():
                    node["viewBox"] = f"0 0 {width} {height}"
            for attr in list(node.attrs):
                if (attr.lower().startswith("on") or attr in
                    ("style", "srcdoc", "action", "formaction", "hidden", "aria-hidden",
                     "width", "height", "loading", "srcset", "sizes", "integrity", "nonce")):
                    del node.attrs[attr]
            if node.name == "details":
                node["open"] = "open"
            if node.name == "a" and node.get("href"):
                href = urljoin(url, node["href"])
                if urlsplit(href).scheme in ("https", "http", "mailto"):
                    node["href"] = href
                else:
                    del node.attrs["href"]
        # Prefix IDs to avoid collisions when many lessons contain the same headings.
        prefix = "u-" + hashlib.sha1(url.encode()).hexdigest()[:10] + "-"
        for node in doc.select("[id]"):
            old = node["id"]
            node["id"] = prefix + old
            for ref in doc.select("[href]"):
                if ref.get("href") == "#" + old:
                    ref["href"] = "#" + prefix + old
            for ref in doc.select("[fill], [clip-path], [mask], [filter]"):
                for attr in ("fill", "clip-path", "mask", "filter"):
                    if ref.get(attr) == f"url(#{old})":
                        ref[attr] = f"url(#{prefix}{old})"
        for img in list(doc.find_all("img")):
            if not self.config.get("images", True):
                img.decompose()
                continue
            raw = img.get("src") or img.get("data-src") or ""
            target = urljoin(url, raw)
            try:
                img["src"] = self.image_data(target, url)
            except Exception as exc:
                display_target = "[inline image]" if target.startswith("data:") else target
                self.warn(url, f"Image unavailable: {display_target} ({str(exc)[:180]})")
                note = doc.new_tag("p", attrs={"class": "missing-media"})
                note.string = f"[Image unavailable: {img.get('alt') or display_target}]"
                img.replace_with(note)
        assessment = bool(re.search(r"knowledge.check|assessment|quiz", url, flags=re.I))
        # Do not pretend that assessment login instructions are the questions.
        if assessment and not doc.select("label, fieldset, [role='radiogroup'], .question"):
            self.warn(url, "Assessment page captured; verify that its questions are visible in the PDF.")
        text = doc.get_text(" ", strip=True)
        if len(text) < 35 and not doc.find(["img", "svg"]):
            raise ExportError(f"Lesson is empty after removing navigation: {url}")
        return str(doc), selector, interactive

    def image_data(self, url: str, lesson: str) -> str:
        if url in self.images:
            return self.images[url]
        if url.startswith("data:image/") and ";base64," in url:
            if len(url) > MAX_IMAGE_BYTES * 1.4:
                raise ExportError("Inline image exceeds the size limit")
            raw_data = base64.b64decode(url.split(",", 1)[1], validate=True)
            if len(raw_data) > MAX_IMAGE_BYTES or self.image_bytes + len(raw_data) > MAX_TOTAL_IMAGE_BYTES:
                raise ExportError("Image size budget exceeded")
            self.image_bytes += len(raw_data)
            self.images[url] = url
            return url
        u = urlsplit(url)
        # Do not let an imported image request a local file or arbitrary network host.
        suffixes = ("microsoft.com", "microsoftusercontent.com", "azureedge.net",
                    "akamaized.net", "msftstatic.com", "githubusercontent.com",
                    "windows.net", "visualstudio.com", "aka.ms")
        host = u.hostname or ""
        if (u.scheme != "https" or u.username or u.password or u.port not in (None, 443)
                or not any(host == h or host.endswith("." + h) for h in suffixes)):
            raise ExportError("Image host is outside the allowed public-content hosts")
        response = self.context.request.get(url, timeout=30000, headers={"Referer": lesson})
        try:
            if not response.ok:
                raise ExportError(f"HTTP {response.status}")
            mime = response.headers.get("content-type", "").split(";")[0].lower()
            if not mime.startswith("image/"):
                raise ExportError(f"Unexpected image content type: {mime}")
            declared = response.headers.get("content-length", "0")
            if declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
                raise ExportError("Image exceeds 15 MB")
            data = response.body()
            if len(data) > MAX_IMAGE_BYTES or self.image_bytes + len(data) > MAX_TOTAL_IMAGE_BYTES:
                raise ExportError("Image size budget exceeded")
            value = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
            self.images[url] = value
            self.image_bytes += len(data)
            return value
        finally:
            response.dispose()


def build_html(title: str, modules: list[dict], report: dict, config: dict) -> str:
    css = CSS.replace("PAPER", config.get("paper", "A4"))
    css = css.replace("FONTSIZE", str(config.get("font_size", 12)))
    css = css.replace("LINEHEIGHT", str(config.get("line_height", 1.5)))
    font = config.get("font", "Times New Roman")
    css = css.replace("PDFFONT", FONT_STACKS.get(font, FONT_STACKS["Times New Roman"]))
    if font == "Oswald":
        font_path = Path(__file__).resolve().parent.parent / "frontend/assets/fonts/Oswald.ttf"
        font_data = base64.b64encode(font_path.read_bytes()).decode("ascii")
        css = ('@font-face { font-family: Oswald; font-style: normal; font-weight: 200 700; '
               'src: url(data:font/ttf;base64,' + font_data + ') format("truetype"); }' + css)
    partial = bool(report["errors"])
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           # A second layer of defense for the downloadable HTML.
           '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
           'img-src data:; style-src \'unsafe-inline\'; font-src data:; '
           'base-uri \'none\'; form-action \'none\'">',
           f'<title>{esc(title)}</title><style>{css}</style></head><body>',
           f'<section class="cover"><h1>{esc(title)}</h1></section>']
    contents_title = "Contents — PARTIAL EXPORT" if partial else "Contents"
    out.append(f'<section class="toc"><h2>{contents_title}</h2><ol>')
    for mi, module in enumerate(modules, 1):
        out.append(f'<li><a href="#module-{mi}">{esc(module["title"])}</a><ol>')
        for ui, unit in enumerate(module["units"], 1):
            suffix = " [NOT EXTRACTED]" if unit["status"] != "captured" else ""
            out.append(f'<li><a href="#unit-{mi}-{ui}">{esc(unit["title"] + suffix)}</a></li>')
        out.append('</ol></li>')
    out.append('</ol></section>')
    for mi, module in enumerate(modules, 1):
        out.append(f'<section class="module" id="module-{mi}">'
                   f'<div class="eyebrow">MODULE {mi}</div>'
                   f'<h2 class="module-heading">{esc(module["title"])}</h2>'
                   f'<p class="small">{esc(" / ".join(module["paths"]))}</p>'
                   f'<p class="source">Module source: <a href="{esc(module["url"])}">{esc(module["url"])}</a></p>')
        for ui, unit in enumerate(module["units"], 1):
            page_break = " new-page" if config.get("unit_break") and ui > 1 else ""
            out.append(f'<article class="unit{page_break}" id="unit-{mi}-{ui}">'
                       f'<h3 class="unit-title">{mi}.{ui} {esc(unit["title"])}</h3>'
                       f'<p class="source">Source: <a href="{esc(unit["url"])}">{esc(unit["url"])}</a></p>'
                       f'<div class="lesson">{unit["html"]}</div></article>')
        out.append('</section>')
    if report["errors"] or report["warnings"]:
        out.append('<section class="module"><h2>Export notes</h2>')
        for label, items in (("Extraction errors", report["errors"]), ("Warnings", report["warnings"])):
            if items:
                out.append(f'<h3>{label}</h3><ol>')
                for item in items:
                    out.append(f'<li>{esc(item["message"])}<p class="source">'
                               f'<a href="{esc(item["url"])}">{esc(item["url"])}</a></p></li>')
                out.append('</ol>')
        out.append('</section>')
    out.append('</body></html>')
    return "".join(out)


def print_pdf(browser: Any, content: str, output: Path, config: dict) -> list[dict]:
    import pymupdf

    # Use an isolated, script-disabled page, not the live site's own print layout.
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    try:
        page.set_default_timeout(120000)
        page.set_content(content, wait_until="load", timeout=120000)
        page.emulate_media(media="print")
        page.evaluate("document.fonts.ready")
        page.wait_for_function("Array.from(document.images).every(i => i.complete)", timeout=45000)
        failed = page.locator("img").evaluate_all(
            "imgs => imgs.filter(i => !i.naturalWidth).map(i => i.alt || 'Unrenderable embedded image')")
        if failed:
            raise ExportError("An embedded image could not be decoded by Chromium. "
                              "Try exporting without images. Details: " + "; ".join(failed[:5]))
        page.pdf(path=str(output), format=config.get("paper", "A4"),
                 print_background=True, prefer_css_page_size=True,
                 display_header_footer=False, tagged=True, outline=True)
        # Draw within the physical page margins, independent of HTML pagination.
        with pymupdf.open(output) as document:
            inset = 7 * 72 / 25.4
            for sheet in document:
                frame = pymupdf.Rect(inset, inset, sheet.rect.width - inset, sheet.rect.height - inset)
                sheet.draw_rect(frame, color=(0.545, 0.600, 0.647), width=0.65, overlay=False)
            document.saveIncr()
        if output.stat().st_size < 500:
            raise ExportError("PDF renderer returned an unexpectedly empty file.")
        return []
    finally:
        context.close()


def run_export(config: dict, output_dir: Path, emit: Callable) -> dict:
    from playwright.sync_api import sync_playwright
    roots = input_urls("\n".join(config["urls"]))
    report: dict = {"app_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                    "inputs": roots, "status": "running", "errors": [], "warnings": [],
                    "sources": [], "modules": [], "summary": {}}
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "extraction_report.json"
    try:
        with sync_playwright() as p:
            launch_args: dict = {"headless": True, "executable_path": p.chromium.executable_path}
            # Optional explicit executable for managed machines/offline renderer tests.
            if os.environ.get("LEARN_PDF_BROWSER"):
                launch_args["executable_path"] = os.environ["LEARN_PDF_BROWSER"]
            browser = p.chromium.launch(**launch_args)
            try:
                context = browser.new_context(viewport={"width": 1366, "height": 1000},
                                              reduced_motion="reduce")
                page = context.new_page()
                exporter = Exporter(page, context, config, emit)
                report["warnings"] = exporter.warnings
                exporter.load_robots()
                sources, modules, errors = exporter.discover(roots)
                report["sources"], report["errors"] = sources, errors
                total = sum(len(m["unit_urls"]) for m in modules)
                if not total:
                    raise ExportError("No lesson pages were discovered. See the extraction report.")
                if errors and not config.get("allow_partial", False):
                    raise ExportError("Curriculum discovery failed for one or more URLs. "
                                      "No PDF was created. See the extraction report.")
                done = captured = 0
                for module in modules:
                    for url in module["unit_urls"]:
                        done += 1
                        emit("progress", message=f"Reading lesson {done}/{total}: {module['title']}",
                             fraction=0.16 + 0.72 * done / total)
                        unit = {"url": url, "title": unquote(urlsplit(url).path.split("/")[-1]),
                                "status": "failed", "selector": "", "html": ""}
                        try:
                            soup, final = exporter.visit(url)
                            expected_parent = urlsplit(module["url"]).path.rstrip("/") + "/"
                            if not urlsplit(final).path.startswith(expected_parent):
                                raise ExportError(f"Lesson redirected outside its assigned module: {url} -> {final}")
                            if any(u["url"] == final and u["status"] == "captured" for u in module["units"]):
                                raise ExportError(f"Duplicate lesson redirect would omit a distinct unit: {url} -> {final}")
                            unit["url"], unit["title"] = final, title_of(soup, unit["title"])
                            fragment, selector, interactive = exporter.content_fragment(soup, final)
                            unit.update(html=fragment, selector=selector, status="captured",
                                        interactive_media=interactive)
                            captured += 1
                            emit("log", message=f"Captured: {unit['title']}")
                        except Exception as exc:
                            message = str(exc)
                            errors.append({"url": url, "stage": "lesson", "message": message})
                            unit["html"] = f'<div class="notice error">NOT EXTRACTED: {esc(message)}</div>'
                            emit("warning", message=f"Not extracted: {url}: {message}")
                        module["units"].append(unit)
                report["summary"] = {"modules": len(modules), "discovered_units": total,
                                     "exported_units": captured, "failed_units": total - captured}
                report["modules"] = [
                    {**{k: v for k, v in m.items() if k != "units"},
                     "units": [{k: v for k, v in u.items() if k != "html"} for u in m["units"]]}
                    for m in modules]
                if captured == 0:
                    raise ExportError("No lesson content was captured. No PDF was created.")
                if errors and not config.get("allow_partial", False):
                    raise ExportError(f"{len(errors)} extraction error(s). No PDF was created because "
                                      "'Allow a clearly marked partial PDF' is disabled.")
                title = config.get("title", "").strip() or (sources[0]["title"] if len(sources) == 1
                                                           else "Microsoft Learn - Combined Study Guide")
                report["title"] = title
                report["status"] = "partial" if errors else ("captured_with_warnings" if exporter.warnings else "captured")
                content = build_html(title, modules, report, config)
                (output_dir / "combined_lessons.html").write_text(content, encoding="utf-8")
                emit("progress", message="Building the combined PDF...", fraction=0.92)
                print_pdf(browser, content, output_dir / "combined_lessons.pdf", config)
                emit("progress", message="PDF ready.", fraction=1.0)
            finally:
                browser.close()
    except Exception as exc:
        report["status"] = "failed"
        report["fatal_error"] = str(exc)
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def worker_main(config_path: str) -> int:
    def emit(kind: str, **kwargs: Any) -> None:
        print(json.dumps({"type": kind, **kwargs}, ensure_ascii=True), flush=True)
    try:
        config_file = Path(config_path)
        config = json.loads(config_file.read_text(encoding="utf-8"))
        run_export(config, config_file.parent, emit)
        emit("done", message="Export completed.")
        return 0
    except Exception as exc:
        message = str(exc)
        if "Executable doesn't exist" in message:
            message = "Chromium is not installed. Run: python -m playwright install chromium"
        emit("error", message=message)
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--worker":
        raise SystemExit("Usage: python exporter.py --worker job.json")
    raise SystemExit(worker_main(sys.argv[2]))
