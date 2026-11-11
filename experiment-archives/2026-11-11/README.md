# Retained electrothermal experiment archives

These bundles preserve the research records used for the November 2026
electrothermal comparisons, including the retained post-hoc selections and HV
reference sensitivity analysis. The five-seed factorial study remains intact.
Some later experiments were intentionally filtered after results were observed;
their filtered reports and missing full-run journals are documented in the
archived reports. Do not treat their selected seeds or post-hoc HV reference as a
pre-specified confirmatory comparison.

| Bundle | Contents |
| --- | --- |
| `factorial` | `runs/f1101` and the independent four-arm review |
| `classical-retained` | retained classical runs, review and execution records |
| `fresh-retained` | retained fresh-seed runs, software rehearsal and review |
| `hv-and-evidence` | HV recalculations, sensitivity analysis and evidence audit |

Archives are Zstandard-compressed tar streams split into parts. The manifest
records each part's SHA-256 and the ordered hash of the archived file names and
file hashes. `pack.py` documents the source paths and exclusions. Environment
directories, caches, Python bytecode, `.env` files and symlinks are omitted.

To restore a bundle, concatenate its parts in numeric order as binary data,
decompress the resulting `.tar.zst` with `zstd -d`, then extract the `.tar` at
the project root. For example, on Windows PowerShell:

```powershell
$bundle = 'factorial'
$out = [System.IO.File]::Create("$bundle.tar.zst")
try {
    Get-ChildItem "$bundle.tar.zst.part*" | Sort-Object Name | ForEach-Object {
        $in = [System.IO.File]::OpenRead($_.FullName)
        try { $in.CopyTo($out) } finally { $in.Dispose() }
    }
} finally { $out.Dispose() }
zstd -d "$bundle.tar.zst" -o "$bundle.tar"
tar -xf "$bundle.tar" -C <project-root>
```

Some archived manifests contain original absolute Windows paths. A restored
archive preserves those bytes for provenance; replay on a different machine may
require a path mapping or a compatible checkout. `source-pins.json` and archive
hashes document the historical execution state, including intentionally removed
records and changed HV reference points.
