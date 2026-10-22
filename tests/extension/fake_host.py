"""A fake local program for tests/extension/e2e.py (feature 015 tasks T021). Standard library only.

Started by Chrome through a temporary .bat as `python fake_host.py <state dir> <Chrome's arguments...>`. It appends
every request to <state dir>/requests.jsonl and answers from <state dir>/plan.json, which e2e.py rewrites per
scenario: {"<cmd>": {"reply": {...}, "data": <path of a data file to copy over the extension's> | null,
"delay": seconds}}. Every reply carries "fake": true so e2e.py can refuse to go on if anything else answered.
It never reads or writes a settings file or a database.
"""

import json
import os
import shutil
import struct
import sys
import time


def main() -> int:
    state = sys.argv[1]
    if sys.platform == "win32":
        import msvcrt

        msvcrt.setmode(0, os.O_BINARY)
        msvcrt.setmode(1, os.O_BINARY)
    head = sys.stdin.buffer.read(4)
    if len(head) < 4:
        return 0
    (size,) = struct.unpack("=I", head)
    request = json.loads(sys.stdin.buffer.read(size).decode("utf-8"))
    with open(os.path.join(state, "requests.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"request": request, "args": sys.argv[2:]}) + "\n")
    with open(os.path.join(state, "plan.json"), encoding="utf-8") as f:
        plan = json.load(f).get(request.get("cmd"), {})
    time.sleep(plan.get("delay", 0))
    if plan.get("data"):
        shutil.copyfile(plan["data"]["from"], plan["data"]["to"])
    reply = {**plan.get("reply", {"v": 1, "ok": False, "code": "bad-request", "message": "no plan"}), "fake": True}
    body = json.dumps(reply, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(body)) + body)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
