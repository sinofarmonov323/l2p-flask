import base64
import os
import re
import time
import uuid
from flask import Flask, request, render_template, jsonify
from flask_socketio import SocketIO, emit, disconnect
from werkzeug.wrappers import Response
from threading import Event

ENABLE_DOCS = os.getenv("LTP_ENABLE_DOCS", "").lower() in {"1", "true", "yes"}
BASE_DOMAIN = os.getenv("LTP_BASE_DOMAIN", "localhost").strip().lower().rstrip(".")
REQUEST_TIMEOUT = float(os.getenv("LTP_REQUEST_TIMEOUT", "30"))
MAX_BODY_BYTES = int(os.getenv("LTP_MAX_BODY_BYTES", str(10 * 1024 * 1024)))
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

app = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "your-secret-key")
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# stores active tunnels: name -> sid (socket id)
tunnels: dict[str, str] = {}

# stores pending requests: request_id -> {"event": Event, "response": dict}
pending: dict[str, dict] = {}


def is_valid_tunnel_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name))


def filtered_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def tunnel_name_from_host(host: str | None) -> str | None:
    if not host or not BASE_DOMAIN:
        return None

    hostname = host.split(":", 1)[0].lower().rstrip(".")
    suffix = f".{BASE_DOMAIN}"
    if hostname == BASE_DOMAIN or not hostname.endswith(suffix):
        return None

    name = hostname[:-len(suffix)]
    if "." in name or not is_valid_tunnel_name(name):
        return None
    return name


def proxy_to_tunnel(name: str, path: str):
    if not is_valid_tunnel_name(name):
        return jsonify({"error": "invalid tunnel name"}), 400

    if name not in tunnels:
        return jsonify({"error": "tunnel not found"}), 404

    tunnel_sid = tunnels[name]
    request_id = str(uuid.uuid4())

    # read request body
    body = request.get_data()
    if len(body) > MAX_BODY_BYTES:
        return jsonify({"error": "request body too large"}), 413

    # create event for synchronization
    event = Event()
    pending[request_id] = {"event": event, "response": None}

    # forward request to CLI client via WebSocket
    socketio.emit("request", {
        "request_id": request_id,
        "method": request.method,
        "path": f"/{path}",
        "query_string": request.query_string.decode("utf-8") if request.query_string else "",
        "headers": filtered_headers(dict(request.headers)),
        "body": base64.b64encode(body).decode("ascii"),
        "body_encoding": "base64",
    }, room=tunnel_sid)

    try:
        # wait for CLI client to respond
        if event.wait(timeout=REQUEST_TIMEOUT):
            response = pending[request_id]["response"]
            pending.pop(request_id, None)

            response_body = response.get("body", "")
            if response.get("body_encoding") == "base64":
                content = base64.b64decode(response_body)
            else:
                content = response_body.encode("utf-8") if isinstance(response_body, str) else response_body

            return Response(
                content,
                status=response.get("status", 200),
                headers=filtered_headers(response.get("headers", {})),
            )
        else:
            # Timeout
            pending.pop(request_id, None)
            return jsonify({"error": "tunnel timeout"}), 504

    except Exception as e:
        pending.pop(request_id, None)
        return jsonify({"error": str(e)}), 500


@app.route("/")
def homepage():
    name = tunnel_name_from_host(request.headers.get("host"))
    if name:
        return proxy_to_tunnel(name, "")

    return render_template("index.html")


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/join/<name>/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def proxy_join(name, path):
    return proxy_to_tunnel(name, path)


@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def subdomain_proxy(path):
    name = tunnel_name_from_host(request.headers.get("host"))
    if not name:
        return jsonify({"error": "tunnel not found"}), 404

    return proxy_to_tunnel(name, path)


@socketio.on("register")
def handle_register(data):
    """Handle tunnel registration from CLI client"""
    port = data.get("port")
    name = data.get("name", "").strip().lower()

    if not is_valid_tunnel_name(name):
        emit("error", {"error": "invalid tunnel name"})
        disconnect()
        return

    if name in tunnels:
        emit("error", {"error": "tunnel name already in use"})
        disconnect()
        return

    tunnels[name] = request.sid
    print(f"Client registered: {name} -> localhost:{port}")

    emit("registered", {"name": name})
    if BASE_DOMAIN:
        print(f"Tunnel open at https://{name}.{BASE_DOMAIN}/")
    else:
        print(f"Tunnel open at /join/{name}")


@socketio.on("response")
def handle_response(data):
    """Handle response from CLI client"""
    request_id = data.get("request_id")

    if request_id in pending:
        pending[request_id]["response"] = data
        pending[request_id]["event"].set()


@socketio.on("disconnect")
def handle_disconnect():
    """Handle client disconnection"""
    for tunnel_name, tunnel_sid in list(tunnels.items()):
        if tunnel_sid == request.sid:
            tunnels.pop(tunnel_name, None)
            print(f"Tunnel closed: {tunnel_name}")
            break


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    socketio.run(app, port=port, debug=False)
