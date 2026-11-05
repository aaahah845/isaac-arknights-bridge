// Recover only this test client's windows when an off-screen popup is activated.
const windowUser32 = Process.getModuleByName("user32.dll");
function windowFn(name, result, args) {
    return new NativeFunction(windowUser32.getExportByName(name), result, args);
}
const windowsEnum = windowFn("EnumWindows", "int", ["pointer", "pointer"]);
const windowPid = windowFn("GetWindowThreadProcessId", "uint", ["pointer", "pointer"]);
const windowClass = windowFn("GetClassNameW", "int", ["pointer", "pointer", "int"]);
const windowRect = windowFn("GetWindowRect", "int", ["pointer", "pointer"]);
const windowOwner = windowFn("GetWindow", "pointer", ["pointer", "uint"]);
const windowVisible = windowFn("IsWindowVisible", "int", ["pointer"]);
const windowIconic = windowFn("IsIconic", "int", ["pointer"]);
const windowForeground = windowFn("GetForegroundWindow", "pointer", []);
const windowShow = windowFn("ShowWindowAsync", "int", ["pointer", "int"]);
const windowSetForeground = windowFn("SetForegroundWindow", "int", ["pointer"]);
const windowPosition = windowFn("SetWindowPos", "int", ["pointer", "pointer", "int", "int", "int", "int", "uint"]);
const windowLastPopup = windowFn("GetLastActivePopup", "pointer", ["pointer"]);

function windowProcess(handle) {
    if (handle.isNull()) return 0;
    const id = Memory.alloc(4);
    windowPid(handle, id);
    return id.readU32();
}

function windowBounds(handle) {
    const r = Memory.alloc(16);
    if (!windowRect(handle, r)) return null;
    return [0, 4, 8, 12].map(offset => r.add(offset).readS32());
}

function windowList() {
    const result = [];
    const callback = new NativeCallback((handle, unused) => {
        if (windowProcess(handle) !== Process.id) return 1;
        const name = Memory.alloc(512);
        windowClass(handle, name, 256);
        result.push({handle, cls: name.readUtf16String(), rect: windowBounds(handle),
                     iconic: !!windowIconic(handle), visible: !!windowVisible(handle),
                     owner: windowOwner(handle, 4)});
        return 1;
    }, "int", ["pointer", "pointer"]);
    windowsEnum(callback, ptr(0));
    return result;
}

function windowMain(list) {
    return list.find(item => item.cls === "UnityWndClass");
}

function windowOffscreen(item) {
    return item.rect !== null && (item.rect[0] <= -30000 || item.rect[1] <= -30000);
}

function windowState() {
    const list = windowList(), main = windowMain(list);
    return {pid: Process.id, foregroundPid: windowProcess(windowForeground()),
        minimized: main ? main.iconic : null,
        mainRect: main ? main.rect : null,
        offscreenPopups: main ? list.filter(item => item.visible && item.owner.equals(main.handle) && windowOffscreen(item)).length : 0};
}

function restoreGameWindow() {
    const list = windowList(), main = windowMain(list);
    if (!main) return false;
    windowShow(main.handle, 9); // SW_RESTORE
    setTimeout(() => {
        const refreshed = windowList(), restored = windowMain(refreshed);
        if (!restored || restored.iconic || !restored.rect) return;
        const r = restored.rect;
        for (const popup of refreshed) {
            if (!popup.visible || !popup.owner.equals(restored.handle) || !windowOffscreen(popup)) continue;
            const width = Math.max(1, popup.rect[2] - popup.rect[0]);
            const height = Math.max(1, popup.rect[3] - popup.rect[1]);
            const x = r[0] + Math.max(0, Math.round((r[2] - r[0] - width) / 2));
            const y = r[1] + Math.max(0, Math.round((r[3] - r[1] - height) / 2));
            windowPosition(popup.handle, ptr(0), x, y, 0, 0, 0x0015); // preserve size, order, activation
        }
        let target = windowLastPopup(restored.handle);
        if (target.isNull() || !windowVisible(target) || windowProcess(target) !== Process.id) target = restored.handle;
        windowSetForeground(target);
    }, 300);
    return true;
}

let strandedTicks = 0;
setInterval(() => {
    const foreground = windowForeground();
    if (windowProcess(foreground) !== Process.id) { strandedTicks = 0; return; }
    const list = windowList(), main = windowMain(list);
    const stranded = main && main.iconic && list.some(item => item.handle.equals(foreground) && item.owner.equals(main.handle) && windowOffscreen(item));
    strandedTicks = stranded ? strandedTicks + 1 : 0;
    if (strandedTicks >= 3) { strandedTicks = 0; restoreGameWindow(); }
}, 300);

rpc.exports = {restore: restoreGameWindow, state: windowState};
