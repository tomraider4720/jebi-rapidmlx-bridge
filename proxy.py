#!/usr/bin/env python3
"""
jebi-rapidmlx-bridge
=====================

Tiny reverse proxy that makes a local Rapid-MLX server
(https://github.com/raullenchai/Rapid-MLX, OpenAI/Anthropic-compatible)
look like an Ollama server to jebi (https://github.com/jebi-sh/jebi).

Why this exists
----------------
jebi only ships two LLM providers: "ollama" and "llama-server". The
"ollama" provider calls GET /api/tags to check availability and list
models before it will send any chat request. Rapid-MLX is fully
OpenAI-compatible (/v1/chat/completions, /v1/models, ...) but does not
implement Ollama's native /api/tags endpoint, so jebi's ollama provider
never gets past its own availability check.

This proxy sits between the two:

  jebi (provider=ollama, endpointURL=http://127.0.0.1:11434)
    -> this proxy (127.0.0.1:11434)
         - GET /api/tags        -> synthesized from Rapid-MLX GET /v1/models
         - everything else      -> transparently forwarded to Rapid-MLX,
                                    streaming responses (SSE) included
    -> Rapid-MLX (127.0.0.1:8000)

No external dependencies. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 11434  # jebi's default ollama endpointURL port
DEFAULT_BACKEND = "http://127.0.0.1:8000"  # rapid-mlx serve default

logger = logging.getLogger("jebi-rapidmlx-bridge")

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",  # recomputed by the HTTP layer when relevant
}


def ollama_tags_payload(models_json: dict) -> dict:
    """Translate a Rapid-MLX GET /v1/models response into Ollama's
    GET /api/tags shape.

    Ollama's real /api/tags returns a "models" list of objects with at
    least a "name" and "model" field. jebi's provider only reads the
    "name"/"model" field to match against the configured model, so we
    keep this minimal but valid.
    """
    data = models_json.get("data") or []
    out = []
    for entry in data:
        model_id = entry.get("id") or entry.get("slug")
        if not model_id:
            continue
        out.append(
            {
                "name": model_id,
                "model": model_id,
                "modified_at": "",
                "size": 0,
                "digest": "",
                "details": {
                    "format": "mlx",
                    "family": "rapid-mlx",
                    "parameter_size": "",
                    "quantization_level": "",
                },
            }
        )
    return {"models": out}


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "jebi-rapidmlx-bridge/1.0"
    backend: str = DEFAULT_BACKEND
    request_timeout: float = 30.0

    def log_message(self, format, *args):  # noqa: A002 - stdlib override
        logger.info("%s - %s", self.address_string(), format % args)

    def do_GET(self):  # noqa: N802 - stdlib override
        if self.path.rstrip("/") == "/api/tags":
            self._handle_api_tags()
            return
        self._proxy()

    def do_POST(self):  # noqa: N802
        self._proxy()

    def do_PUT(self):  # noqa: N802
        self._proxy()

    def do_DELETE(self):  # noqa: N802
        self._proxy()

    def do_HEAD(self):  # noqa: N802
        self._proxy()

    # -- handlers ---------------------------------------------------

    def _handle_api_tags(self):
        try:
            with urllib.request.urlopen(
                f"{self.backend}/v1/models", timeout=self.request_timeout
            ) as resp:
                models_json = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.error("backend /v1/models failed: %s", exc)
            self._send_json(
                502,
                {"error": f"rapid-mlx backend unreachable at {self.backend}: {exc}"},
            )
            return

        payload = ollama_tags_payload(models_json)
        self._send_json(200, payload)

    def _proxy(self):
        """Transparently forward the request to the Rapid-MLX backend,
        streaming the response body back (needed for SSE chat streams)."""
        target_url = self.backend + self.path
        body = None
        content_length = self.headers.get("Content-Length")
        if content_length:
            body = self.rfile.read(int(content_length))

        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS and k.lower() != "host"
        }

        req = urllib.request.Request(
            target_url, data=body, headers=headers, method=self.command
        )

        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                self._stream_response(resp)
        except urllib.error.HTTPError as exc:
            resp_body = exc.read()
            self.send_response(exc.code)
            for k, v in exc.headers.items():
                if k.lower() not in HOP_BY_HOP_HEADERS:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.error("backend request failed: %s", exc)
            self._send_json(
                502, {"error": f"rapid-mlx backend unreachable at {self.backend}: {exc}"}
            )

    def _stream_response(self, resp):
        self.send_response(resp.status)
        for k, v in resp.headers.items():
            if k.lower() not in HOP_BY_HOP_HEADERS:
                self.send_header(k, v)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
            self.wfile.write(chunk)
            self.wfile.write(b"\r\n")
            try:
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        self.wfile.write(b"0\r\n\r\n")

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_handler(backend: str, timeout: float):
    class _Handler(BridgeHandler):
        pass

    _Handler.backend = backend.rstrip("/")
    _Handler.request_timeout = timeout
    return _Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--listen-host",
        default=os.environ.get("BRIDGE_LISTEN_HOST", DEFAULT_LISTEN_HOST),
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=int(os.environ.get("BRIDGE_LISTEN_PORT", DEFAULT_LISTEN_PORT)),
    )
    parser.add_argument(
        "--backend",
        default=os.environ.get("BRIDGE_BACKEND", DEFAULT_BACKEND),
        help="Rapid-MLX server base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("BRIDGE_TIMEOUT", "30")),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parsed_backend = urlsplit(args.backend)
    if parsed_backend.hostname not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "backend host %s is not localhost — this bridge is meant for local use only",
            parsed_backend.hostname,
        )

    handler_cls = make_handler(args.backend, args.timeout)
    httpd = ThreadingHTTPServer((args.listen_host, args.listen_port), handler_cls)
    print(
        f"jebi-rapidmlx-bridge listening on http://{args.listen_host}:{args.listen_port}"
        f" -> forwarding to {args.backend}",
        file=sys.stderr,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
