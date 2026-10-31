import os
import json
import hmac
import socket
import http.client
import logging
from urllib.parse import urlencode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("LOGIN_BRIDGE_TOKEN", "")
SOCKET_PATH = "/run/openbot/control.sock"
HOST = "0.0.0.0"
PORT = 7860

logging.basicConfig(
    level=logging.INFO,
    format="[login-bridge] %(asctime)s %(levelname)s %(message)s"
)

if len(TOKEN) < 32:
    raise SystemExit("LOGIN_BRIDGE_TOKEN is missing or too short.")

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenBot Login</title>
<style>
*{box-sizing:border-box}
body{
  font:16px system-ui,sans-serif;
  background:#111;color:#eee;
  max-width:440px;margin:40px auto;padding:20px
}
input,button{
  width:100%;padding:13px;margin:8px 0;
  border-radius:8px;border:1px solid #555;
  background:#222;color:white;font:inherit
}
button{
  background:#6750d8;border:0;cursor:pointer;
  font-weight:600
}
button:disabled{opacity:.55;cursor:not-allowed}
#codebox{display:none}
#status{
  white-space:pre-wrap;color:#bbb;
  overflow-wrap:anywhere;margin-top:16px
}
#status.error{color:#ff8585}
#status.success{color:#8ee6a0}
.small{font-size:13px;color:#999}
</style>
</head>
<body>
<h2>OpenBot Server Login</h2>
<p>Sign in to connect this server to your OpenBot account.</p>

<input id="token" type="password" autocomplete="off"
       placeholder="Bridge access token" aria-label="Bridge access token">

<input id="email" type="email" autocomplete="email"
       placeholder="Your OpenBot email" aria-label="Your OpenBot email">

<button id="send" type="button">Send verification code</button>

<div id="codebox">
  <input id="code" autocomplete="one-time-code" inputmode="numeric"
         placeholder="Email verification code" aria-label="Email verification code">
  <button id="verify" type="button">Verify and sign in</button>
</div>

<p id="status" role="status" aria-live="polite"></p>
<p class="small">Your bridge token is sent only to this server.</p>

<script>
(() => {
  "use strict";

  let challenge = "";

  const tokenInput = document.getElementById("token");
  const emailInput = document.getElementById("email");
  const codeInput = document.getElementById("code");
  const sendButton = document.getElementById("send");
  const verifyButton = document.getElementById("verify");
  const codeBox = document.getElementById("codebox");
  const status = document.getElementById("status");

  function showStatus(message, kind = "") {
    status.textContent = message;
    status.className = kind;
  }

  function setBusy(button, busy, busyText, normalText) {
    button.disabled = busy;
    button.textContent = busy ? busyText : normalText;
  }

  async function callBridge(path, data) {
    const token = tokenInput.value.trim();

    if (!token) {
      throw new Error("Enter your bridge access token first.");
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);

    try {
      const response = await fetch(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + token
        },
        body: JSON.stringify(data),
        signal: controller.signal,
        cache: "no-store"
      });

      const text = await response.text();
      let result;

      try {
        result = text ? JSON.parse(text) : {};
      } catch {
        throw new Error(
          "The server returned an invalid response (HTTP " +
          response.status + ")."
        );
      }

      if (!response.ok) {
        const message = result.message || result.error ||
          ("Request failed with HTTP " + response.status);
        throw new Error(message);
      }

      return result;
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error("The request timed out. Check the server logs and try again.");
      }

      if (error instanceof TypeError) {
        throw new Error(
          "Could not reach the login bridge. Check that the server is running."
        );
      }

      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  sendButton.addEventListener("click", async () => {
    showStatus("");

    const email = emailInput.value.trim();

    if (!email) {
      showStatus("Enter your OpenBot email address.", "error");
      emailInput.focus();
      return;
    }

    if (!emailInput.checkValidity()) {
      showStatus("Enter a valid email address.", "error");
      emailInput.focus();
      return;
    }

    setBusy(sendButton, true, "Sending code…", "Send verification code");
    showStatus("Connecting to OpenBot and sending your code…");

    try {
      const result = await callBridge("/start", { email });

      challenge = result.challenge || result.challenge_id || "";

      if (!challenge) {
        console.error("Login bridge /start response did not contain a challenge.");
        throw new Error(
          "OpenBot did not return a verification challenge. Check the server logs."
        );
      }

      codeBox.style.display = "block";
      showStatus("Verification code sent. Check your email.", "success");
      codeInput.focus();
    } catch (error) {
      console.error("Login start failed:", error.message);
      showStatus(error.message || "Could not send the verification code.", "error");
    } finally {
      setBusy(sendButton, false, "Sending code…", "Send verification code");
    }
  });

  verifyButton.addEventListener("click", async () => {
    showStatus("");

    const code = codeInput.value.trim();

    if (!challenge) {
      showStatus("Send a verification code first.", "error");
      return;
    }

    if (!code) {
      showStatus("Enter the verification code from your email.", "error");
      codeInput.focus();
      return;
    }

    setBusy(verifyButton, true, "Verifying…", "Verify and sign in");
    showStatus("Verifying your code…");

    try {
      const result = await callBridge("/verify", {
        challenge,
        code
      });

      showStatus(
        result.message || "Signed in successfully. Open https://openbot.run/app using this account.",
        "success"
      );
    } catch (error) {
      console.error("Login verification failed:", error.message);
      showStatus(error.message || "Verification failed.", "error");
    } finally {
      setBusy(verifyButton, false, "Verifying…", "Verify and sign in");
    }
  });

  // Make it obvious the page JavaScript actually loaded.
  showStatus("Login page ready.");
})();
</script>
</body>
</html>
"""


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET_PATH)


class Handler(BaseHTTPRequestHandler):
    server_version = "OpenBotLoginBridge/1.1"

    def log_message(self, format_string, *args):
        # Do not log headers, request bodies, email addresses, or tokens.
        logging.info("%s %s", self.command, self.path)

    def reply(self, status, data, content_type="application/json", head=False):
        body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; "
            "style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        self.end_headers()

        if not head:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self.reply(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/health":
            self.reply(200, {"status": "ok"})
        else:
            self.reply(404, {"error": "not_found"})

    def do_HEAD(self):
        if self.path == "/":
            self.reply(
                200,
                PAGE.encode("utf-8"),
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
            logging.warning("Rejected unauthorized request to %s", self.path)
            return self.reply(401, {"error": "Invalid bridge access token."})

        try:
            size = int(self.headers.get("Content-Length", "0"))

            if size < 1 or size > 4096:
                return self.reply(400, {"error": "invalid_request"})

            data = json.loads(self.rfile.read(size))

            if not isinstance(data, dict):
                return self.reply(400, {"error": "invalid_request"})

            if self.path == "/start":
                email = str(data.get("email", "")).strip()

                if not email or len(email) > 254 or "@" not in email:
                    return self.reply(400, {"error": "Enter a valid email address."})

                route = "/v1/login/start"
                fields = {"email": email}

            else:
                challenge = str(data.get("challenge", "")).strip()
                code = str(data.get("code", "")).strip()

                if not challenge or not code:
                    return self.reply(400, {"error": "Enter the verification code."})

                route = "/v1/login/verify"
                fields = {
                    "challenge": challenge,
                    "code": code
                }

            logging.info("Forwarding authenticated request to OpenBot: %s", route)

            conn = UnixConnection("localhost", timeout=20)

            try:
                conn.request(
                    "POST",
                    route,
                    body=urlencode(fields),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "text/plain"
                    }
                )

                response = conn.getresponse()
                status = response.status
                raw = response.read().decode("utf-8", "replace")
            finally:
                conn.close()

            result = {}

            # OpenBot's control socket currently returns key=value lines.
            for line in raw.splitlines():
                key, separator, value = line.partition("=")
                if separator:
                    result[key.strip()] = value.strip()

            logging.info("OpenBot login endpoint returned HTTP %s", status)

            if status < 200 or status >= 300:
                message = (
                    result.get("message")
                    or result.get("error")
                    or "OpenBot rejected the login request."
                )
                return self.reply(status, {"error": message})

            if self.path == "/start":
                challenge_value = (
                    result.get("challenge")
                    or result.get("challenge_id")
                )

                if challenge_value:
                    result["challenge"] = challenge_value

            if self.path == "/verify":
                result["message"] = (
                    "Signed in successfully. "
                    "Open https://openbot.run/app using this account."
                )

            self.reply(status, result)

        except (ValueError, OSError, socket.timeout, socket.error) as error:
            logging.error(
                "OpenBot login service connection failed: %s",
                type(error).__name__
            )
            self.reply(
                503,
                {"error": "OpenBot login service is not ready. Check server logs."}
            )

        except Exception as error:
            logging.error(
                "Unexpected login bridge error: %s",
                type(error).__name__
            )
            self.reply(500, {"error": "Login bridge error. Check server logs."})


if __name__ == "__main__":
    logging.info("Starting login bridge on %s:%s", HOST, PORT)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
