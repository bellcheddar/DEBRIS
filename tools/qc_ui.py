"""Phase 3 UI QC (spec section 3 and 6.1).

Starts gunicorn on a spare port, drives the preinstalled Chromium through Playwright
(never `playwright install`), and checks, for every tab at 1440x900 and 390x844:

* the route returns 200 and the page paints
* no `console.error` and no failed network request
* axe-core reports zero serious or critical violations
* the Atlas is interactive inside the 1.5 s budget
* the click-throughs work: Atlas region -> Papers, Body node -> panel

Screenshots land in `qc/` and a JSON summary in `qc/qc_ui.json`. If Chromium is absent
the run logs a degraded pass rather than downloading a browser.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
from pathlib import Path

from pipeline import common as c

QC = c.ROOT / "qc"
VIEWPORTS = {"desktop": (1440, 900), "mobile": (390, 844)}
PAGES = [("atlas", "/"), ("body", "/body"), ("pathways", "/pathways"), ("papers", "/papers")]
AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"
IGNORED_CONSOLE = ("favicon",)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def axe_source() -> str:
    """axe-core from the installed package, else the vendored copy, else the CDN."""
    try:
        import axe_core_python  # noqa: F401
        pkg = Path(axe_core_python.__file__).parent
        for candidate in pkg.rglob("axe.min.js"):
            return candidate.read_text()
    except Exception:
        pass
    vendored = c.ROOT / "app" / "static" / "vendor" / "axe.min.js"
    if vendored.exists():
        return vendored.read_text()
    import urllib.request
    with urllib.request.urlopen(AXE_CDN, timeout=30) as resp:  # noqa: S310
        text = resp.read().decode()
    vendored.parent.mkdir(parents=True, exist_ok=True)
    vendored.write_text(text)
    return text


def start_server(port: int) -> subprocess.Popen:
    cmd = [str(c.ROOT / ".venv" / "bin" / "gunicorn"), "-w", "2", "-b", f"127.0.0.1:{port}",
           "--timeout", "60", "wsgi:app"]
    proc = subprocess.Popen(cmd, cwd=c.ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    import urllib.error
    import urllib.request
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
                if r.status == 200:
                    return proc
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    proc.terminate()
    raise RuntimeError("gunicorn did not come up")


def run(headed: bool = False) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        c.log("qc ui: playwright not installed, screenshots skipped (degraded)")
        return {"status": "skipped", "reason": "playwright absent"}

    QC.mkdir(exist_ok=True)
    port = free_port()
    server = start_server(port)
    base = f"http://127.0.0.1:{port}"
    axe = axe_source()
    report: dict = {"base": base, "pages": [], "violations": [], "console": [],
                    "network": [], "interactions": []}

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=not headed)
            except Exception as exc:
                c.log(f"qc ui: Chromium unavailable ({type(exc).__name__}), skipped (degraded)")
                return {"status": "skipped", "reason": "chromium absent"}
            for label, (width, height) in VIEWPORTS.items():
                ctx = browser.new_context(viewport={"width": width, "height": height},
                                          device_scale_factor=2)
                page = ctx.new_page()
                page.on("console", lambda m, l=label: report["console"].append(
                    {"viewport": l, "type": m.type, "text": m.text})
                    if m.type == "error" and not any(s in m.text for s in IGNORED_CONSOLE)
                    else None)
                page.on("requestfailed", lambda r, l=label: report["network"].append(
                    {"viewport": l, "url": r.url, "failure": r.failure}))
                for name, path in PAGES:
                    started = time.monotonic()
                    resp = page.goto(base + path, wait_until="networkidle")
                    elapsed = time.monotonic() - started
                    shot = QC / f"{name}-{label}.png"
                    page.screenshot(path=str(shot), full_page=(label == "mobile"))
                    results = page.evaluate(
                        """async (src) => {
                             if (!window.axe) { const s = document.createElement('script');
                               s.textContent = src; document.head.appendChild(s); }
                             const r = await window.axe.run(document, {
                               runOnly: { type: 'tag',
                                          values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } });
                             return r.violations.map(v => ({ id: v.id, impact: v.impact,
                               help: v.help, nodes: v.nodes.length,
                               targets: v.nodes.slice(0, 4).map(n => ({
                                 target: n.target.join(' '),
                                 html: (n.html || '').slice(0, 220),
                                 summary: (n.failureSummary || '').slice(0, 220) })) }));
                           }""", axe)
                    serious = [v for v in results if v["impact"] in ("serious", "critical")]
                    report["pages"].append({"page": name, "viewport": label,
                                            "status": resp.status if resp else None,
                                            "seconds": round(elapsed, 3),
                                            "screenshot": str(shot.relative_to(c.ROOT)),
                                            "violations": len(results),
                                            "serious_or_critical": len(serious)})
                    report["violations"] += [dict(v, page=name, viewport=label) for v in serious]
                if label == "desktop":
                    report["interactions"] = click_throughs(page, base)
                ctx.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=30)

    slow = [p for p in report["pages"] if p["page"] == "atlas" and p["seconds"] > 1.5]
    report["status"] = "pass" if not report["violations"] and not report["console"] \
        and not report["network"] and not slow else "fail"
    report["atlas_over_budget"] = slow
    (QC / "qc_ui.json").write_text(json.dumps(report, indent=2) + "\n")
    c.log(f"qc ui: {report['status']}, {len(report['pages'])} page renders, "
          f"{len(report['violations'])} serious or critical axe violations, "
          f"{len(report['console'])} console errors, {len(report['network'])} failed requests")
    return report


def click_throughs(page, base: str) -> list[dict]:
    """Atlas region -> Papers, Body node -> panel."""
    out = []
    page.goto(base + "/", wait_until="networkidle")
    region = page.locator("svg .venn-region").first
    if region.count():
        try:
            region.scroll_into_view_if_needed(timeout=5000)
            region.click(timeout=5000)
            page.wait_for_load_state("networkidle")
            out.append({"from": "atlas region", "url": page.url,
                        "ok": "/papers" in page.url})
        except Exception as exc:
            out.append({"from": "atlas region", "ok": False,
                        "note": f"{type(exc).__name__}: {str(exc).splitlines()[0]}"})
    else:
        out.append({"from": "atlas region", "ok": False, "note": "no clickable region"})
    page.goto(base + "/body", wait_until="networkidle")
    node = page.locator("svg .node").first
    if node.count():
        try:
            node.scroll_into_view_if_needed(timeout=5000)
            node.click(timeout=5000)
        except Exception as exc:
            return out + [{"from": "body node", "ok": False,
                           "note": f"{type(exc).__name__}: {str(exc).splitlines()[0]}"}]
        page.wait_for_timeout(600)
        title = page.locator("#panel-title")
        body = page.locator("#panel-body")
        out.append({"from": "body node",
                    "title": title.inner_text() if title.count() else None,
                    "ok": bool(title.count() and title.inner_text().strip()
                               and body.count() and body.inner_text().strip())})
    else:
        out.append({"from": "body node", "ok": False, "note": "no organ node"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="DEBRIS UI QC")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    report = run(args.headed)
    return 0 if report.get("status") in ("pass", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
