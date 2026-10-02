"""Use the app in headless Chrome like a visitor and an owner would, and save
screenshots for the submission page. Also works as an end-to-end UI check.

    python scripts/capture_screenshots.py https://your-site.cloudfront.net [site-to-learn]

Needs Google Chrome and `pip install websocket-client`. Writes docs/screenshots/.
"""
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"
LEARN = sys.argv[2] if len(sys.argv) > 2 else "basecamp.com"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

profile = tempfile.mkdtemp()
proc = subprocess.Popen(
    [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=9334",
     "--remote-allow-origins=*", "--window-size=1360,900", f"--user-data-dir={profile}", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
errors, seq = [], [0]


def main():
    for _ in range(60):
        try:
            tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9334/json"))
            break
        except OSError:
            time.sleep(0.25)
    ws = websocket.create_connection(next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"])

    def cmd(method, **params):
        seq[0] += 1
        ws.send(json.dumps({"id": seq[0], "method": method, "params": params}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                errors.append(msg["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:300])
            if msg.get("id") == seq[0]:
                return msg.get("result", {})

    def js(expr):
        result = cmd("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"].get("exception", {}).get("description"))
        return result["result"].get("value")

    def wait(expr, seconds=30):
        end = time.time() + seconds
        while time.time() < end:
            if js(expr):
                return
            time.sleep(0.3)
        raise TimeoutError(expr)

    def shot(name, full=False):
        params = {"format": "png"}
        if full:
            height = js("document.documentElement.scrollHeight")
            params["clip"] = {"x": 0, "y": 0, "width": 1360, "height": height, "scale": 1}
            params["captureBeyondViewport"] = True
        (OUT / f"{name}.png").write_bytes(base64.b64decode(cmd("Page.captureScreenshot", **params)["data"]))
        print("saved", name)

    def go(url):
        cmd("Page.navigate", url=url)
        wait("document.readyState === 'complete'")

    cmd("Runtime.enable")
    cmd("Page.enable")
    widget = "document.querySelector('[id^=greetwell-]').shadowRoot"

    # Landing page, with the live demo assistant answering a question about Greetwell.
    go(BASE + "/")
    wait("!!document.querySelector('[id^=greetwell-]')")
    shot("1-landing")
    shot("1-landing-full", full=True)
    js(f"{widget}.querySelector('.launcher').click(); true")
    js(f"(() => {{ const r = {widget}; r.querySelector('textarea').value = 'What does Greetwell do, and what does it cost?'; r.querySelector('form').requestSubmit(); return true; }})()")
    wait(f"{widget}.querySelectorAll('.msg.bot').length >= 2 && !{widget}.querySelector('.typing')", 60)
    shot("2-demo-assistant")

    # Build an assistant from a real website.
    js(f"{widget}.querySelector('.close').click(); true")
    js(f"document.getElementById('url').value = {json.dumps(LEARN)}; document.getElementById('build-form').requestSubmit(); true")
    wait("location.pathname === '/dashboard.html'")
    wait("!!document.querySelector('.steps li.now')", 15)
    shot("3-building")
    wait("!!document.querySelector('.tabs')", 180)
    dashboard = js("location.href")
    bot = js("location.hash.slice(1).split('.')[0]")
    shot("4-dashboard-overview")

    # Talk to it like a customer on the preview page.
    go(f"{BASE}/preview.html?bot={bot}")
    wait("!!document.querySelector('[id^=greetwell-]')")
    wait(f"{widget}.querySelector('.root').classList.contains('open')")
    for text in ("How much does it cost for a team of 25?",
                 "We'd like to switch next month. I'm Sam from Northwind, sam@northwind.example"):
        count = js(f"{widget}.querySelectorAll('.msg.bot').length")
        js(f"(() => {{ const r = {widget}; r.querySelector('textarea').value = {json.dumps(text)}; r.querySelector('form').requestSubmit(); return true; }})()")
        wait(f"{widget}.querySelectorAll('.msg.bot').length > {count} && !{widget}.querySelector('.typing')", 60)
    shot("5-preview-conversation")

    # The owner's view of that lead.
    go(dashboard.replace("dashboard.html", "dashboard.html?tab=leads"))
    wait("!!document.querySelector('tbody tr')", 20)
    shot("6-leads")
    js("document.querySelector('tbody tr td').click(); true")
    wait("document.querySelectorAll('.drawer .transcript .b').length >= 2", 20)
    shot("7-lead-detail")
    go(dashboard.replace("dashboard.html", "dashboard.html?tab=knowledge"))
    wait("!!document.querySelector('.list li')", 20)
    shot("8-knowledge")
    print("dashboard:", dashboard)
    print("JavaScript errors:", errors or "none")


try:
    main()
finally:
    proc.terminate()
    time.sleep(0.5)
    shutil.rmtree(profile, ignore_errors=True)
