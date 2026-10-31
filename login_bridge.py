import os
import json
import hmac
import socket
import http.client
from urllib.parse import urlencode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("LOGIN_BRIDGE_TOKEN", "")
SOCKET_PATH = "/run/openbot/control.sock"

if len(TOKEN) < 32:
    raise SystemExit("LOGIN_BRIDGE_TOKEN is missing or too short.")

PAGE = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenBot Login</title>
<style>
body{font:16px system-ui;background:#111;color:#eee;max-width:440px;
margin:60px auto;padding:20px}
input,button{box-sizing:border-box;width:100%;padding:13px;margin:8px 0;
border-radius:8px;border:1px solid #555;background:#222;color:white}
button{background:#6750d8;border:0;cursor:pointer}
#codebox{display:none}
#status{white-space:pre-wrap;color:#aaa}
</style>
</head>
<body>
<h2>OpenBot Server Login</h2>
<p>Sign in to connect this server to your OpenBot account.</p>
<input id="token" type="password" placeholder="Bridge access token">
<input id="email" type="email" placeholder="Your OpenBot email">
<button id="send">Send verification code</button>
<div id="codebox">
<input id="code" autocomplete="one-time-code" placeholder="Email verification code">
<button id="verify">Verify and sign in</button>
</div>
<p id="status"></p>
<script>
let challenge = "";
const status = document.getElementById("status");

async function call(path, data) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer " + document.getElementById("token").value
    },
    body: JSON.stringify(data)
  });

  const result = await response.json();

  if (!response.ok) {
    throw new Error(result.message || result.error || "Request failed");
  }

  return result;
}

document.getElementById("send").onclick = async () => {
  status.textContent = "Sending code...";

  try {
    const result = await call("/start", {
      email: document.getElementById("email").value
    });

    challenge = result.challenge;
    document.getElementById("codebox").style.display = "block";
    status.textContent = "Verification code sent. Check your email.";
  } catch (e) {
    status.textContent = e.message;
  }
};

document.getElementById("verify").onclick = async () => {
  status.textContent = "Verifying...";

  try {
    const result = await call("/verify", {
      challenge,
      code: document.getElementById("code").value
    });

    status.textContent = result.message || "Signed in! Check your OpenBot account.";
  } catch (e) {
    status.textContent = e.message;
  }
};
</script>
</body>
</html>"""


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(SOCKET_PATH)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data, content_type="application/json", head=False):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        self.end_headers()

        if not head:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self.reply(200, PAGE.encode(), "text/html; charset=utf-8")
        elif self.path == "/health":
            self.reply(200, {"status": "ok"})
        else:
            self.reply(404, {"error": "not_found"})

    def do_HEAD(self):
        if self.path == "/":
            self.reply(
                200,
                PAGE.encode(),
                "text/html; charset=utf-8",
                head=True
            )
        elif self.path == "/health":
            self.reply(200, {"status": "ok"}, head=True)
        else:
            self.reply(404, {"error": "not_found"}, head=True)

    def do_POST(self):
        if self.path not in ("/start", "/verify"):
            return self.reply(404, {"error": "not_found"})

        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + TOKEN

        if not hmac.compare_digest(supplied, expected):
            return self.reply(401, {"error": "unauthorized"})

        try:
            size = int(self.headers.get("Content-Length", "0"))

            if size < 1 or size > 4096:
                return self.reply(400, {"error": "invalid_request"})

            data = json.loads(self.rfile.read(size))

            if self.path == "/start":
                email = str(data.get("email", "")).strip()

                if not email or len(email) > 254:
                    return self.reply(400, {"error": "invalid_email"})

                route = "/v1/login/start"
                fields = {"email": email}

            else:
                challenge = str(data.get("challenge", ""))
                code = str(data.get("code", "")).strip()

                if not challenge or not code:
                    return self.reply(400, {"error": "invalid_request"})

                route = "/v1/login/verify"
                fields = {
                    "challenge": challenge,
                    "code": code
                }

            conn = UnixConnection("localhost", timeout=20)

            conn.request(
                "POST",
                route,
                body=urlencode(fields),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded"
                }
            )

            response = conn.getresponse()
            status = response.status
            raw = response.read().decode("utf-8", "replace")
            conn.close()

            result = {}

            for line in raw.splitlines():
                key, sep, value = line.partition("=")

                if sep:
                    result[key] = value

            if status == 200 and self.path == "/verify":
                result["message"] = (
                    "Signed in successfully. "
                    "Open https://openbot.run/app using this account."
                )

            self.reply(status, result)

        except (ValueError, OSError, socket.error):
            self.reply(
                503,
                {"error": "OpenBot login service is not ready."}
            )

        except Exception:
            self.reply(500, {"error": "Login bridge error."})


ThreadingHTTPServer(("0.0.0.0", 7860), Handler).serve_forever()
