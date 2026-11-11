import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

from pack_legacy import OUT, PROJECT, TOKEN, ZSTD, secrets


manifest_path = OUT / 'legacy-manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf8'))
records = manifest['other-research-records-filtered']['omitted']
if not records or any(row['reason'] != 'unreadable' for row in records):
    raise ValueError('Unexpected omitted-file list')
archive_path = OUT / 'recovered-long-paths.tar.zst.part001'
archive_file = archive_path.open('xb')
process = subprocess.Popen([str(ZSTD), '-3', '-T2', '-q', '-c'], stdin=subprocess.PIPE, stdout=archive_file)
known_secrets = secrets()
digest = hashlib.sha256()
count = 0
size = 0
try:
    with tarfile.open(fileobj=process.stdin, mode='w|') as archive:
        for record in records:
            relative = record['path']
            full_path = PROJECT / relative
            extended = chr(92) * 2 + '?' + chr(92) + str(full_path)
            content = Path(extended).read_bytes()
            if any(secret in content for secret in known_secrets) or (TOKEN.search(content) and '/tests/' not in '/' + relative):
                raise ValueError('Potential credential in recovered path: ' + relative)
            archive.addfile(archive.gettarinfo(extended, arcname=relative), io.BytesIO(content))
            digest.update(relative.encode('utf8') + b'\0' + hashlib.sha256(content).digest())
            count += 1
            size += len(content)
    process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError('compression failed')
finally:
    archive_file.close()
with archive_path.open('rb') as stream:
    part_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
manifest['recovered-long-paths'] = {'source': 'long-path recovery', 'files': count,
    'uncompressed_bytes': size, 'content_manifest_sha256': digest.hexdigest(), 'omitted': [],
    'recovers': 'other-research-records-filtered unreadable entries',
    'parts': [{'name': archive_path.name, 'bytes': archive_path.stat().st_size, 'sha256': part_hash}]}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
print(f'Recovered {count} long-path files', flush=True)
