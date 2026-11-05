"""Follow Windows output changes without restarting Isaac or touching volume."""
import json
import sys
import time
from pathlib import Path
import frida

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = Path(r'D:\IsaacArknights-Codex\client\Repentogon\isaac-ng.exe')


def connect():
    device = frida.get_device_manager().add_remote_device('127.0.0.1:27043')
    session = device.attach('Gadget')
    try:
        guard = session.create_script('rpc.exports.path=()=>Process.mainModule.path;')
        guard.load()
        if Path(guard.exports_sync.path()).resolve() != EXPECTED.resolve():
            raise RuntimeError('Unexpected Isaac process')
        guard.unload()
        script = session.create_script((ROOT/'tools/isaac_audio.js').read_text(encoding='utf-8'))
        script.load()
        return session, script
    except Exception:
        session.detach()
        raise


def main():
    once = '--once' in sys.argv
    session = script = None
    last_error = None
    try:
        while once or not (ROOT/'stop.flag').exists():
            try:
                if script is None:
                    session, script = connect()
                result = script.exports_sync.follow()
                if once or result.get('changed'):
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    (ROOT/'audio-route.json').write_text(json.dumps(
                        dict(result, checkedAt=time.time()), ensure_ascii=False, indent=2), encoding='utf-8')
                last_error = None
                if once:
                    if not result.get('ready'):
                        raise RuntimeError(result.get('reason', 'Audio unavailable'))
                    return
                time.sleep(2)
            except Exception as error:
                if once:
                    raise
                if str(error) != last_error:
                    print('Audio output monitor: '+str(error), flush=True)
                    last_error = str(error)
                if session:
                    try:
                        session.detach()
                    except Exception:
                        pass
                session = script = None
                time.sleep(5)
    finally:
        if session:
            session.detach()


if __name__ == '__main__':
    main()
