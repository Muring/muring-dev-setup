"""Opt-in Git-backed daily publishing. Caller holds the tracker lock.

No commands execute on import. Tests inject collection, sync and GitHub adapters.
Dispatch acceptance is never a DB receipt; failed/uncertain attempts remain visible.
"""
from datetime import timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

from usage_publish_common import due_period, durable_write
from usage_store import now, read
from usage_publish import validate_ack

WORKFLOW='publish-ai-usage.yml'
WORKFLOW_PATH='.github/workflows/'+WORKFLOW
ARTIFACT='ai-usage-publish-receipt'
DONE={'applied','already_applied','superseded'}


def full_sha(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{40}',value):raise ValueError('Full usage-data SHA40 required')
    return value


def settings(config):
    value=config.get('publisher',{})
    if value.get('mode')!='git-workflow' or set(value)-{'mode','repository'}:raise ValueError('Configure publisher mode git-workflow and repository only')
    repository=value.get('repository','')
    if not isinstance(repository,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('GitHub owner/repository required')
    if config.get('delivery',{}).get('mode')=='device-v1':raise ValueError('Disable raw-device delivery before enabling Git publishing')
    return repository


def validate_remote(repository,remote):
    match=re.fullmatch(r'(?:git@github\.com:|https://github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?',remote)
    if not match or match[1].lower()!=repository.lower():raise ValueError('Publisher repository differs from the guarded GitHub origin')


def validate_run(run,request_id,repository,workflow_id):
    if not isinstance(run,dict):raise ValueError('Invalid workflow run')
    expected={'display_title':'ai-usage-'+request_id,'event':'workflow_dispatch','head_branch':'main','workflow_id':workflow_id}
    if any(type(run.get(k)) is not type(v) or run[k]!=v for k,v in expected.items()):raise ValueError('Workflow run is outside the requested main dispatch')
    path=run.get('path','').split('@')
    if path[0]!=WORKFLOW_PATH or len(path)>2 or len(path)==2 and path[1] not in ('main','refs/heads/main'):raise ValueError('Unexpected workflow path/ref')
    if run.get('repository',{}).get('full_name','').lower()!=repository.lower():raise ValueError('Unexpected run repository')
    for field in ('id','run_number','run_attempt'):
        if type(run.get(field)) is not int or not 1<=run[field]<=9007199254740991:raise ValueError('Invalid run identity')
    full_sha(run.get('head_sha'))
    if run.get('status') not in ('queued','requested','waiting','pending','in_progress','completed'):raise ValueError('Unknown workflow status')
    if run['status']=='completed' and not isinstance(run.get('conclusion'),str):raise ValueError('Missing workflow conclusion')
    return run


def validate_receipt(receipt,run_sequence):
    fields={'schema','state','requestedSequence','requestedRevision','appliedSequence','appliedRevision'}
    if not isinstance(receipt,dict) or set(receipt)!=fields or type(receipt['schema']) is not int or receipt['schema']!=1:raise ValueError('Invalid publish receipt')
    if type(receipt['requestedSequence']) is not int or receipt['requestedSequence']!=run_sequence:raise ValueError('Receipt sequence differs from workflow run')
    full_sha(receipt['requestedRevision']);full_sha(receipt['appliedRevision'])
    if receipt['state'] not in DONE:raise ValueError('Receipt does not establish a DB outcome')
    expected=validate_ack(dict(accepted=receipt['state']=='applied',sequence=receipt['appliedSequence'],sourceRevision=receipt['appliedRevision']),run_sequence,receipt['requestedRevision'])
    if receipt!=expected:raise ValueError('Contradictory publish receipt')
    return receipt


class GitHub:
    """gh provides credentials; never return command stderr or secret values."""
    def __init__(self,repository):self.repository=repository;self.workflow_id=None

    def command(self,args,input=None):
        env=dict(os.environ,GH_HOST='github.com',GH_PROMPT_DISABLED='1')
        try:
            result=subprocess.run(['gh',*args],input=input,capture_output=True,text=True,timeout=60,env=env)
        except (OSError,subprocess.SubprocessError) as exc:raise RuntimeError('GitHub command unavailable') from exc
        if result.returncode:raise RuntimeError('GitHub command failed')
        if len(result.stdout)>8_000_000:raise ValueError('Oversize GitHub response')
        return result.stdout

    def api(self,path,payload=None):
        args=['api','--hostname','github.com','repos/'+self.repository+'/'+path]
        if payload is not None:args+=['--method','POST','--input','-']
        output=self.command(args,json.dumps(payload) if payload is not None else None)
        return json.loads(output) if output.strip() else None

    def workflow(self):
        if self.workflow_id is None:
            data=self.api('actions/workflows/'+WORKFLOW)
            if not isinstance(data,dict) or data.get('path')!=WORKFLOW_PATH or type(data.get('id')) is not int or data['id']<1:raise ValueError('Unexpected publisher workflow')
            self.workflow_id=data['id']
        return self.workflow_id

    def dispatch(self,revision,request_id):
        self.workflow()
        self.api('actions/workflows/'+WORKFLOW+'/dispatches',dict(ref='main',inputs=dict(requested_revision=revision,request_id=request_id)))

    def find_run(self,request_id):
        workflow_id=self.workflow()
        # Bounded discovery. A missing older run stays unknown, never successful.
        matches=[]
        for page in range(1,6):
            data=self.api(f'actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&branch=main&per_page=100&page={page}')
            rows=data['workflow_runs']
            for row in rows:
                if row.get('display_title')=='ai-usage-'+request_id:
                    matches.append(validate_run(row,request_id,self.repository,workflow_id))
            if matches or len(rows)<100:break
        if len(matches)>1:raise ValueError('Ambiguous dispatch run')
        return matches[0] if matches else None

    def receipt(self,run):
        artifacts=self.api(f"actions/runs/{run['id']}/artifacts?per_page=100")['artifacts']
        matches=[a for a in artifacts if a.get('name')==ARTIFACT and a.get('expired') is False]
        if len(matches)!=1:raise ValueError('Missing/ambiguous receipt artifact')
        artifact=matches[0]
        if type(artifact.get('size_in_bytes')) is not int or not 0<artifact['size_in_bytes']<=65536:raise ValueError('Oversize receipt artifact')
        if artifact.get('workflow_run',{}).get('id')!=run['id']:raise ValueError('Receipt artifact belongs to another run')
        with tempfile.TemporaryDirectory(prefix='ai-publish-receipt-') as directory:
            self.command(['run','download',str(run['id']),'--repo',self.repository,'--name',ARTIFACT,'--dir',directory])
            paths=list(Path(directory).rglob('*'))
            if len(paths)!=1 or paths[0].is_symlink() or not paths[0].is_file() or paths[0].suffix!='.json' or paths[0].stat().st_size>8192:raise ValueError('Receipt artifact must contain one small JSON file only')
            return json.loads(paths[0].read_text())

    def contains_revision(self,ancestor,descendant):
        if ancestor==descendant:return True
        return self.api(f'compare/{full_sha(ancestor)}...{full_sha(descendant)}').get('status') in ('ahead','identical')


class Publisher:
    def __init__(self,config,github=None):
        self.repository=settings(config);self.root=Path(config['state'])/'git-publish'
        self.github=github or GitHub(self.repository)
        binding=dict(schema=1,repository=self.repository,device=config['device'])
        old=read(self.root/'identity.json')
        if old is None:
            if self.root.exists() and any(self.root.iterdir()):raise ValueError('Missing publisher identity; recover existing state explicitly')
            durable_write(self.root/'identity.json',binding)
        elif old!=binding:raise ValueError('Publisher repository/device changed; preserve existing queue')

    def enqueue(self,revision):
        full_sha(revision);path=self.root/'requests'/(revision+'.json')
        if not path.exists():durable_write(path,dict(schema=1,revision=revision,createdAt=now().isoformat(),attempts=[],receipt=None,state='queued'))

    def requests(self):
        result=[]
        for path in sorted((self.root/'requests').glob('*.json')):
            item=read(path)
            if path.is_symlink() or not isinstance(item,dict) or item.get('schema')!=1 or full_sha(item.get('revision'))!=path.stem or not isinstance(item.get('attempts'),list):raise ValueError('Invalid persisted publisher request')
            seen=set()
            for attempt in item['attempts']:
                request_id=attempt.get('requestId','')
                if not re.fullmatch('[a-f0-9]{32}',request_id) or request_id in seen:raise ValueError('Invalid/duplicate persisted dispatch identity')
                seen.add(request_id)
            if item.get('receipt') is not None:
                if not item['attempts'] or item['attempts'][-1].get('state')!='verified':raise ValueError('Receipt has no verified run')
                validate_receipt(item['receipt'],item['attempts'][-1].get('runNumber'))
                if item.get('state')!=item['receipt']['state']:raise ValueError('Persisted receipt state mismatch')
            result.append((path,item))
        return result

    def status(self):
        requests=[r for _,r in self.requests()]
        return dict(pending=sum(r.get('receipt') is None for r in requests),requests=requests)

    def advance(self,path,item):
        if item['receipt'] is not None:return
        attempts=item['attempts'];latest=attempts[-1] if attempts else None
        if latest is None or latest['state'] in ('failed','unverified'):
            latest=dict(requestId=uuid.uuid4().hex,createdAt=now().isoformat(),state='dispatch_unknown')
            attempts.append(latest);item['state']='dispatch_unknown'
            # Persist the attempt ID BEFORE a possibly successful but lost response.
            durable_write(path,item)
            try:
                self.github.dispatch(item['revision'],latest['requestId'])
                latest['state']='accepted';item['state']='accepted'
            except (OSError,ValueError,RuntimeError) as exc:latest['errorType']=type(exc).__name__
            durable_write(path,item);return
        try:run=self.github.find_run(latest['requestId'])
        except (OSError,ValueError,RuntimeError,KeyError) as exc:
            item.update(state='run_unverified',errorType=type(exc).__name__);durable_write(path,item);return
        if run is None:
            from datetime import datetime
            expired=now()-datetime.fromisoformat(latest['createdAt'])>=timedelta(minutes=10)
            if expired:latest['state']='unverified'
            item['state']='run_not_found';durable_write(path,item)
            if expired:self.advance(path,item)
            return
        latest.update(runId=run['id'],runNumber=run['run_number'],runAttempt=run['run_attempt'],runStatus=run['status'],conclusion=run.get('conclusion'))
        if run['status']!='completed':
            item['state']='running';durable_write(path,item);return
        if run.get('conclusion')!='success':
            latest['state']='failed';item['state']='run_failed';durable_write(path,item);return
        try:
            receipt=validate_receipt(self.github.receipt(run),run['run_number'])
            if not self.github.contains_revision(item['revision'],receipt['requestedRevision']):raise ValueError('Workflow receipt does not include the synced revision')
            item['receipt']=receipt;item['state']=receipt['state'];latest['state']='verified'
            item.pop('errorType',None)
        except (OSError,ValueError,RuntimeError,KeyError) as exc:
            latest['state']='unverified';item.update(state='receipt_unverified',errorType=type(exc).__name__)
        durable_write(path,item)

    def retry(self):
        for path,item in self.requests():self.advance(path,item)
        result=self.status();durable_write(self.root/'status.json',result);return result


def daily(config,collect,sync,github=None,retry_only=False):
    """Successful collection is marked independently of sync/dispatch failures."""
    publisher=Publisher(config,github);state=Path(config['state'])
    marker=read(state/'git-publish-daily.json',{})
    period=due_period(now());result=dict(period=period,collection='not_run',sync='not_run')
    if not retry_only:
        if marker.get('collectedPeriod')!=period:
            try:
                collected=collect()
                if collected.get('state')!='ok':raise ValueError('Collection needs attention; do not publish')
                marker.update(collectedPeriod=period,collectedAt=now().isoformat(),collectionBlocked=False)
                durable_write(state/'git-publish-daily.json',marker);result['collection']='collected'
            except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
                result.update(collection='failed',collectionError=type(exc).__name__)
                marker['collectionBlocked']=True;durable_write(state/'git-publish-daily.json',marker)
        else:result['collection']='already_collected'
    # After a crash between successful push and enqueue, idempotent sync recovers
    # the revision on the next invocation without collecting that date again.
    if marker.get('collectedPeriod') and not marker.get('collectionBlocked') and (retry_only or result['collection']!='failed'):
        try:
            synced=sync()
            if synced.get('state')!='ok':raise ValueError('Sync did not establish a published revision')
            full_sha(synced.get('revision'))
            durable_write(state/'sync.json',synced)
            result['sync']=synced
            marker.update(syncedRevision=synced['revision'],syncedAt=now().isoformat())
            durable_write(state/'git-publish-daily.json',marker)
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError,KeyError) as exc:
            result.update(sync='failed',syncError=type(exc).__name__)
            durable_write(state/'sync.json',dict(read(state/'sync.json',{}),state='failed',last_attempt=now().isoformat(),error_type=type(exc).__name__))
        if isinstance(result['sync'],dict):
            try:publisher.enqueue(synced['revision']);result['queue']='queued'
            except (OSError,ValueError,RuntimeError) as exc:result.update(queue='failed',queueError=type(exc).__name__)
    if retry_only and not marker.get('collectedPeriod'):
        previous=read(state/'sync.json',{})
        if previous.get('state')=='ok' and previous.get('revision'):publisher.enqueue(previous['revision'])
    result['publisher']=publisher.retry()
    durable_write(state/'git-publish-status.json',result)
    return result
