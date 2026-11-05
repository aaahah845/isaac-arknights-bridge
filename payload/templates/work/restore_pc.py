"""Restore the test client's main window and stranded login popup."""
import json
from pathlib import Path
import sys
import time
import frida

BASE = Path(__file__).resolve().parent
EXPECTED = Path(r"D:\ArknightsLocal-Codex-20261103\client\Arknights.exe")


def connect():
    session = frida.get_remote_device().attach("Gadget")
    probe = session.create_script("rpc.exports.path=()=>Process.mainModule.path;")
    probe.load()
    if Path(probe.exports_sync.path()).resolve() != EXPECTED.resolve():
        session.detach()
        raise RuntimeError("The connection does not belong to the PC test client.")
    probe.unload()
    script = session.create_script((BASE / "pc_windows.js").read_text(encoding="utf-8"))
    script.on("message", lambda message, data: print(message, flush=True))
    script.load()
    return session, script


if __name__ == "__main__":
    session, script = connect()
    print("Before:", json.dumps(script.exports_sync.state()), flush=True)
    if not script.exports_sync.restore():
        raise RuntimeError("The game window has not been created yet.")
    for _ in range(10):
        time.sleep(0.2)
        state = script.exports_sync.state()
        if state["minimized"] is False and state["offscreenPopups"] == 0:
            break
    else:
        raise RuntimeError("The game window could not be restored to the screen.")
    print("After:", json.dumps(state), flush=True)
    if "--guard" in sys.argv:
        print("WINDOW_RESTORE_GUARD_READY", flush=True)
        while not script.is_destroyed:
            time.sleep(1)
    session.detach()
