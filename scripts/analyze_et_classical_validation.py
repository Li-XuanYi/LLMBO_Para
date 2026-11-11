"""Verify archived external policy events against evaluator records."""
import hashlib
import json
import math
from pathlib import Path
import sys


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def audit_external(run, *, expected_rounds):
    root = Path(run)
    try:
        assert read(root/'audit.json')['passed'], 'base archive audit failed'
        terminal = read(root/'baseline-policy-terminal.json')['state']
        assert terminal['new_evaluations'] == expected_rounds, 'budget mismatch'
        cfg = read(root/'manifest.json')['config']
        project = Path(__file__).resolve().parents[1]
        if str(project/'src') not in sys.path:
            sys.path.insert(0, str(project/'src'))
        from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
        report, prepared = prepare_electrothermal_experiment(cfg, base_dir=project)
        assert prepared is not None, 'configuration cannot be reconstructed: '+str(report.get('errors'))
        scales = cfg['optimization']['objective_scales']
        records = [read(p) for p in sorted((root/'electrothermal-evaluations').glob('*.json'))]
        by_id = {r['evaluation_id']: r for r in records}
        assert len(records) == len(by_id) == 16 + expected_rounds, 'evaluation count mismatch'
        rounds = [read(p) for p in sorted((root/'baseline-rounds').glob('*.json'))]
        assert len(rounds) == expected_rounds, 'round count mismatch'
        initial = read(root/'initialization.json')['selected_ids']
        seen = set(initial)
        events = [read(p) for p in sorted((root/'baseline-policy-events').glob('*.json'))]
        assert len(events) == terminal['library_requests'], 'event count mismatch'
        new = []
        for ordinal, event in enumerate(events):
            proposal, feedback = event['proposal'], event['feedback']
            assert proposal['ordinal'] == ordinal and event['content_sha256'] == digest([proposal, feedback]), 'event integrity mismatch'
            ident = feedback['evaluation_id']
            assert ident in by_id and feedback['complete_pair_valid'] is True, 'invalid feedback'
            normalized = prepared.space.normalize(by_id[ident]['parameters'])
            assert len(proposal['x']) == len(normalized) and all(
                math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)
                for a, b in zip(proposal['x'], normalized)), 'proposal parameters mismatch'
            assert feedback['cached'] == (ident in seen), 'cache status mismatch'
            if ordinal < 16:
                assert ident == initial[ordinal], 'initial order mismatch'
            if not feedback['cached']:
                new.append((ident, ordinal, proposal['x']))
                seen.add(ident)
            objectives = by_id[ident]['objectives']
            assert all(math.isclose(a, b/s, rel_tol=1e-12, abs_tol=1e-12)
                       for a, b, s in zip(feedback['objectives'], objectives, scales)), 'feedback objective mismatch'
        assert len(new) == expected_rounds, 'unique new count mismatch'
        for row, (ident, ordinal, x) in zip(rounds, new):
            assert (row['evaluation_id'], row['proposal_ordinal'], row['normalized_x']) == (ident, ordinal, x), 'round linkage mismatch'
        return {'passed': True, 'rounds': len(new), 'events': len(events)}
    except (AssertionError, KeyError, OSError, TypeError, ValueError) as exc:
        return {'passed': False, 'reason': str(exc)}
