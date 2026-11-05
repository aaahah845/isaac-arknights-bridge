"""Start and stop the independent Windows PC test client."""
import base64
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work"
PYTHON = WORK / "ark-venv/Scripts/python.exe"
GAME = Path(r"D:\ArknightsLocal-Codex-20261103\client\Arknights.exe")
HIDDEN = subprocess.CREATE_NO_WINDOW


def run(args, **kwargs):
    return subprocess.run(args, creationflags=HIDDEN, **kwargs)


def powershell(script):
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return run(["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
               capture_output=True, text=True, timeout=90)


def quote_ps(value):
    return "'" + str(value).replace("'", "''") + "'"


def health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8443/config/prod/official/Windows/version", timeout=2) as response:
            return json.load(response).get("clientVersion") == "2.7.91"
    except Exception:
        return False


def port_ready():
    try:
        with socket.create_connection(("127.0.0.1", 27042), timeout=0.5):
            return True
    except OSError:
        return False


def start_worker(name, args, cwd):
    with (WORK / f"{name}.stdout.log").open("w", encoding="utf-8") as out, (WORK / f"{name}.stderr.log").open("w", encoding="utf-8") as err:
        process = subprocess.Popen(args, cwd=cwd, stdout=out, stderr=err, creationflags=HIDDEN)
    (WORK / f"{name}.pid").write_text(str(process.pid))
    return process


def process_command(pid):
    result = powershell(f"$c=(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine; if($c){{[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($c))}}")
    value = result.stdout.strip()
    return base64.b64decode(value).decode("utf-8") if value else ""


def stop_worker(name, marker):
    path = WORK / f"{name}.pid"
    if path.exists():
        pid = int(path.read_text().strip())
        if marker in process_command(pid):
            run(["taskkill.exe", "/PID", str(pid), "/T", "/F"], capture_output=True)


def stop():
    helper = WORK / "stop_pc.ps1"
    result = powershell("$p=Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList "
                        + quote_ps('-NoProfile -ExecutionPolicy Bypass -File "' + str(helper) + '"')
                        + " -PassThru; $p.WaitForExit()")
    if result.returncode:
        raise RuntimeError("未能关闭 PC 测试窗口，请手动退出后重试。")
    stop_worker("pc-client", "attach_pc.py")
    stop_worker("server", "openbachelors.app:app")
    print("PC 本地测试服已关闭。官服版仍从原启动器进入。")


def start():
    if not GAME.is_file():
        raise RuntimeError("找不到方舟联动副本，请检查安装位置。")
    print("正在启动 PC 本地测试服……", flush=True)
    if not health():
        process = start_worker("server", [str(PYTHON), "-u", "-m", "uvicorn", "openbachelors.app:app",
                                "--host", "127.0.0.1", "--port", "8443"], WORK / "OpenBachelorS")
        for _ in range(60):
            if health():
                break
            if process.poll() is not None:
                raise RuntimeError("服务端启动失败，请查看 work/server.stderr.log。")
            time.sleep(0.5)
        else:
            raise RuntimeError("服务端启动超时，请查看 work/server.stderr.log。")
    state = WORK / "pc-client.pid"
    if port_ready() and state.exists() and "attach_pc.py" in process_command(int(state.read_text().strip())):
        result = run([str(PYTHON), str(WORK / "restore_pc.py")], capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError("客户端仍在运行，但窗口恢复失败，请查看游戏窗口状态。")
        print("已恢复 PC 本地测试客户端窗口。")
        return
    stop_worker("pc-client", "attach_pc.py")
    process = start_worker("pc-client", [str(PYTHON), "-u", str(WORK / "attach_pc.py")], WORK)
    if not port_ready():
        print("Windows 如请求管理员许可，请核对启动的是联动副本。", flush=True)
        args = '-logFile "' + str(WORK / "pc-unity.log") + '"'
        script = "$p=Start-Process -FilePath " + quote_ps(GAME) + " -WorkingDirectory " + quote_ps(GAME.parent)
        script += " -ArgumentList " + quote_ps(args) + " -Verb RunAs -PassThru; $p.Id"
        result = powershell(script)
        ids = [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]
        if result.returncode or not ids:
            stop_worker("pc-client", "attach_pc.py")
            raise RuntimeError("PC 客户端未启动，可能是管理员许可被取消。")
        (WORK / "pc-game.pid").write_text(ids[-1])
    for _ in range(140):
        log = (WORK / "pc-client.stdout.log").read_text(encoding="utf-8", errors="replace")
        if "LOCAL_CLIENT_READY" in log:
            print("PC 本地服务与客户端连接已启动，请在游戏窗口继续。")
            return
        if process.poll() is not None:
            raise RuntimeError("PC 客户端连接失败，请查看 work/pc-client.stderr.log。")
        time.sleep(0.5)
    raise RuntimeError("PC 客户端连接超时，请查看 work/pc-client.stdout.log。")


if __name__ == "__main__":
    try:
        stop() if len(sys.argv)>1 and sys.argv[1]=="stop" else start()
    except Exception as error:
        print("操作未完成："+str(error), file=sys.stderr)
        sys.exit(1)
