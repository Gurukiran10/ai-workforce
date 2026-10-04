"""Playwright browser session with generic, selector-free perception.

Every action returns an Observation: what the page looks like *after* the action,
plus side effects a human would notice (HTTP errors, downloads, dialogs).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

PERCEPTION_JS = (Path(__file__).parent / "perception.js").read_text(encoding="utf-8")

FORM_VALUES_JS = """(id) => {
  const el = document.querySelector(`[data-agent-id="${id}"]`);
  if (!el) return null;
  const form = el.form || el.closest('form');
  const out = {};
  if (!form) return out;
  for (const f of form.querySelectorAll('input:not([type=hidden]):not([type=submit]), select, textarea')) {
    let label = f.getAttribute('aria-label') || '';
    if (!label && f.id) { const l = document.querySelector(`label[for="${CSS.escape(f.id)}"]`); if (l) label = l.innerText; }
    label = (label || f.name || '').replace(/\\s+/g, ' ').trim();
    out[label] = f.tagName === 'SELECT' ? (f.selectedIndex >= 0 ? f.options[f.selectedIndex].text : '') : f.value;
  }
  return out;
}"""


class BrowserActionError(Exception):
    def __init__(self, error_type: str, message: str, hint: str = ""):
        super().__init__(message)
        self.error_type, self.message, self.hint = error_type, message, hint


@dataclass
class Observation:
    url: str
    title: str
    text: str
    alerts: list[str]
    elements: list[dict]
    network: list[str] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)
    dialogs: list[str] = field(default_factory=list)
    screenshot: str | None = None

    @property
    def http_errors(self) -> list[str]:
        return [n for n in self.network if int(n.rsplit(" ", 1)[-1]) >= 400]

    def element(self, eid: int) -> dict | None:
        return next((e for e in self.elements if e["id"] == eid), None)

    def render(self, max_text: int = 2500, max_elements: int = 120) -> str:
        lines = [f"URL: {self.url}", f"Title: {self.title}"]
        if self.network:
            lines.append("HTTP during last action: " + "; ".join(self.network[-6:]))
        if self.http_errors:
            lines.append("!! HTTP ERROR: " + "; ".join(self.http_errors))
        if self.downloads:
            lines.append("Downloaded files (use read_file): " + ", ".join(self.downloads))
        if self.dialogs:
            lines.append("Browser dialogs (auto-dismissed): " + " | ".join(self.dialogs))
        if self.alerts:
            lines.append("Page messages: " + " | ".join(a for a in self.alerts if a))
        text = self.text if len(self.text) <= max_text else self.text[:max_text] + f"\n...[truncated {len(self.text) - max_text} chars; use read_page(full=true)]"
        lines += ["<page_text untrusted=\"true\">", text, "</page_text>", "Interactive elements:"]
        for e in self.elements[:max_elements]:
            desc = f"[{e['id']}] {e['tag']}"
            if e.get("type") and e["tag"] == "input":
                desc += f"[{e['type']}]"
            desc += f' "{e["label"]}"'
            if "value" in e and e["tag"] != "a" and e.get("type") not in ("submit", "button"):
                desc += f' value="{str(e["value"])[:80]}"'
            if e.get("options"):
                desc += " options=" + "|".join(e["options"][:25])
            if e.get("href"):
                desc += f" -> {e['href']}"
            if e.get("form"):
                desc += f" (form {e['form']})"
            lines.append(desc)
        if len(self.elements) > max_elements:
            lines.append(f"... {len(self.elements) - max_elements} more elements (scroll or read_page)")
        return "\n".join(lines)


class Browser:
    def __init__(self, workspace: Path, screens_dir: Path, allowed_origins: list[str], headless: bool = True):
        self.workspace, self.screens_dir = workspace, screens_dir
        self.allowed = [o.rstrip("/") for o in allowed_origins]
        self.downloads_dir = workspace / "downloads"
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        screens_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=headless, slow_mo=150 if not headless else 0)
        except PlaywrightError:  # chromium not installed -> fall back to Edge, preinstalled on Windows
            self._browser = self._pw.chromium.launch(channel="msedge", headless=headless)
        self._context = self._browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
        self._context.set_default_timeout(10_000)
        self.page = self._context.new_page()
        self._net: list[str] = []
        self._pending_downloads = []
        self._dialogs: list[str] = []
        self.page.on("response", self._on_response)
        self.page.on("download", lambda d: self._pending_downloads.append(d))
        self.page.on("dialog", self._on_dialog)
        self.last: Observation | None = None
        self._shot_no = 0

    # -- event hooks
    def _on_response(self, resp):
        if resp.request.resource_type in ("document", "xhr", "fetch"):
            path = urlparse(resp.url).path
            self._net.append(f"{resp.request.method} {path} -> {resp.status}")

    def _on_dialog(self, dialog):
        self._dialogs.append(dialog.message)
        dialog.dismiss()

    # -- core
    def _run(self, action) -> Observation:
        self._net, self._dialogs = [], []
        n_blocked = len(getattr(self, "blocked_writes", []))
        try:
            action()
        except PlaywrightTimeout as e:
            raise BrowserActionError("timeout", f"Action timed out: {str(e).splitlines()[0]}",
                                     "The page may be slow or the element not actionable. Re-observe and retry or choose another element.")
        except PlaywrightError as e:
            # navigating straight to a file URL raises "Download is starting": that's a download, not a failure
            if "download is starting" not in str(e).lower():
                if len(getattr(self, "blocked_writes", [])) > n_blocked:
                    raise BrowserActionError("read_only", "This action sends a data-changing request; this session is read-only "
                                             f"and it was blocked: {', '.join(self.blocked_writes[n_blocked:])}",
                                             "Verify by reading pages and files only.")
                raise BrowserActionError("browser_error", str(e).splitlines()[0], "Re-observe the page (read_page) before retrying.")
            self.page.wait_for_timeout(500)
        try:
            self.page.wait_for_load_state("load", timeout=10_000)
        except PlaywrightTimeout:
            pass
        self.page.wait_for_timeout(300)
        saved = []
        for d in self._pending_downloads:
            target = self.downloads_dir / d.suggested_filename
            d.save_as(target)
            saved.append(str(target.relative_to(self.workspace)).replace("\\", "/"))
        self._pending_downloads = []
        obs = self.observe(network=list(self._net), downloads=saved, dialogs=list(self._dialogs))
        blocked = getattr(self, "blocked_writes", [])[n_blocked:]
        if blocked:
            obs.alerts = [f"BLOCKED (read-only session, nothing was changed): {', '.join(blocked)}"] + obs.alerts
        return obs

    def observe(self, network=None, downloads=None, dialogs=None) -> Observation:
        snap = self.page.evaluate(PERCEPTION_JS)
        self._shot_no += 1
        shot = self.screens_dir / f"{self._shot_no:03d}.png"
        try:
            self.page.screenshot(path=str(shot), full_page=True)
        except PlaywrightError:
            shot = None
        self.last = Observation(url=snap["url"], title=snap["title"], text=snap["text"], alerts=snap["alerts"],
                                elements=snap["elements"], network=network or [], downloads=downloads or [],
                                dialogs=dialogs or [], screenshot=str(shot) if shot else None)
        return self.last

    def _loc(self, eid: int):
        loc = self.page.locator(f'[data-agent-id="{int(eid)}"]')
        if loc.count() == 0:
            raise BrowserActionError("stale_element", f"No element with id {eid} on the current page.",
                                     "Element ids change after every page update. Use the ids from the latest observation.")
        return loc.first

    def check_url(self, url: str) -> None:
        origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if origin.rstrip("/") not in self.allowed:
            raise BrowserActionError("not_allowed", f"Navigation to {origin} is outside the allowed company systems.",
                                     f"Allowed origins: {', '.join(self.allowed)}")

    # -- actions
    def goto(self, url: str) -> Observation:
        self.check_url(url)
        return self._run(lambda: self.page.goto(url))

    def click(self, eid: int) -> Observation:
        loc = self._loc(eid)
        href = loc.get_attribute("href")
        if href and href.startswith("http"):
            self.check_url(href)
        return self._run(lambda: loc.click())

    def type_text(self, eid: int, text: str, clear: bool = True, submit: bool = False) -> Observation:
        loc = self._loc(eid)

        def act():
            if clear:
                loc.fill(text)
            else:
                loc.type(text)
            if submit:
                loc.press("Enter")
        return self._run(act)

    def select_option(self, eid: int, option: str) -> Observation:
        loc = self._loc(eid)

        def act():
            try:
                loc.select_option(label=option)
            except PlaywrightError:
                loc.select_option(value=option)
        return self._run(act)

    def press_key(self, key: str) -> Observation:
        return self._run(lambda: self.page.keyboard.press(key))

    def scroll(self, direction: str) -> Observation:
        dy = 700 if direction == "down" else -700
        return self._run(lambda: self.page.mouse.wheel(0, dy))

    def go_back(self) -> Observation:
        return self._run(lambda: self.page.go_back())

    def form_values(self, eid: int) -> dict:
        return self.page.evaluate(FORM_VALUES_JS, int(eid)) or {}

    def new_isolated_page(self, workspace: Path | None = None) -> "Browser":
        """A read-only browser in a fresh context with its own workspace (used by the verifier).

        - Fresh cookies/storage: it re-observes the systems independently of the worker's session.
        - Own workspace (default: <run_dir>/verifier_workspace): it cannot read the worker's downloads,
          so it must re-download source documents itself.
        - Network-level read-only: every request that is not GET/HEAD is aborted before it leaves the
          browser and recorded in `blocked_writes`. This holds no matter which button or script fired it.
        """
        clone = object.__new__(Browser)
        clone.__dict__.update(self.__dict__)
        clone.workspace = workspace or (self.workspace.parent / "verifier_workspace")
        clone.downloads_dir = clone.workspace / "downloads"
        clone.downloads_dir.mkdir(parents=True, exist_ok=True)
        clone.screens_dir = self.screens_dir.parent / "verifier_screens"
        clone.screens_dir.mkdir(parents=True, exist_ok=True)
        clone.blocked_writes = []
        clone._context = self._browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
        clone._context.set_default_timeout(10_000)
        clone._context.route("**/*", clone._read_only_route)
        clone.page = clone._context.new_page()
        clone._net, clone._pending_downloads, clone._dialogs = [], [], []
        clone.page.on("response", clone._on_response)
        clone.page.on("download", lambda d: clone._pending_downloads.append(d))
        clone.page.on("dialog", clone._on_dialog)
        clone._shot_no = 0
        clone.last = None
        return clone

    def _read_only_route(self, route) -> None:
        req = route.request
        if req.method.upper() in ("GET", "HEAD"):
            route.continue_()
            return
        self.blocked_writes.append(f"{req.method.upper()} {urlparse(req.url).path}")
        route.abort()

    def close_isolated(self) -> None:
        """Close only this clone's context (the shared browser process stays up for the worker)."""
        try:
            self._context.close()
        except PlaywrightError:
            pass

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            self._pw.stop()
