"""Create split Zstandard tar bundles of the retained research archives.

Paths are project-root relative inside each archive. Existing local records are
read only. Parts are split below the GitHub per-file limit.
"""
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
PART_SIZE=48*1024*1024
ZSTD=Path('C:/Users/aa133/miniconda3/Library/bin/zstd.exe')
GROUPS={
    'factorial': ['runs/f1101','bo-repair-work/20261017_et_implementation/fourarm-results-review-20261102'],
    'classical-retained': ['runs/cr1103','runs/cr1103-review','bo-repair-work/20261017_et_implementation/classical-baselines-20261102'],
    'fresh-retained': ['runs/n1104','runs/n1104r','runs/n1104s','runs/n1104-review'],
    'hv-and-evidence': ['runs/hv01-20261105','runs/hv-reference-sensitivity','runs/evidence-audit-20261106'],
}
EXCLUDE_DIRS={'.git','__pycache__','.pytest_cache','pip-cache','site-packages','environments','node_modules'}
TOKEN_PATTERN=re.compile(rb'(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,}|sk-[A-Za-z0-9]{40,}|(?i:bearer)\s+[A-Za-z0-9_.-]{40,})')


def credential_values():
    values=[]
    for name in ('LLMBO_OPENCODE_API_KEY','SUB2API_API_KEY','OPENAI_API_KEY'):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
                value,_=winreg.QueryValueEx(key,name)
            if isinstance(value,str) and len(value)>=20:values.append(value.encode())
        except OSError:pass
    return values


def pack(name,sources,secrets):
    compressor=subprocess.Popen([str(ZSTD),'-3','-T2','-q','-c'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    parts=[];failure=[]
    def output_reader():
        try:
            stream=None;used=0
            while True:
                block=compressor.stdout.read(1024*1024)
                if not block:break
                if stream is None or used+len(block)>PART_SIZE:
                    if stream is not None:stream.close()
                    path=OUT/f'{name}.tar.zst.part{len(parts)+1:03d}'
                    stream=path.open('xb');parts.append(path);used=0
                stream.write(block);used+=len(block)
            if stream is not None:stream.close()
        except BaseException as exc:failure.append(exc)
    thread=threading.Thread(target=output_reader,daemon=True);thread.start()
    count=0;size=0;digest=hashlib.sha256()
    try:
        with tarfile.open(fileobj=compressor.stdin,mode='w|') as tar:
            for rel in sources:
                source=PROJECT/rel
                if not source.is_dir():raise ValueError(f'missing source {source}')
                for current,dirs,files in os.walk(source):
                    dirs[:]=sorted(d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.venv'))
                    for filename in sorted(files):
                        path=Path(current)/filename
                        if path.is_symlink() or filename.endswith(('.pyc','.pyo')) or filename=='.env':continue
                        relative=path.relative_to(PROJECT).as_posix()
                        contents=path.read_bytes()
                        if any(secret in contents for secret in secrets):raise ValueError('credential match: '+relative)
                        # Source test snapshots contain deliberately fake bearer/key fixtures.
                        if TOKEN_PATTERN.search(contents) and '/tests/' not in '/'+relative:
                            raise ValueError('potential token requires review: '+relative)
                        info=tar.gettarinfo(str(path),arcname=relative)
                        tar.addfile(info,io.BytesIO(contents))
                        count+=1;size+=len(contents)
                        digest.update(relative.encode('utf8')+b'\0'+hashlib.sha256(contents).digest())
        compressor.stdin.close();thread.join()
        if failure:raise failure[0]
        if compressor.wait()!=0:raise RuntimeError('zstd failed')
        return {'sources':sources,'files':count,'uncompressed_bytes':size,'content_manifest_sha256':digest.hexdigest(),
                'parts':[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in parts]}
    except BaseException:
        try:compressor.stdin.close()
        except OSError:pass
        compressor.kill();thread.join(timeout=10);compressor.wait()
        raise


def main():
    secrets=credential_values();result={}
    for name,sources in GROUPS.items():
        print('packing',name,flush=True)
        result[name]=pack(name,sources,secrets)
        print('packed',name,result[name]['files'],'files',flush=True)
    (OUT/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':main()
