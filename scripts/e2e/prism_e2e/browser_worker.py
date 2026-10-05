"""The browser worker process: owns Playwright and Chromium and answers JSON-line requests on stdin.

Started by ``prism_e2e.browser.BrowserClient``; not meant to be run by hand. The human participant's
token arrives in ``PRISM_BOARD_TOKEN`` and never leaves this process except by being typed into the
board's token form. Every reply is one JSON line on the original stdout; anything else this process
prints goes to stderr.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROTOCOL = sys.stdout
sys.stdout = sys.stderr


def reply(payload: dict) -> None:
    PROTOCOL.write(json.dumps(payload, ensure_ascii=False) + "\n")
    PROTOCOL.flush()


def main() -> int:
    from prism_e2e.browser import BrowserUnavailable, HumanBrowser

    token = os.environ.pop("PRISM_BOARD_TOKEN", "")
    browser = HumanBrowser(os.environ["PRISM_E2E_BASE_URL"], token)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        operation = request.get("op")
        try:
            if operation == "start":
                browser.start()
                reply({"ok": True, "version": browser.version})
            elif operation == "perform":
                outcome = browser.perform(request["action"], request["feature_id"], Path(request["workspace"]), Path(request["screenshot_dir"]))
                reply({"ok": True, "outcome": outcome})
            elif operation == "screenshot":
                reply({"ok": browser.failure_screenshot(Path(request["path"]))})
            elif operation == "recover":
                browser.recover()
                reply({"ok": True})
            elif operation == "close":
                reply({"ok": True, "status": browser.close()})
                return 0
            else:
                reply({"ok": False, "error": f"unknown operation {operation}"})
        except BrowserUnavailable as error:
            reply({"ok": False, "error": str(error)})
        except Exception as error:  # noqa: BLE001 - one failed step is reported, the worker keeps serving
            traceback.print_exc()
            reply({"ok": False, "error": f"{type(error).__name__}: {str(error).splitlines()[0] if str(error) else ''}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
