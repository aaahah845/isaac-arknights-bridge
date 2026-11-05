"""Build native console requests; user text is always data in the Lua adapter."""
import json


def lua_literal(value):
    return '"' + ''.join('\\%03d' % byte for byte in value.encode('utf-8')) + '"'


def console_source(command=None):
    prefix = 'local output="";local success=true;'
    if command is not None:
        command = command.strip()
        if not command:
            raise ValueError('请输入控制台指令。')
        if len(command.encode('utf-8')) > 4096 or any(ord(c) < 32 for c in command):
            raise ValueError('请使用单行指令，长度不超过 4096 字节。')
        prefix += 'success,output=pcall(Isaac.ExecuteCommand,' + lua_literal(command) + ');'
    return prefix + '''
local lines={};local history={};local commands={};
if Console and Console.GetHistory then
 local h=Console.GetHistory();for i=math.min(#h,100),1,-1 do lines[#lines+1]=h[i] end
end
if Console and Console.GetCommandHistory then
 local h=Console.GetCommandHistory();for i=math.max(1,#h-99),#h do commands[#commands+1]=h[i] end
end
return require("json").encode({ok=success,output=tostring(output or ""),lines=lines,commands=commands})
'''


def decode_response(raw):
    envelope = json.loads(raw)
    if envelope.get('status') != 0:
        raise RuntimeError(envelope.get('value') or envelope.get('error') or '以撒控制台未返回结果。')
    response = json.loads(envelope['value'])
    if not isinstance(response, dict) or 'ok' not in response:
        raise RuntimeError('控制台返回格式不正确。')
    return response
