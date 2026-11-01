"""Persistent per-task liveness/accounting guards; no monetary or global call quota."""
from pathlib import Path
import hashlib
import json
import os
import time


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('x',encoding='utf8') as f:
        json.dump(value,f,indent=2,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
    temp.replace(path)


class FactorialBudget:
    def __init__(self,path,*,phases):
        self.path=Path(path);self.phases=phases

    @classmethod
    def start(cls,path,*,phases,protocol_sha,phase_timeout_s=21600):
        if not phases or any(set(v)!={'DFN','API'} or any(type(x) is not int or x<0 for x in v.values()) for v in phases.values()):
            raise ValueError('finite task counts required')
        obj=cls(path,phases=phases)
        obj._write({'type':'start','phases':phases,'protocol_sha':protocol_sha,'phase_timeout_s':phase_timeout_s,
                    'global_spending_quota':None,'unix':time.time(),'previous':None})
        return obj

    def _write(self,event):
        event['hash']=digest(event)
        with self.path.open('x' if event['type']=='start' else 'a',encoding='utf8') as f:
            f.write(json.dumps(event,separators=(',',':'))+'\n');f.flush();os.fsync(f.fileno())

    def state(self):
        raw=self.path.read_text(encoding='utf8')
        if not raw.endswith('\n'):raise ValueError('incomplete ledger')
        events=[json.loads(x) for x in raw.splitlines()];prev=None
        state={'phase':None,'counts':{'DFN':0,'API':0},'phase_counts':{'DFN':0,'API':0},'finished':[], 'ids':set()}
        if events[0]['type']!='start' or events[0]['phases']!=self.phases:raise ValueError('ledger origin differs')
        for e in events:
            if e['previous']!=prev or digest({k:v for k,v in e.items() if k!='hash'})!=e['hash']:raise ValueError('ledger hash chain differs')
            prev=e['hash']
            if e['type']=='begin':
                if state['phase'] or e['phase'] not in self.phases or e['phase'] in [x['phase'] for x in state['finished']]:raise ValueError('phase order differs')
                state.update(phase=e['phase'],phase_counts={'DFN':0,'API':0},phase_unix=e['unix'])
            elif e['type']=='charge':
                k=e['kind'];ident=e['event_id']
                if state['phase'] is None or k not in ('DFN','API') or ident in state['ids']:raise ValueError('invalid charge')
                state['ids'].add(ident);state['counts'][k]+=1;state['phase_counts'][k]+=1
                if state['phase_counts'][k]>self.phases[state['phase']][k]:raise ValueError('task algorithm count exceeded')
            elif e['type']=='finish':
                if state['phase'] is None:raise ValueError('orphan phase completion')
                state['finished'].append({'phase':state['phase'],'success':e['success']});state['phase']=None
            elif e['type']!='start':raise ValueError('unknown ledger event')
        state.update(hash=prev,origin=events[0],closed=len(state['finished'])==len(self.phases))
        return state

    def append(self,event):
        self._write({**event,'previous':self.state()['hash']})

    @property
    def deadline(self):
        s=self.state()
        return time.monotonic()+max(0,s.get('phase_unix',time.time())+s['origin']['phase_timeout_s']-time.time())

    def counts(self):return self.state()['counts'].copy()

    def begin(self,phase):
        s=self.state()
        if s['phase'] or phase not in self.phases or phase in [x['phase'] for x in s['finished']]:raise RuntimeError('phase already claimed')
        self.append({'type':'begin','phase':phase,'unix':time.time()})

    def require(self,calls):
        s=self.state()
        if type(calls) is not int or calls<0 or s['phase'] is None or time.monotonic()>=self.deadline or s['phase_counts']['DFN']+calls>self.phases[s['phase']]['DFN']:
            raise RuntimeError('task closed, stalled, or candidate count exceeded')

    def charge(self,kind,ident):
        self.require(0);s=self.state()
        if kind not in ('API','DFN') or ident in s['ids'] or s['phase_counts'][kind]>=self.phases[s['phase']][kind]:raise RuntimeError('duplicate or excessive task call')
        self.append({'type':'charge','kind':kind,'event_id':ident})

    def finish(self,success):
        if self.state()['phase'] is None or type(success) is not bool:raise RuntimeError('active phase required')
        self.append({'type':'finish','success':success})
