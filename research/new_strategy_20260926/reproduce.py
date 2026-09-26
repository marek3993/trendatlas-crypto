"""Copy frozen inputs/code to a new sibling research directory and rerun safely."""
import argparse,os,re,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--destination',default='new_strategy_reproduction');p.add_argument('--run',action='store_true');p.add_argument('--allow-api',action='store_true');a=p.parse_args()
    if not re.fullmatch('[a-z][a-z0-9_]{2,63}',a.destination):raise ValueError('Use a new lowercase research-directory name')
    dest=ROOT/'research'/a.destination
    if dest.exists() or dest.resolve().parent!=(ROOT/'research').resolve():raise ValueError('Destination must be new and inside this repository research directory')
    dest.mkdir()
    names=['contract.json','market_inputs.zip','cohort.json','acquisition.json','listing_evidence.json','venue_notices.json','requirements.txt','.gitattributes']
    names += [p.name for p in HERE.glob('*.py')]
    for name in names:(dest/name).write_bytes((HERE/name).read_bytes())
    print('Frozen reproduction directory:',dest)
    if a.run:
        env=os.environ.copy()
        if not a.allow_api:
            for key in ['DEEPSEEK_API_KEY','MRV1_DEEPSEEK_API_KEY']:env.pop(key,None)
        for script in ['test_framework.py','run.py','audit.py','extra_validation.py','render.py']:
            subprocess.run([sys.executable,'-W','ignore',str(dest/script)],cwd=ROOT,env=env,check=True)

if __name__=='__main__':main()
