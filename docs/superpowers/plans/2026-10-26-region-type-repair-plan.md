# Region fixed metadata compatibility and paired validation

Status: approved by the user's 2026-10-26 instruction to fix the extra `type`
field and complete the 20-round RMSE/HV comparison. This is the concrete
implementation of that requested correction, not a new Region method.

## Scope and contract

Actual evidence: `opencode-paired-retry3-20261025/reply-diagnosis.json`.
Three HTTP200 replies had correct frozen request IDs and valid regions but an
extra top-level `"type":"json_object"`. Old raw replies and rejections remain
immutable. Only `electrothermal_lgbo_wire.decode_lgbo_action()` gains an inbound
compatibility exception for that exact string. The outbound contract continues
to request only request_id/region. Every other extra key, wrong metadata value,
stale ID, malformed region or non-finite value is rejected. No mutation of the
incoming reply, payload, identity, objectives, GP or posterior variance.
Existing non-LGBO formats and old caches retain their original rules.

## Execution

1. Run current wire regression; add failures for both LGBO versions and both
   actions with the fixed metadata. Cover invalid metadata, other extra fields,
   stale context and invalid regions while metadata is present. Observe RED,
   implement the narrow check, then run targeted and complete software regression
   with sockets and battery solves blocked; save logs/JUnit/exit codes.
2. Replay all five archived replies offline with the corrected decoder. Preserve
   original raw responses and historical failure counts. Review the change,
   commit an explicit file list, freeze current source and software evidence.
3. New independent validation under the established maximum of 66 API requests,
   256 DFN solves and 10800 seconds from live start. Same endpoint/model, single
   thread, no automatic retries, HTTP failures or three consecutive protocol
   failures stop. One minimal and three complete historical Region contexts
   must pass binding and frozen GP/EI checks with nonzero tilt before DFN.
   Reevaluation of the same eight coordinates produces a new signed plan under
   repaired source; both arms use it, with three fixed seeds and 20 new rounds
   each. This avoids mixing a new implementation signature with old cache data.
   Reuse existing 0.5C/1C 60-second synthetic observations, no new observations,
   measured fitting, old 3C or WarmStart API. Old closed campaign costs remain
   API14/DFN66 and are reported separately from new charges.
4. Independently recompute RMSE from saved curves and HV in the fixed
   [F_U/0.1V,F_T/1K] space with reference [10,10]. Compare complete paired arms
   only, report all seeds and Pareto parameter sets, Region receipt/tilt/selection
   counts and positive/negative results. Failure does not become zero error or
   an invented 20-round gain. This trial isolates Region on shared initialization.

## Boundaries

The user directly authorized the specific fix and continuation, so there is no
additional plan approval stop for this exact scope. No change to Prompt,
numerical algorithm, thermal model, rates, objective scales, seeds or stopping
rules. No secret in source/config/arguments/logs/snapshots; read only the dedicated
OpenCode environment credential. Evidence root:
`bo-repair-work/20261017_et_implementation/region-type-repair-20261026`.
