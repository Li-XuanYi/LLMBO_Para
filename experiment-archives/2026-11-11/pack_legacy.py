"""Export remaining local research records in split, credential-scanned bundles."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import threading
import winreg

PROJECT=Path('D:/Users/aa133/Desktop/LLMBO_Para')
OUT=Path(__file__).resolve().parent
SIZE=48*1024*1024
ZSTD=Path('C:/Users/aa133/miniconda3/Library/bin/zstd.exe')
SKIP_DIRS={'.git','__pycache__','.pytest_cache','pip-cache','site-packages','environments','node_modules'}
PREVIOUS={'f1101','cr1103','cr1103-review','n1104','n1104r','n1104s','n1104-review',
          'hv01-20261105','hv-reference-sensitivity','evidence-audit-20261106'}
# These software rehearsals retain cases deliberately removed from the active
# classical comparison; omit them to respect that selection.
REMOVED_REHEARSALS={'cs1103','cs1103b'}
TOKEN=re.compile(rb'(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,}|sk-[A-Za-z0-9]{40,}|(?i:bearer)\s+[A-Za-z0-9_.-]{60,})')


def secrets():
    found=[]
    for name in ('LLMBO_OPENCODE_API_KEY','SUB2API_API_KEY','OPENAI_API_KEY'):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:v,_=winreg.QueryValueEx(key,name)
            if isinstance(v,str) and len(v)>=20:found.append(v.encode())
        except OSError:pass
    return found


def export(name,source,exclude_top):
    proc=subprocess.Popen([str(ZSTD),'-3','-T2','-q','-c'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    pieces=[];reader_errors=[]
    def drain():
        try:
            out=None;used=0
            while block:=proc.stdout.read(1024*1024):
                if out is None or used+len(block)>SIZE:
                    if out is not None:out.close()
                    path=OUT/f'{name}.tar.zst.part{len(pieces)+1:03d}';out=path.open('xb');pieces.append(path);used=0
                out.write(block);used+=len(block)
            if out is not None:out.close()
        except BaseException as e:reader_errors.append(e)
    thread=threading.Thread(target=drain,daemon=True);thread.start()
    sensitive=secrets();omitted=[];counts={'files':0,'bytes':0};digest=hashlib.sha256()
    try:
        with tarfile.open(fileobj=proc.stdin,mode='w|') as archive:
            for current,dirs,files in os.walk(source):
                cur=Path(current)
                dirs[:]=sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(('.venv','.cache','pytest-cache'))
                               and not (cur==source and d in exclude_top)
                               and not (name=='other-research-records-filtered' and cur==source
                                        and re.fullmatch(r'(?:ge|gep|p|t)\d{10,}',d)))
                for filename in sorted(files):
                    path=cur/filename;relative=path.relative_to(PROJECT).as_posix()
                    if path.is_symlink() or filename in ('.git','.env') or filename.startswith('.env.') or filename.endswith(('.pyc','.pyo','.pem','.key','.p12','.pfx')):
                        continue
                    if cur==source and filename in ('cs1103.log','cs1103b.log'):continue
                    try:content=path.read_bytes()
                    except OSError as e:omitted.append({'path':relative,'reason':'unreadable'});continue
                    if any(s in content for s in sensitive) or (TOKEN.search(content) and '/tests/' not in '/'+relative):
                        omitted.append({'path':relative,'reason':'potential_credential'});continue
                    archive.addfile(archive.gettarinfo(str(path),arcname=relative),io.BytesIO(content))
                    counts['files']+=1;counts['bytes']+=len(content)
                    digest.update(relative.encode('utf8')+b'\0'+hashlib.sha256(content).digest())
                    if counts['files']%25000==0:print(name,counts['files'],'files',flush=True)
        proc.stdin.close();thread.join()
        if reader_errors:raise reader_errors[0]
        if proc.wait()!=0:raise RuntimeError('compression failed')
        return {'source':str(source.relative_to(PROJECT)),'files':counts['files'],'uncompressed_bytes':counts['bytes'],
            'content_manifest_sha256':digest.hexdigest(),'omitted':omitted,
            'parts':[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in pieces]}
    except BaseException:
        try:proc.stdin.close()
        except OSError:pass
        proc.kill();thread.join(timeout=10);proc.wait();raise


def main():
    result=json.loads((OUT/'legacy-manifest.json').read_text(encoding='utf8'))
    for name,source,skip in [('other-research-records-filtered',PROJECT/'bo-repair-work',{'fg-code','warmstart-v31','environments'})]:
        print('packing',name,flush=True);result[name]=export(name,source,skip)
        (OUT/'legacy-manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print('packed',name,result[name]['files'],'omitted',len(result[name]['omitted']),flush=True)


if __name__=='__main__':main()
