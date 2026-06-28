from __future__ import annotations

import argparse
import asyncio
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from local_lab.harness import LocalSentinelHarness


HARNESS = LocalSentinelHarness()


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SENTINEL Local Lab</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #182026;
      --muted: #66727f;
      --line: #d8dde3;
      --accent: #147c72;
      --accent-2: #b35c00;
      --good: #236b31;
      --bad: #a83232;
      --shadow: 0 12px 34px rgba(24, 32, 38, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }
    .app {
      display: grid;
      grid-template-columns: minmax(320px, 1fr) 360px;
      height: 100vh;
      min-height: 620px;
    }
    .chat {
      display: grid;
      grid-template-rows: 64px 1fr auto;
      min-width: 0;
      border-right: 1px solid var(--line);
      background:
        linear-gradient(rgba(20, 124, 114, .05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(179, 92, 0, .04) 1px, transparent 1px),
        #eef4f3;
      background-size: 28px 28px;
    }
    .topbar, .sidehead {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 18px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.9);
      backdrop-filter: blur(10px);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }
    .mark {
      width: 36px;
      height: 36px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      color: white;
      background: var(--accent);
      font-weight: 800;
    }
    .title {
      display: grid;
      gap: 1px;
      min-width: 0;
    }
    .title strong {
      font-size: 15px;
      line-height: 1.2;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .title span {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .statusdot {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      color: var(--good);
      font-size: 12px;
      font-weight: 700;
      flex: 0 0 auto;
    }
    .statusdot::before {
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--good);
    }
    #messages {
      overflow: auto;
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .bubble {
      width: fit-content;
      max-width: min(760px, 84%);
      padding: 10px 12px;
      border-radius: 8px;
      line-height: 1.42;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      box-shadow: 0 2px 10px rgba(24, 32, 38, .06);
      font-size: 14px;
    }
    .bubble.user {
      align-self: flex-end;
      background: #d9f0ea;
      border: 1px solid #b8ded5;
    }
    .bubble.bot {
      align-self: flex-start;
      background: var(--panel);
      border: 1px solid var(--line);
    }
    .composer {
      padding: 12px;
      background: rgba(255,255,255,.94);
      border-top: 1px solid var(--line);
      display: grid;
      gap: 10px;
    }
    .quick {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 8px;
      min-height: 34px;
      padding: 0 11px;
      font-weight: 700;
      cursor: pointer;
    }
    button:hover { border-color: var(--accent); }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      min-width: 48px;
    }
    .inputrow {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: end;
    }
    textarea {
      width: 100%;
      min-height: 44px;
      max-height: 150px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 11px 12px;
      font: inherit;
      background: #fff;
      color: var(--ink);
      outline: none;
    }
    textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(20, 124, 114, .16); }
    .side {
      display: grid;
      grid-template-rows: 64px 1fr;
      min-width: 0;
      background: #fbfbfc;
    }
    .sidebody {
      overflow: auto;
      padding: 14px;
      display: grid;
      gap: 12px;
      align-content: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel h2 {
      margin: 0;
      padding: 11px 12px;
      font-size: 13px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }
    .rows { display: grid; }
    .row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      padding: 9px 12px;
      border-top: 1px solid #edf0f2;
      font-size: 13px;
    }
    .row:first-child { border-top: 0; }
    .row span:first-child {
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .row strong { color: var(--ink); }
    .log {
      max-height: 330px;
      overflow: auto;
      padding: 8px 0;
    }
    .logitem {
      padding: 8px 12px;
      border-top: 1px solid #edf0f2;
      font-size: 12px;
      display: grid;
      gap: 3px;
    }
    .logitem:first-child { border-top: 0; }
    .logitem code {
      color: var(--accent-2);
      font-weight: 800;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .logitem span {
      color: var(--muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    @media (max-width: 900px) {
      .app {
        grid-template-columns: 1fr;
        grid-template-rows: minmax(520px, 68vh) auto;
        height: auto;
        min-height: 100vh;
      }
      .chat { min-height: 68vh; border-right: 0; border-bottom: 1px solid var(--line); }
      .side { min-height: 420px; }
    }
  </style>
</head>
<body>
  <main class="app">
    <section class="chat">
      <header class="topbar">
        <div class="brand">
          <div class="mark">S</div>
          <div class="title">
            <strong>SENTINEL Local Lab</strong>
            <span>Telegram-style offline harness</span>
          </div>
        </div>
        <div class="statusdot">LOCAL</div>
      </header>
      <div id="messages"></div>
      <form id="form" class="composer">
        <div class="quick">
          <button type="button" data-msg="/start">Start</button>
          <button type="button" data-msg="/plan">Plan</button>
          <button type="button" data-msg="/homework Physics Ch.5 Ex2A Q1-20">Homework</button>
          <button type="button" data-msg="/done attempted 12 correct 8, Q7 circular motion doubt">Done</button>
          <button type="button" data-msg="/doubts">Doubts</button>
          <button type="button" data-msg="/night">Night</button>
          <button type="button" data-msg="/simulate 30">Sim 30</button>
        </div>
        <div class="inputrow">
          <textarea id="text" placeholder="Message SENTINEL locally"></textarea>
          <button class="primary" type="submit">Send</button>
        </div>
      </form>
    </section>
    <aside class="side">
      <header class="sidehead">
        <div class="title">
          <strong>Runtime</strong>
          <span id="runtime">loading</span>
        </div>
        <button type="button" id="reset">Reset</button>
      </header>
      <div class="sidebody">
        <section class="panel">
          <h2>Fake Databases</h2>
          <div id="dbrows" class="rows"></div>
        </section>
        <section class="panel">
          <h2>Recent Audit</h2>
          <div id="audit" class="log"></div>
        </section>
      </div>
    </aside>
  </main>
  <script>
    const messages = document.getElementById('messages');
    const form = document.getElementById('form');
    const text = document.getElementById('text');
    const dbrows = document.getElementById('dbrows');
    const audit = document.getElementById('audit');
    const runtime = document.getElementById('runtime');

    function addBubble(kind, value) {
      const div = document.createElement('div');
      div.className = `bubble ${kind}`;
      div.textContent = value;
      messages.appendChild(div);
      messages.scrollTop = messages.scrollHeight;
    }

    function renderState(state) {
      runtime.textContent = state.runtime_dir || 'local';
      const schemas = state.schemas || {};
      const counts = state.fake_db_counts || {};
      dbrows.innerHTML = Object.keys(schemas).map((key) => {
        const item = schemas[key];
        return `<div class="row"><span>${key.toUpperCase()} · ${item.title}</span><strong>${counts[key] || 0}</strong></div>`;
      }).join('');
      const events = (state.audit_tail || []).slice(-14).reverse();
      audit.innerHTML = events.map((event) => {
        return `<div class="logitem"><code>${event.event_type}</code><span>${event.timestamp}</span></div>`;
      }).join('');
    }

    async function refresh() {
      const res = await fetch('/api/state');
      renderState(await res.json());
    }

    async function sendMessage(value) {
      const trimmed = value.trim();
      if (!trimmed) return;
      addBubble('user', trimmed);
      text.value = '';
      const res = await fetch('/api/message', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: trimmed})
      });
      const payload = await res.json();
      (payload.replies || []).forEach((reply) => addBubble('bot', reply));
      renderState(payload.state || {});
    }

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      sendMessage(text.value);
    });

    document.querySelectorAll('[data-msg]').forEach((button) => {
      button.addEventListener('click', () => sendMessage(button.dataset.msg));
    });

    document.getElementById('reset').addEventListener('click', async () => {
      await fetch('/api/reset', {method: 'POST'});
      messages.innerHTML = '';
      addBubble('bot', 'Local runtime reset.');
      refresh();
    });

    text.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage(text.value);
      }
    });

    addBubble('bot', 'Local lab is ready. Try /start, /plan, /done, /doubts, /night, or /simulate 30.');
    refresh();
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "SentinelLocalLab/1.0"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send(HTTPStatus.OK, HTML, "text/html; charset=utf-8")
        elif path == "/api/state":
            self._send_json(HARNESS.state_snapshot())
        elif path == "/api/fake-db":
            self._send_json(HARNESS.export_fake_notion())
        elif path == "/api/audit":
            self._send_json(HARNESS.audit.tail(200))
        else:
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/message":
            payload = self._read_json()
            message = str(payload.get("message", ""))
            result = asyncio.run(HARNESS.handle_message(message))
            self._send_json(result)
        elif path == "/api/reset":
            HARNESS.reset()
            asyncio.run(HARNESS.init())
            self._send_json({"ok": True, "state": HARNESS.state_snapshot()})
        else:
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[local-lab] {self.address_string()} {fmt % args}")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _send(self, status: HTTPStatus, body: str | bytes, content_type: str) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SENTINEL local Telegram-style lab.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    asyncio.run(HARNESS.init())
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"SENTINEL local lab running at http://{args.host}:{args.port}")
    print("Real Notion/MongoDB/Telegram/live AI providers are disabled in this server.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

