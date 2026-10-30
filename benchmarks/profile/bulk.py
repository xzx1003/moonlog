"""Paired bulk-vs-byte scan benchmark. Preserve binaries before running."""
import argparse, hashlib, importlib.util, json, os, statistics, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('baseline',ROOT/'scripts/bench_cli.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
p=argparse.ArgumentParser();p.add_argument('--before',required=True);p.add_argument('--after',required=True);p.add_argument('--output',required=True);p.add_argument('--size',type=int,default=100);p.add_argument('--runs',type=int,default=5);a=p.parse_args()
if a.size<1 or a.runs<1:p.error('size and runs must be positive')
bins={'before':a.before,'after':a.after}
r={'hardware':b.hardware(),'load_start':os.getloadavg(),'runs':a.runs,'warmups':1,'binaries':{k:{'path':v,'sha256':hashlib.sha256(Path(v).read_bytes()).hexdigest()} for k,v in bins.items()},'cases':[]}
with tempfile.TemporaryDirectory() as tmp:
 tmp=Path(tmp)
 for fmt in ['text','jsonl']:
  src=tmp/'input';expected=b.generate(src,a.size,fmt,True,20261029)
  twice=hashlib.sha256()
  for _ in range(2):
   with src.open('rb') as f:
    for block in iter(lambda:f.read(1048576),b''):twice.update(block)
  samples={k:{m:[] for m in ['read','digest','full']} for k in bins}
  for i in range(a.runs+1):
   mode_order=['read','digest','full'] if i%2==0 else ['full','digest','read']
   for mode in mode_order:
    outputs={}
    for name in (list(bins) if i%2==0 else list(reversed(bins))):
     x=b.run([bins[name],str(src),mode],tmp/'out',tmp/'err');outputs[name]=(tmp/'out').read_text()
     if i:samples[name][mode].append(x)
    assert outputs['before']==outputs['after'],(fmt,mode)
    if mode=='digest':
     fields=outputs['after'].split()
     assert len(fields)==3 and int(fields[0])==2*expected['total'] and fields[2]==twice.hexdigest(),(fmt,mode,outputs['after'][:120])
    elif mode=='full':
     doc=json.loads(outputs['after'])
     assert doc['sha256']==expected['sha256'] and int(doc['total'])==expected['total'] and int(doc['levels']['ERROR'])==expected['errors'],(fmt,mode)
  r['cases'].append({'format':fmt,'input':expected,'samples':samples,'median_seconds':{k:{m:statistics.median(x['seconds'] for x in xs) for m,xs in modes.items()} for k,modes in samples.items()}})
r['load_end']=os.getloadavg()
Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
for c in r['cases']:print(c['format'],c['median_seconds'])
