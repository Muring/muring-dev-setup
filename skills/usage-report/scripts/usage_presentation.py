"""Optional public task presentation. Contract: mublog taskPresentationSchema."""
import calendar
import copy
import re


def validate(value):
    def obj(v, fields, where):
        if not isinstance(v, dict) or set(v) != set(fields):
            raise ValueError(f'presentation {where}: unexpected or missing fields')
    def text(v, limit, where):
        if not isinstance(v, str) or len(v.encode('utf-16-le', errors='surrogatepass')) // 2 > limit:
            raise ValueError(f'presentation {where}: expected text <= {limit}')
    def enum(v, options, where):
        if not isinstance(v, str) or v not in options:
            raise ValueError(f'presentation {where}: invalid enum')
    obj(value, ('title','summary','occurredAt','checks','followUps','knowledge','evidence'), 'root')
    text(value['title'],300,'title'); text(value['summary'],2000,'summary')
    date=value['occurredAt']
    if date is not None:
        match=re.fullmatch(r'([0-9]{4})-([0-9]{2})-([0-9]{2})T([01][0-9]|2[0-3]):([0-5][0-9])(?::[0-5][0-9](?:\.[0-9]+)?)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])',date) if isinstance(date,str) else None
        if not match or not 1 <= int(match[2]) <= 12 or not 1 <= int(match[3]) <= calendar.monthrange(int(match[1]),int(match[2]))[1]:
            raise ValueError('presentation occurredAt: expected ISO datetime with offset or null')
    for field in ('checks','followUps','knowledge','evidence'):
        if not isinstance(value[field],list):raise ValueError(f'presentation {field}: expected array')
    for c in value['checks']:
        obj(c,('title','method','result','reason'),'checks')
        text(c['title'],300,'check title');text(c['method'],1000,'method')
        enum(c['result'],('pass','fail','not_run','unknown'),'result')
        if c['reason'] is not None:text(c['reason'],1000,'reason')
    for c in value['followUps']:
        obj(c,('title','status','note'),'followUps')
        text(c['title'],300,'followUp title');text(c['note'],1000,'note')
        enum(c['status'],('pending','delegated','unknown'),'followUp status')
    for c in value['knowledge']:
        obj(c,('document','usage','note'),'knowledge')
        text(c['document'],300,'document');text(c['note'],1000,'note')
        enum(c['usage'],('reference','applied'),'knowledge usage')
    for e in value['evidence']:text(e,1000,'evidence')
    return copy.deepcopy(value)


def merge(tasks, conflicts, directory, read, digest):
    for key, task in tasks.items():
        if 'presentation' in task:
            task['presentation']=validate(task['presentation'])
            if key in conflicts:raise ValueError('presentation target has conflicting task records')
    if directory.is_symlink():raise ValueError('presentation supplement directory must not be a symlink')
    records=[]
    for path in sorted(directory.glob('*.json')):
        if path.is_symlink():raise ValueError('presentation supplement must not be a symlink')
        records.append((path.name, read(path)))
    merge_supplements(tasks, conflicts, records, digest)


def merge_supplements(tasks, conflicts, records, digest):
    for name, data in records:
        if not isinstance(data,dict) or set(data)!={'project','id','presentation'} or not all(isinstance(data[k],str) and data[k] for k in ('project','id')):
            raise ValueError(f'presentation supplement invalid wrapper: {name}')
        key=digest([data['project'],data['id']])
        if name != key+'.json':raise ValueError(f'presentation supplement filename mismatch: {name}')
        if key not in tasks:raise ValueError(f'presentation supplement target missing: {name}')
        if key in conflicts:raise ValueError(f'presentation supplement target conflict: {name}')
        p=validate(data['presentation']);task=tasks[key]
        if 'presentation' in task and task['presentation']!=p:
            raise ValueError(f'presentation native/supplement conflict: {name}')
        task['presentation']=p
