"""Actions entry point: collect first, publish only from an unchanged default HEAD.

Regular Git push is the remote transaction. A rejected push leaves remote state
pending; never rebase generated SQLite files or force-push them.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scraper.event_refresh import main as event_main
from scraper.stat_scraper import main as full_main, initial
from scraper.publication import FILES


def git(*args):
    return subprocess.check_output(['git',*args],text=True).strip()


def allowed_publish(env):
    branch=env.get('DEFAULT_BRANCH','')
    return bool(branch) and env.get('GITHUB_REF')=='refs/heads/'+branch and env.get('GITHUB_EVENT_NAME') in {'schedule','workflow_dispatch'}


def push_candidate(stage, mode, env):
    if not allowed_publish(env):
        raise ValueError('Publication is allowed only on the intended default branch')
    branch=env['DEFAULT_BRANCH']
    # Git validates the ref; never interpolate a branch into a shell command.
    git('check-ref-format','refs/heads/'+branch)
    expected=git('rev-parse','HEAD')
    git('fetch','origin','refs/heads/'+branch)
    if git('rev-parse','FETCH_HEAD')!=expected:
        raise ValueError('Remote baseline changed; candidate preserved. Retry from the newer baseline; do not rebase generated data.')
    tracked=git('status','--porcelain','--untracked-files=no')
    if tracked:
        raise ValueError('Tracked working copy changed before publication')
    if mode=='event':
        event_main(reviewed=stage)
    else:
        full_main(reviewed=stage)  # Deliberately no bootstrap switch.
    git('add','--',*FILES)
    if subprocess.run(['git','diff','--cached','--quiet','--',*FILES]).returncode==0:
        return False
    git('config','user.name','github-actions[bot]')
    git('config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
    git('commit','-m','Refresh validated UFC dataset and event state')
    # A concurrent remote update/branch protection rejects this ordinary push.
    # State is durable only if this commit arrives; the next run retries otherwise.
    git('push','origin','HEAD:refs/heads/'+branch)
    return True


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['event','full'],required=True)
    p.add_argument('--publish',action='store_true')
    p.add_argument('--budget',type=int,required=True)
    a=p.parse_args()
    if a.publish and not allowed_publish(os.environ):
        p.error('Default-branch restriction prevents publication')
    if a.publish and initial(Path.cwd()):
        p.error('Publication requires an explicitly bootstrapped UFC.com baseline')
    stage=(event_main if a.mode=='event' else full_main)(budget=a.budget,pace=1,workers=4)
    report=json.loads((stage/'report.json').read_text(encoding='utf-8'))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as f:
            f.write(f'candidate={stage}\n')
    summary={'candidate':str(stage),'mode':a.mode,'reason':report['reason'],
             'runtime':report.get('runtime'),'pending':report.get('pending'),
             'hosted_access':'This run only; see diagnostic evidence. Local Windows access establishes no hosted guarantee.'}
    try:
        if a.publish and report['reason']!='no work':
            summary['remote_push_succeeded'] = push_candidate(stage,a.mode,os.environ)
    except Exception as exc:
        summary['publication_error'] = str(exc)
        summary['remote_completion_acknowledged'] = False
        raise
    finally:
        Path('actions-refresh-summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:
                f.write('```json\n'+json.dumps(summary,indent=2)+'\n```\n')


if __name__=='__main__':
    main()
