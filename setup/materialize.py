"""Generate private runtime files with correctly quoted configurable paths."""
import ast
import io
import json
import re
import tokenize
from pathlib import Path
from settings import ROOT,read_state

OLD_ARK=r'D:\ArknightsLocal-Codex-20261103'
OLD_ISAAC=r'D:\IsaacArknights-Codex'


def rewrite_js(text,paths):
    def literal(match):
        try:value=ast.literal_eval(match.group(0))
        except (ValueError,SyntaxError):return match.group(0)
        changed=value
        for old,new in paths:
            changed=changed.replace(old,str(new)).replace(old.lower(),str(new).lower())
        return json.dumps(changed,ensure_ascii=False) if changed!=value else match.group(0)
    text=re.sub(r'''(['"])(?:\\.|(?!\1)[^\\])*?\1''',literal,text)
    for old,new in paths:
        # Forward-slash paths used by Lua or an embedded Lua command.
        old_forward=old.replace('\\','/')
        new_forward=Path(new).as_posix()
        text=text.replace(old_forward,new_forward)
    return text


def rewrite_value(value,paths):
    result=rewrite_js(value,paths)
    for old,new in paths:
        result=result.replace(old,str(new)).replace(old.replace('\\','/'),Path(new).as_posix())
    return result.replace('ark-venv/Scripts/pythonw.exe','../runtime/pythonw.exe').replace('ark-venv/Scripts/python.exe','../runtime/python.exe')


def rewrite_python(source,paths):
    tokens=[]
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type==tokenize.STRING:
            try:value=ast.literal_eval(token.string)
            except (ValueError,SyntaxError):value=None
            if isinstance(value,str):
                changed=rewrite_value(value,paths)
                if changed!=value:token=token._replace(string=repr(changed))
        tokens.append(token)
    result=tokenize.untokenize(tokens)
    compile(result,'<release-runtime>','exec')
    return result


def generate():
    state=read_state();games=state['games'];ports=state['ports']
    ark=Path(games.get('arknights',{}).get('destination',ROOT/'games/Arknights'))
    isaac_info=games.get('isaac',{})
    isaac=Path(isaac_info.get('runtimeDestination',isaac_info.get('destination',ROOT/'games/Isaac')))
    paths=[(OLD_ARK,ark),(OLD_ISAAC,isaac)]
    templates=ROOT/'payload/templates'
    for source in templates.rglob('*'):
        if not source.is_file():continue
        target=ROOT/source.relative_to(templates);target.parent.mkdir(parents=True,exist_ok=True)
        if source.suffix in ('.py','.js','.lua','.ps1','.cmd'):
            text=source.read_text(encoding='utf-8')
            if source.suffix=='.py':text=rewrite_python(text,paths)
            elif source.suffix=='.js':text=rewrite_js(text,paths)
            else:text=rewrite_value(text,paths)
            for original,key in ((27042,'pc'),(27043,'isaac'),(18731,'bridge'),(8443,'server')):
                text=re.sub(r'(?<!\d)'+str(original)+r'(?!\d)',str(ports[key]),text)
            if source.suffix=='.py':
                text=text.replace('frida.get_remote_device()',f"frida.get_device_manager().add_remote_device('127.0.0.1:{ports['pc']}')")
            # Artwork paths in a Lua literal are quoted independently.
            if source.suffix=='.lua':
                match=re.search(r"local artRoot='[^\n]*?'",text)
                if match:
                    art=(isaac/'client/mods/isaac_arknights_bridge/resources/gfx/ark_enemies').as_posix()+'/'
                    text=text[:match.start()]+'local artRoot='+json.dumps(art,ensure_ascii=False)+text[match.end():]
            target.write_text(text,encoding='utf-8')
        else:target.write_bytes(source.read_bytes())
    return state
