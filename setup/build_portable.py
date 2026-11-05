"""Build the distributable from this source bundle, without either game installed.

From the extracted GitHub source root:
  py -3.14 setup/build_portable.py --output D:/IA-dist
Dependencies are installed from requirements.lock.txt; games are selected by
the end user only when running the two built installation wizards.
"""
import argparse,os,shutil,subprocess,sys
from pathlib import Path

def copy(source,target):target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if sys.version_info[:2]!=(3,14) or sys.maxsize<2**32:raise RuntimeError('Use standard CPython 3.14 x64 with pip installed.')
    root=Path(__file__).resolve().parent.parent;out=args.output.resolve()
    if out==root or root in out.parents or out.exists():raise ValueError('Output must be a new directory outside the source tree.')
    out.mkdir(parents=True)
    for name in ('setup','payload','components','licenses'):
        shutil.copytree(root/name,out/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','qa_*','build-cache'))
    for name in ('README.md','视频简介.txt','THIRD_PARTY_NOTICES.md','validation.json'):
        if (root/name).is_file():copy(root/name,out/name)
    runtime=out/'runtime';base=Path(sys.base_prefix)
    for p in base.iterdir():
        if p.is_file() and (p.suffix.lower() in ('.dll','.exe') or p.name=='LICENSE.txt'):copy(p,runtime/p.name)
    shutil.copytree(base/'DLLs',runtime/'DLLs',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pdb'))
    shutil.copytree(base/'Lib',runtime/'Lib',ignore=shutil.ignore_patterns('__pycache__','*.pyc','site-packages','test','tests','idlelib','ensurepip','tkinter','turtledemo'))
    packages=runtime/'Lib/site-packages';packages.mkdir(parents=True)
    subprocess.run([sys.executable,'-m','pip','install','--isolated','--disable-pip-version-check','--only-binary=:all:','--target',str(packages),'-r',str(root/'setup/requirements.lock.txt')],check=True)
    (runtime/'python314._pth').write_text('Lib\nDLLs\nLib/site-packages\n../setup\n../work\n../work/isaac-arknights\n../work/OpenBachelorS/src\nimport site\n',encoding='ascii')
    (packages/'sitecustomize.py').write_text("import sys\nfor s in (sys.stdout,sys.stderr):\n if s is not None and hasattr(s,'reconfigure'):s.reconfigure(encoding='utf-8',errors='replace')\n",encoding='utf-8')
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    for mode,name in [('arknights','01-安装方舟联动.exe'),('isaac','02-安装以撒联动.exe'),('start','03-启动联动.exe')]:
        subprocess.run([str(compiler),'/nologo','/target:winexe','/reference:System.Windows.Forms.dll','/out:'+str(out/name),str(out/'setup'/('Entry-'+mode+'.cs'))],check=True)
    subprocess.run([str(runtime/'python.exe'),'-c','import frida,lief,numpy,PIL,PySide6,uvicorn,fastapi; print("Runtime imports OK")'],check=True)
    print('Built '+str(out))

if __name__=='__main__':main()
