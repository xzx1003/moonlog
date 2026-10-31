"""Run locked synthetic evaluation against the production MoonBit detector."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from core import (ALGORITHMS, COMMON_WARMUP, corpus, dataset_hash, default,
                  predict, score, select, summarize)

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, default=ROOT/'_build/native/release/build/evaluation/adapter/adapter.exe')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output exists; choose a new path to preserve results')
    binary = args.binary.resolve()
    tune, test = corpus('tune'), corpus('test')
    result = dict(kind='synthetic injected anomaly evaluation; NOT service incident accuracy',
                  protocol_version=1, common_warmup=COMMON_WARMUP,
                  environment=dict(platform=platform.platform(),
                    moon=subprocess.check_output(['moon','version','--all'],text=True),
                    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    working_tree_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True)),
                    binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest()),
                  datasets=dict(tune=tune,test=test),
                  dataset_hashes=dict(tune=dataset_hash(tune),test=dataset_hash(test)),
                  source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), ROOT/'evaluation/core.py', ROOT/'evaluation/adapter/main.mbt',ROOT/'detector.mbt',ROOT/'aggregate.mbt',ROOT/'types.mbt']},
                  algorithms={})
    # Freeze all selections BEFORE evaluating any test trace.
    selections = {algorithm:select(binary,tune,algorithm) for algorithm in ALGORITHMS}
    for algorithm in ALGORITHMS:
        chosen,trials = selections[algorithm]
        runs = {}
        for label,p in [('default',default(algorithm)),('selected',chosen)]:
            cases = []
            for case in test:
                hits,trace = predict(binary,case,algorithm,p)
                cases.append(dict(id=case['id'],scenario=case['scenario'],
                                  score=score(case['labels'],hits),hits=hits,
                                  # Reference trace checked against production hits.
                                  reference_trace=trace if case['scenario']=='sustained' else None))
            per_scenario = {name:summarize([c['score'] for c in cases if c['scenario']==name])
                            for name in sorted({c['scenario'] for c in cases})}
            runs[label]=dict(parameters=p,overall=summarize([c['score'] for c in cases]),
                             by_scenario=per_scenario,cases=cases)
        result['algorithms'][algorithm]=dict(search=trials,**runs)
        print(algorithm, json.dumps(runs['selected']['overall']),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2);stream.write('\n')


if __name__ == '__main__':
    main()
