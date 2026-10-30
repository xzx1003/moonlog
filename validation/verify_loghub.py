"""Independent bucket/count oracle and coverage audit, not incident ground truth."""
import csv, datetime as dt, json, subprocess, tempfile
from collections import Counter
from pathlib import Path
root=Path(__file__).resolve().parents[1];results=[]
with tempfile.TemporaryDirectory() as tmp:
 for name in ['Apache','OpenStack','BGL']:
  source=root/'validation/data'/f'{name}.log';rows=list(csv.DictReader((source.with_suffix('.csv')).open()));target=Path(tmp)/(name+'.json')
  subprocess.run([str(root/'bin/moonlog'),'analyze',str(source),'--report',str(target),'--format','json'],check=True,stdout=subprocess.DEVNULL)
  report=json.loads(target.read_text());buckets=Counter();errors=0;levels=Counter();times=[]
  for line in source.read_text().splitlines():
   t=dt.datetime.strptime(line[:19],'%Y-%m-%d %H:%M:%S');minute=(t-dt.datetime(1,1,1)).days*1440+t.hour*60+t.minute;key=minute//5*5;level=line[21:line.index(']',21)];levels[level]+=1;error=level in ['ERROR','FATAL'];errors+=error;buckets[(key,'total')]+=1;buckets[(key,'errors')]+=error;times.append(t)
  assert report['summary']['total']==len(rows)==2000
  assert report['summary']['errors']==errors
  for b in report['buckets']:
   t=dt.datetime.strptime(b['start'],'%Y-%m-%d %H:%M:%SZ');minute=(t-dt.datetime(1,1,1)).days*1440+t.hour*60+t.minute
   assert b['total']==buckets[(minute,'total')];assert b['errors']==buckets[(minute,'errors')]
  intervals=[(dt.datetime.strptime(s['start'],'%Y-%m-%d %H:%M:%SZ'),dt.datetime.strptime(s['end_exclusive'],'%Y-%m-%d %H:%M:%SZ')) for s in report['spikes']]
  labels=[r.get('Label','-')!='-' for r in rows];hits=sum(label and any(a<=t<b for a,b in intervals) for label,t in zip(labels,times))
  results.append({'dataset':name,'provenance':json.loads(source.with_suffix('.json').read_text()),'lines':len(rows),'errors':errors,'spikes':len(intervals),'raw_levels':dict(levels),'labeled_alert_rows':sum(labels) if name=='BGL' else None,'labeled_alert_rows_inside_spike_windows':hits if name=='BGL' else None,'warning':'2k sample is not a continuous incident trace; timestamp timezone unknown; normalization required; no precision/recall claim'})
(root/'validation/loghub-results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2))
