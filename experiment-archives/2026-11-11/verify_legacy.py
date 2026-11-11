import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import threading


root = Path(__file__).resolve().parent
zstd = Path('C:/Users/aa133/miniconda3/Library/bin/zstd.exe')
manifest = json.loads((root / 'legacy-manifest.json').read_text(encoding='utf-8'))
for group, info in manifest.items():
    if len(sys.argv) > 1 and group not in sys.argv[1:]:
        continue
    for entry in info['parts']:
        part = root / entry['name']
        if part.stat().st_size != entry['bytes']:
            raise ValueError(f'{part.name}: size mismatch')
        with part.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != entry['sha256']:
            raise ValueError(f'{part.name}: hash mismatch')
    process = subprocess.Popen([str(zstd), '-d', '-q', '-c'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    errors = []

    def feed():
        try:
            for entry in info['parts']:
                with (root / entry['name']).open('rb') as source:
                    while chunk := source.read(1024 * 1024):
                        process.stdin.write(chunk)
            process.stdin.close()
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=feed)
    worker.start()
    digest = hashlib.sha256()
    files = 0
    size = 0
    with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
        for member in archive:
            if not member.isfile():
                raise ValueError(f'unexpected tar entry: {member.name}')
            stream = archive.extractfile(member)
            file_hash = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                file_hash.update(chunk)
            digest.update(member.name.encode('utf-8') + b'\0' + file_hash.digest())
            files += 1
            size += member.size
    while process.stdout.read(1024 * 1024):
        pass
    worker.join()
    if errors:
        raise errors[0]
    if process.wait() or files != info['files'] or size != info['uncompressed_bytes'] or digest.hexdigest() != info['content_manifest_sha256']:
        raise ValueError(f'{group}: archive verification failed')
    print(f'{group}: verified {files} files, {len(info["parts"])} parts', flush=True)
