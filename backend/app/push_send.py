"""Send phone notifications in a separate process (v2.3).

The engine passes the messages as JSON on stdin and kills this process if it does not finish in time, so a hung
notification service can never hold the engine's own database connection (27 Oct: one hung send slowed every
later database call of the cycle). Prints the result as JSON.
"""
import json
import sys


def main() -> None:
    msgs = json.loads(sys.stdin.read() or "[]")
    from .config import settings
    from .sinks import FirestoreSink

    sink = FirestoreSink(None, settings_project())
    print(json.dumps(sink._send_push(msgs)))


def settings_project():
    import os

    return os.environ.get("FIREBASE_PROJECT_ID") or None


if __name__ == "__main__":
    main()
