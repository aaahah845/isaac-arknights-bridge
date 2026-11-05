// Keep only the independent Isaac test copy on the current Windows output.
if (Process.mainModule.path.toLowerCase() !==
    'd:\\isaacarknights-codex\\client\\repentogon\\isaac-ng.exe') {
    throw Error('Unexpected Isaac process');
}
const audioModule = Process.getModuleByName('OpenAL32.dll');
function audioFn(name, result, args) {
    return new NativeFunction(audioModule.getExportByName(name), result, args);
}
const audioContext = audioFn('alcGetCurrentContext', 'pointer', []);
const audioDevice = audioFn('alcGetContextsDevice', 'pointer', ['pointer']);
const audioString = audioFn('alcGetString', 'pointer', ['pointer', 'int']);
const audioExtension = audioFn('alcIsExtensionPresent', 'uint8', ['pointer', 'pointer']);
const audioProcedure = audioFn('alcGetProcAddress', 'pointer', ['pointer', 'pointer']);
const audioError = audioFn('alcGetError', 'int', ['pointer']);
function audioText(pointer) { return pointer.isNull() ? null : pointer.readUtf8String(); }
rpc.exports.follow = () => {
    const context = audioContext();
    if (context.isNull()) return {ready:false, reason:'No audio context'};
    const device = audioDevice(context);
    if (device.isNull()) return {ready:false, reason:'No audio device'};
    // Refresh endpoint enumeration so hotplug/default changes are observable.
    audioString(ptr(0), 0x1013);
    const before = audioText(audioString(device, 0x1013));
    const target = audioText(audioString(ptr(0), 0x1012));
    if (!target) return {ready:false, reason:'No default output', before};
    if (before === target) return {ready:true, changed:false, before, after:before, target};
    if (!audioExtension(device, Memory.allocUtf8String('ALC_SOFT_reopen_device')))
        throw Error('OpenAL device reopening is unsupported');
    const address = audioProcedure(device, Memory.allocUtf8String('alcReopenDeviceSOFT'));
    if (address.isNull()) throw Error('OpenAL device reopening is unavailable');
    const reopen = new NativeFunction(address, 'uint8', ['pointer', 'pointer', 'pointer']);
    // Preserve the context, source objects, buffers, game state, and volume.
    if (!reopen(device, Memory.allocUtf8String(target), ptr(0)))
        throw Error('OpenAL output switch failed: ' + audioError(device));
    const after = audioText(audioString(device, 0x1013));
    if (after !== target) throw Error('OpenAL output did not match requested device');
    return {ready:true, changed:true, before, after, target};
};
