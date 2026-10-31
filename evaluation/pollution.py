"""Evaluation-only baseline contamination experiments; no production policy change."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from core import default, predict, reference, score, summarize


def frozen_reference(errors, p):
    n=p['window']; baseline=sum(errors[:n])/n; hits=[False]*len(errors); trace=[]
    for i in range(n,len(errors)):
        threshold=baseline*p['multiplier']
        hit=errors[i]>=p['minimum'] and errors[i]>threshold
        hits[i]=hit
        trace.append(dict(bucket=i,baseline=baseline,threshold=threshold,hit=hit))
        if not hit:
            alpha=p['parameter_tenths']/10
            baseline=alpha*errors[i]+(1-alpha)*baseline
    return hits,trace


def freeze_predict(binary, errors, p):
    rows=json.loads(subprocess.check_output([str(binary),'ewma-freeze',str(p['window']),
        str(p['multiplier']),str(p['minimum']),str(p['parameter_tenths']),
        ','.join(map(str,errors))],text=True,timeout=10))
    hits,trace=frozen_reference(errors,p)
    import math
    for row,expected in zip(rows,trace):
        assert row[0]==expected['bucket'] and row[3]==expected['hit']
        assert math.isclose(row[1],expected['baseline'],rel_tol=1e-12,abs_tol=1e-12)
        assert math.isclose(row[2],expected['threshold'],rel_tol=1e-12,abs_tol=1e-12)
    assert len(rows)==len(trace)
    return hits,trace


def experiment(binary):
    records=[]
    # Normal step changes are negative controls for the freeze policy's lock-in.
    for scenario in ['sustained-recovery','healthy-level-shift','intermittent']:
        errors=[1]*18+[20]*30+[1]*18
        labels=[False]*18+[True]*30+[False]*18
        if scenario=='healthy-level-shift':
            errors=[1]*18+[20]*48;labels=[False]*66
        if scenario=='intermittent':
            errors=[1]*18+([20]*3+[1]*3)*5+[1]*18
            labels=[False]*18+([True]*3+[False]*3)*5+[False]*18
        for alpha in [1,3,5,8]:
            p=default('ewma');p['parameter_tenths']=alpha
            case=dict(id=scenario,errors=errors)
            for policy in ['update-all','freeze-on-alert']:
                hits,trace=(predict(binary,case,'ewma',p) if policy=='update-all'
                            else freeze_predict(binary,errors,p))
                records.append(dict(scenario=scenario,policy=policy,parameters=p,
                    errors=errors,labels=labels,hits=hits,trace=trace,
                    metrics=summarize([score(labels,hits)])))
    mad=[]
    # Every occupancy 0..n, both flat and variable contaminants, both temporal
    # arrangements: median/MAD is order invariant; later moving windows aren't.
    for n in [6,12]:
        for count in range(n+1):
            for shape in ['flat','variable']:
                contaminated=[20 if shape=='flat' else 15+3*i for i in range(count)]
                clean=[1]*(n-count)
                for order in ['early','late']:
                    history=contaminated+clean if order=='early' else clean+contaminated
                    errors=history+[20]*12+[1]*n
                    p=default('mad');p['window']=n
                    hits,trace=predict(binary,dict(id='mad-history',errors=errors),'mad',p)
                    # Fixed probe labels describe an injected event, not each
                    # history contaminant's operational meaning.
                    mad.append(dict(window=n,contaminated=count,shape=shape,order=order,
                        errors=errors,hits=hits,trace=trace,
                        probe_hit=hits[n],probe_baseline=trace[0]['baseline'],
                        probe_threshold=trace[0]['threshold']))
    return dict(kind='synthetic baseline contamination; not production fault accuracy',
        ewma=records,mad=mad)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--binary',type=Path,default=Path(__file__).resolve().parents[1]/'_build/native/release/build/evaluation/adapter/adapter.exe')
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args()
    if a.output.exists():parser.error('output exists')
    result=experiment(a.binary)
    result['binary_sha256']=hashlib.sha256(a.binary.read_bytes()).hexdigest()
    result['source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(__file__).with_name('core.py'),Path(__file__).parent/'adapter/main.mbt']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')


if __name__=='__main__':main()
