import ast,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import installer_backend as backend
from official_patch import bspatch
from materialize import rewrite_python,rewrite_js

class InstallerTests(unittest.TestCase):
    def test_official_delta_add_insert_and_backwards_seek(self):
        import bz2
        def encode(n):return (abs(n)|(1<<63 if n<0 else 0)).to_bytes(8,'little')
        old=b'abcdef';control=b''.join(encode(n) for n in (3,1,-3,3,0,0))
        c=bz2.compress(control);d=bz2.compress(bytes([1,1,1,0,0,0]));e=bz2.compress(b'!')
        delta=b'BSDIFF40'+encode(len(c))+encode(len(d))+encode(7)+c+d+e
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'base';target=Path(folder)/'patched';source.write_bytes(old);bspatch(source,delta,target)
            self.assertEqual(target.read_bytes(),b'bcd!abc');self.assertEqual(source.read_bytes(),old)
    def test_static_sdk_copied_and_account_cache_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'official';source.mkdir();target=root/'private'
            for name in ('U8Data/config.bin','AntiCheatExpert/required.dll','sdkdata/account','mmkv/token'):
                p=source/name;p.parent.mkdir(exist_ok=True);p.write_bytes(b'fixture')
            backend.copy_client(source,target,'arknights',lambda m,p:None)
            self.assertTrue((target/'U8Data/config.bin').is_file());self.assertTrue((target/'AntiCheatExpert/required.dll').is_file())
            self.assertFalse((target/'sdkdata').exists());self.assertFalse((target/'mmkv').exists())
    def test_python_and_embedded_javascript_paths(self):
        old=r'D:\IsaacArknights-Codex';new=Path("D:/中文 空格/O'Brien/以撒")
        code="p="+repr(old+'\\client')+"\ns="+repr("if(Process.mainModule.path.toLowerCase()!=="+json.dumps(old.lower()+'\\client\\repentogon\\isaac-ng.exe')+")throw Error('wrong')")
        fixed=rewrite_python(code,[(old,new)]);ns={};exec(fixed,ns)
        self.assertEqual(ns['p'],str(new)+'\\client');self.assertNotIn('isaacarknights-codex',ns['s'])
        literal=ns['s'].split('!==',1)[1].split(')throw',1)[0];self.assertEqual(json.loads(literal),(str(new)+'\\client\\repentogon\\isaac-ng.exe').lower())
    def test_js_unicode_quoted_without_code_injection(self):
        source="if(p!=="+json.dumps(r'd:\isaacarknights-codex\client')+")throw Error('bad');"
        fixed=rewrite_js(source,[(r'D:\IsaacArknights-Codex',Path("D:/中文/O'Brien"))]);self.assertNotIn('isaacarknights-codex',fixed)
        self.assertEqual(json.loads(fixed.split('!==')[1].split(')throw')[0]),"D:\\中文\\O'Brien".lower()+r'\client')
    def test_reject_overlapping_or_existing_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'官方';source.mkdir()
            for dest in (source,source/'联动',root):
                with self.assertRaises(ValueError):backend.validate_target(source,dest)
            target=root/'old';target.mkdir()
            with self.assertRaises(ValueError):backend.validate_target(source,target)
            self.assertEqual(backend.validate_target(source,root/'副本')[1],root/'副本')
    def test_extract_refuses_traversal_drive_and_links(self):
        for name,mode in [('../escape',0),('C:/escape',0),('ok/../../escape',0),('link',0o120777)]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);archive=root/'bad.zip'
                with zipfile.ZipFile(archive,'w') as z:
                    info=zipfile.ZipInfo(name);info.external_attr=mode<<16;z.writestr(info,b'x')
                with self.assertRaises(ValueError):backend.safe_extract(archive,root/'out')
                self.assertFalse((root/'escape').exists())
    def test_valid_archive_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive=root/'good.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('repo/data/中文.json','ok')
            backend.safe_extract(archive,root/'out','repo/')
            self.assertEqual((root/'out/data/中文.json').read_text(),'ok')
    def test_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'GameAssembly.dll';p.write_bytes(b'unsupported')
            with self.assertRaises(RuntimeError):backend.check_hash(p,'0'*64)
    def test_failed_install_rolls_back_without_touching_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'Steam';source.mkdir();(source/'isaac-ng.exe').write_bytes(b'game');(source/'resources').mkdir();dest=root/'private'
            state={'format':1,'ports':{'isaac':27143},'games':{}}
            with patch.object(backend,'manifest',return_value={'isaac':{'baseExeSha256':backend.sha256(source/'isaac-ng.exe')}}),patch.object(backend,'runtime_alias',side_effect=lambda p:p),patch.object(backend,'ROOT',root/'release'),patch.object(backend,'read_state',return_value=state),patch.object(backend,'prepare_rgon',side_effect=RuntimeError('test interruption')):
                with self.assertRaisesRegex(RuntimeError,'test interruption'):backend._install('isaac',source/'isaac-ng.exe',dest,lambda m,p:None)
            self.assertEqual((source/'isaac-ng.exe').read_bytes(),b'game');self.assertFalse(dest.exists());self.assertFalse(list(root.glob('private.installing-*')))
    def test_template_failure_rolls_back_committed_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'Steam';source.mkdir();(source/'isaac-ng.exe').write_bytes(b'game');(source/'resources').mkdir();dest=root/'private'
            old={'format':1,'ports':{'isaac':27143},'games':{}};writes=[]
            with patch.object(backend,'manifest',return_value={'isaac':{'baseExeSha256':backend.sha256(source/'isaac-ng.exe')}}),patch.object(backend,'runtime_alias',side_effect=lambda p:p),patch.object(backend,'ROOT',root/'release'),patch.object(backend,'read_state',side_effect=lambda:json.loads(json.dumps(old))),patch.object(backend,'write_state',side_effect=lambda s:writes.append(s)),patch.object(backend,'prepare_rgon'),patch.object(backend,'patch_gadget'),patch.object(backend,'generate',side_effect=RuntimeError('bad template')):
                with self.assertRaisesRegex(RuntimeError,'bad template'):backend._install('isaac',source/'isaac-ng.exe',dest,lambda m,p:None)
            self.assertEqual(writes[-1]['games'],{});self.assertFalse(dest.exists());self.assertEqual((source/'isaac-ng.exe').read_bytes(),b'game')

if __name__=='__main__':unittest.main()
