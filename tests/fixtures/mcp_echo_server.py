"""A tiny stdio MCP server used by the test suite — real protocol, no network.

It speaks the same newline-delimited JSON-RPC 2.0 as a production MCP server, so
the client tests exercise real framing, real subprocess pipes and real process
teardown instead of mocks.

Flags (appended to ``args`` by the tests):

* ``--exit-immediately``  exit before reading anything (EOF handling)
* ``--noisy``             send a notification before every reply (out-of-band path)
* ``--stderr-noise``      write to stderr on start (stderr capture path)
"""

import json
import sys
import time

TOOLS = [
    {
        "name": "echo",
        "description": "Return the text you send",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "fail",
        "description": "Always answers with isError",
        "inputSchema": {"type": "object"},
    },
    {
        "name": "slow",
        "description": "Sleeps before answering",
        "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}},
    },
    {
        "name": "delete_everything",
        "description": "Dangerous name, used by the deny-pattern tests",
        "inputSchema": {"type": "object"},
    },
]


def send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(message):
    """Return a reply dict for *message*, or None for notifications."""
    method = message.get("method")
    request_id = message.get("id")

    if request_id is None:
        return None  # notification: nothing to answer

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "echo", "version": "0.0.1"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "ping":
        result = {}
    elif method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "echo":
            result = {"content": [{"type": "text", "text": "echo: " + str(arguments.get("text", ""))}]}
        elif name == "fail":
            result = {"isError": True, "content": [{"type": "text", "text": "boom"}]}
        elif name == "slow":
            time.sleep(float(arguments.get("seconds", 0.5)))
            result = {"content": [{"type": "text", "text": "slept"}]}
        elif name == "delete_everything":
            result = {"content": [{"type": "text", "text": "deleted"}]}
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "unknown tool: %s" % name},
            }
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "method not found: %s" % method},
        }

    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main(argv):
    flags = set(argv[1:])
    if "--exit-immediately" in flags:
        return 0
    if "--stderr-noise" in flags:
        sys.stderr.write("server is starting\n")
        sys.stderr.flush()

    while True:
        line = sys.stdin.readline()
        if not line:
            return 0
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue

        if "--noisy" in flags and message.get("method") and message.get("id") is not None:
            send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info"}})

        reply = handle(message)
        if reply is not None:
            send(reply)


if __name__ == "__main__":
    sys.exit(main(sys.argv))