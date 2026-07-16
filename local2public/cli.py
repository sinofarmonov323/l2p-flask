from argparse import ArgumentParser
import base64
import os
import re
from urllib.parse import urlparse, urlunparse

import httpx
import socketio

SERVER_URL = os.getenv("LTP_SERVER_URL", "http://localhost:8000")
PUBLIC_BASE_URL = os.getenv("LTP_PUBLIC_BASE_URL")
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def parse_args():
    parser = ArgumentParser(description="ltp - local to public")
    parser.add_argument("-p", "--port", type=int, required=True, help="Local port to expose")
    parser.add_argument("-n", "--name", type=str, required=True, help="Public tunnel name")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    return parser.parse_args()


def normalize_tunnel_name(name: str) -> str:
    normalized = name.strip().lower()
    if not NAME_RE.fullmatch(normalized):
        raise ValueError(
            "name must be a valid DNS label: lowercase letters, numbers, and hyphens only"
        )
    return normalized


def filtered_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def public_url_for_name(name: str) -> str:
    base_url = PUBLIC_BASE_URL
    if not base_url:
        parsed_server = urlparse(SERVER_URL)
        scheme = "https" if parsed_server.scheme == "wss" else "http"
        base_url = urlunparse((scheme, parsed_server.netloc, "", "", "", ""))

    parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}")
    netloc = f"{name}.{parsed.netloc}"
    return urlunparse((parsed.scheme, netloc, "/", "", "", ""))


def tunnel(local_port: int, name: str, verbose: bool):
    name = normalize_tunnel_name(name)

    sio = socketio.Client()
    
    @sio.event
    def registered(data):
        print(f"Tunnel open: {public_url_for_name(data['name'])}")
        print("Ctrl+C to stop")
    
    @sio.event
    def error(data):
        print(f"Error: {data['error']}")
    
    @sio.on("request")
    def handle_request(data):
        if verbose:
            print(f"-> {data['method']} {data['path']}")

        try:
            path = data["path"]
            if data.get("query_string"):
                path = f"{path}?{data['query_string']}"

            body = data.get("body", "")
            if data.get("body_encoding") == "base64":
                content = base64.b64decode(body)
            else:
                content = body.encode("utf-8") if isinstance(body, str) else body

            resp = httpx.request(
                method=data["method"],
                url=f"http://localhost:{local_port}{path}",
                headers=filtered_headers(data.get("headers", {})),
                content=content,
            )
            sio.emit("response", {
                "request_id": data["request_id"],
                "status": resp.status_code,
                "headers": filtered_headers(dict(resp.headers)),
                "body": base64.b64encode(resp.content).decode("ascii"),
                "body_encoding": "base64",
            })
        except Exception as e:
            sio.emit("response", {
                "request_id": data["request_id"],
                "status": 502,
                "headers": {"content-type": "text/plain; charset=utf-8"},
                "body": base64.b64encode(str(e).encode("utf-8")).decode("ascii"),
                "body_encoding": "base64",
            })

    try:
        sio.connect(SERVER_URL, transports=["websocket", "polling"])
        sio.emit("register", {"port": local_port, "name": name})
        sio.wait()
    except KeyboardInterrupt:
        sio.disconnect()
        print("\nTunnel closed")
    except Exception as e:
        print(f"Connection error: {e}")


def main():
    args = parse_args()
    try:
        tunnel(args.port, args.name, args.verbose)
    except ValueError as e:
        print(f"Error: {e}")
    except KeyboardInterrupt:
        print("\nTunnel closed")


if __name__ == "__main__":
    main()
