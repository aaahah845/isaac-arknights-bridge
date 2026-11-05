"""Shared release settings; no dependency on the development workspace."""
import json
import os
from pathlib import Path

ROOT=Path(os.environ.get('IA_RELEASE_ROOT',Path(__file__).resolve().parent.parent)).resolve()
STATE=ROOT/'install-state.json'
MANIFEST=ROOT/'payload/manifest.json'
HIDDEN=0x08000000


def read_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding='utf-8'))
    return {'format':1,'ports':{'pc':27042,'isaac':27043,'bridge':18731,'server':8443},'games':{}}


def write_state(value):
    temporary=STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(STATE)


def manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def python():
    return ROOT/'runtime/python.exe'
