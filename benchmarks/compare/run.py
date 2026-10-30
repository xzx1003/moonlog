#!/usr/bin/env python3
"""Identical bounded benchmark contract; see README.md for scope limitations."""
import argparse, hashlib, importlib.util, json, platform, statistics, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('baseline',ROOT/'scripts/bench_cli.py'); baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
p=argparse.ArgumentParser();p.add_argument('--go',default='/tmp/moonlog-go-reference');p.add_argument('--sizes',default='10,100');p.add_argument('--runs',type=int,default=5);p.add_argument('--output',default='benchmarks/compare/results.json');args=p.parse_args()
if args.runs < 1 or any(int(n) < 1 for n in args.sizes.split(',')):
 p.error('runs and sizes must be positive')
binaries={'moonbit':ROOT/'_build/native/release/build/benchmarks/compare/compare.exe','go':Path(args.go).resolve()}
result={'environment':{'platform':platform.platform(),'hardware':baseline.hardware(),'moon':subprocess.check_output(['moon','version','--all'],text=True),'go':'go toolchain recorded in benchmarks/compare/README.md','binary_sha256':{k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in binaries.items()}},'runs':args.runs,'warmups':1,'scope':'common benchmark contract only; no full CLI/report/context comparison','cases':[]}
with tempfile.TemporaryDirectory(prefix='moonlog-compare-') as d:
 d=Path(d)
 # Preflight an actual incident in both supported encodings, including nonempty spikes.
 fixture=(ROOT/'fixtures/incident.log').read_text().splitlines()
 for encoding in ('text','jsonl'):
  path=d/'preflight.log'
  lines=fixture if encoding=='text' else [json.dumps({'ts':line[:19],'level':line[21:line.index(']',21)],'msg':line[line.index(']',21)+2:]}) for line in fixture]
  path.write_text('\n'.join(lines)+'\n')
  left,right=[json.loads(subprocess.check_output([str(exe),str(path)])) for exe in binaries.values()]
  assert left==right and len(left['spikes'])==1, 'incident preflight mismatch'
 for size in map(int,args.sizes.split(',')):
  for fmt in ('text','jsonl'):
   for dense in (False,True):
    source=d/'input';expected=baseline.generate(source,size,fmt,dense,20261029);case={'name':f'{fmt}-{size}-'+('dense' if dense else 'sparse'),'input':expected,'samples':{'moonbit':[],'go':[]}}
    for iteration in range(args.runs+1):
     reports={}
     # Alternate process order to reduce systematic cache/order bias.
     order=list(binaries) if iteration%2==0 else list(reversed(binaries))
     for name in order:
      out=d/(name+'.json');measurement=baseline.run([str(binaries[name]),str(source)],out,d/'stderr');reports[name]=json.loads(out.read_text());measurement['mib_per_second']=expected['bytes']/1048576/measurement['seconds']
      if iteration:case['samples'][name].append(measurement)
     if reports['moonbit']!=reports['go']:raise AssertionError(case['name']+' output mismatch')
     assert reports['moonbit']['total']==expected['total']
     assert reports['moonbit']['levels']['ERROR']==expected['errors']
     assert reports['moonbit']['sha256']==expected['sha256']
    case['summary']={name:{'median_seconds':statistics.median(x['seconds'] for x in samples),'median_mib_per_second':statistics.median(x['mib_per_second'] for x in samples),'max_rss_mib':max(x['peak_rss_mib'] for x in samples),'median_cpu_seconds':statistics.median(x['user_seconds']+x['system_seconds'] for x in samples)} for name,samples in case['samples'].items()};result['cases'].append(case);print(case['name'],case['summary'],flush=True)
output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n')
lines=['# MoonBit / Go common-contract benchmark','','| Case | Language | MiB/s median | Wall s median | CPU s median | Peak RSS MiB max |','|---|---|---:|---:|---:|---:|']
for c in result['cases']:
 for name,s in c['summary'].items():lines.append(f"| {c['name']} | {name} | {s['median_mib_per_second']:.1f} | {s['median_seconds']:.3f} | {s['median_cpu_seconds']:.3f} | {s['max_rss_mib']:.1f} |")
lines+=['','Each result passed full JSON equality and input SHA-256 checks. See README.md for supported input scope and interpretation.'];output.with_suffix('.md').write_text('\n'.join(lines)+'\n')
