"""Bounded classroom retrospectives, with explicit fields and credential redaction."""
import hashlib,json,re,math
from datetime import datetime,timezone
from echo.backend import store

def text(value,limit):
    value=str(value or '')
    value=re.sub(r'(?:ghp_|cfat_|sk-)[A-Za-z0-9_-]{12,}','[已隐藏凭证]',value)
    value=re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----','[已隐藏私钥]',value,flags=re.S)
    return value[:limit]
def build(exclude_cloud=False):
    lessons=[]
    items=store.list_lessons()
    if exclude_cloud:items=[v for v in items if not v.get('_cloud_imported')]
    for item in items[:50]:
        stamp=item.get('time',0)
        if type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp<=0:continue
        skills=[]
        for skill in (item.get('skills_detail') or [])[:30]:
            if not isinstance(skill,dict):continue
            mastery=skill.get('mastery')
            skills.append({'name':text(skill.get('name'),100),'status':text(skill.get('status'),20),'mastery':mastery if type(mastery) in (int,float) and math.isfinite(mastery) and 0<=mastery<=1 else None})
        notes=[]
        for board in (item.get('blackboards') or [])[-8:]:
            if isinstance(board,dict):
                for key in ('title','summary','content','text'):
                    if isinstance(board.get(key),str):notes.append(text(board[key],500))
        record={'id':'lesson_'+hashlib.sha256(str(stamp).encode()).hexdigest()[:24],'title':text(item.get('title'),200),'ended_at':datetime.fromtimestamp(stamp,timezone.utc).isoformat(),'duration_seconds':min(86400,max(0,float(item.get('duration') or 0))),'summary':text(item.get('summary'),1600),'suggestion':text(item.get('suggestion'),400),'highlights':[text(v,160) for v in (item.get('highlights') or [])[:5]],'skills':skills,'blackboard_notes':'\n'.join(notes)[:1600],'truncated':False}
        # Keep every retained lesson's index; shorten prose instead of losing old titles.
        while len(json.dumps(record,ensure_ascii=False).encode())>8192:
            record['truncated']=True
            if len(record['blackboard_notes'])>200:record['blackboard_notes']=record['blackboard_notes'][:len(record['blackboard_notes'])//2]
            elif len(record['summary'])>300:record['summary']=record['summary'][:len(record['summary'])//2]
            elif len(record['skills'])>5:record['skills']=record['skills'][:len(record['skills'])//2]
            else:break
        lessons.append(record)
    return {'protocol':'echo.classroom/1','lessons':lessons}
