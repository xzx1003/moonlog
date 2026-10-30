import csv, hashlib, json, subprocess, re
from pathlib import Path
root=Path(__file__).parent; out=root/'data';out.mkdir(exist_ok=True)
urls={'Apache':'https://raw.githubusercontent.com/logpai/loghub/dd61d0952749ee7963bde24220d1be5ede023033/Apache/Apache_2k.log_structured.csv','OpenStack':'https://raw.githubusercontent.com/logpai/loghub/dd61d0952749ee7963bde24220d1be5ede023033/OpenStack/OpenStack_2k.log_structured.csv','BGL':'https://raw.githubusercontent.com/logpai/loghub/dd61d0952749ee7963bde24220d1be5ede023033/BGL/BGL_2k.log_structured.csv'}
for name,url in urls.items():
 raw=out/(name+'.csv')
 if not raw.exists(): subprocess.run(['curl','-fsSL','--max-time','45','--retry','2',url,'-o',str(raw)],check=True)
 rows=list(csv.DictReader(raw.open())); dst=out/(name+'.log'); count=0; timed=0
 with dst.open('w') as f:
  for r in rows:
   if name=='Apache':
    # Source timestamps are in 2005 prose format; normalize only rows parseable by the source schema.
    import datetime
    try: ts=datetime.datetime.strptime(r['Time'],'%a %b %d %H:%M:%S %Y').strftime('%Y-%m-%d %H:%M:%S')
    except ValueError: continue
    level=r['Level'].upper();msg=r['Content']
   elif name=='OpenStack':
    ts=r['Date']+' '+r['Time'][:8];level=r['Level'];msg=r['Content']
   else:
    try: ts=__import__('datetime').datetime.strptime(r['Time'][:19],'%Y-%m-%d-%H.%M.%S').strftime('%Y-%m-%d %H:%M:%S')
    except ValueError: continue
    level=r['Level'];msg=r['Content']
   # Remove obvious identifiers; local-only output still requires manual review.
   msg=re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b','[IP]',msg)
   msg=re.sub(r'\b[0-9a-f]{32}\b|\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b','[ID]',msg,flags=re.I)
   msg=re.sub(r'(?<![A-Za-z0-9])/(?:[^\s\"<>]+)','[PATH]',msg)
   msg=msg.replace('\r',' ').replace('\n',' ')
   f.write(f'{ts} [{level}] {msg}\n');count+=1;timed+=1
 meta={'source':url,'csv_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'rows':len(rows),'normalized_lines':count,'timed_lines':timed,'normalized_sha256':hashlib.sha256(dst.read_bytes()).hexdigest(),'timestamp_policy':'source clock preserved, timezone unknown; interpreted as UTC for arithmetic only'}
 (out/(name+'.json')).write_text(json.dumps(meta,indent=2)+'\n');print(name,meta)
