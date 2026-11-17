"""Echo account adapter around the user's Qingjuan paper prompts and renderer."""
import copy,json,re,uuid
from fastapi import Request,Response
import billing,storage,qingjuan_prompts

def clean_text(value,limit=4000):
    if not isinstance(value,str) or len(value)>limit:raise ValueError('清卷文字格式或长度无效。')
    return value.strip()

def normalize(raw):
    if not isinstance(raw,dict) or not isinstance(raw.get('meta'),dict) or not isinstance(raw.get('sections'),list):raise ValueError('请导入清卷格式JSON（meta与sections）。')
    meta=raw['meta'];paper={'meta':{k:clean_text(meta.get(k,''),200) for k in ('title','subtitle','school','subject','grade','term')},'sections':[]}
    if not paper['meta']['title']:raise ValueError('试卷标题不能为空。')
    duration=meta.get('duration',30)
    if type(duration)!=int or not 5<=duration<=120:raise ValueError('考试时长须为5至120分钟。')
    paper['meta']['duration']=duration
    if not 1<=len(raw['sections'])<=12:raise ValueError('试卷须含1至12个大题。')
    counter=[0]
    def question(q,depth=0):
        if not isinstance(q,dict) or depth>1:raise ValueError('子题结构无效。')
        kind=q.get('type','short')
        if kind not in qingjuan_prompts.TYPE_NAMES:raise ValueError('清卷题型无效。')
        children=q.get('questions',[])
        if not isinstance(children,list) or len(children)>20:raise ValueError('子题数量超限。')
        result={'id':clean_text(str(q.get('id') or uuid.uuid4().hex),80),'type':kind,'stem':clean_text(q.get('stem',''),4000),
                'answer':clean_text(str(q.get('answer','')),4000),'analysis':clean_text(str(q.get('analysis','')),4000),
                'knowledge':clean_text(str(q.get('knowledge','综合复习')),120),'passage':clean_text(q.get('passage',''),12000),
                'passage_title':clean_text(q.get('passage_title',''),200),'passage_author':clean_text(q.get('passage_author',''),100),
                'answer_space':min(12,max(0,int(q.get('answer_space') or 0)))}
        if not result['stem']:raise ValueError('题干不能为空。')
        options=q.get('options',[])
        if not isinstance(options,list) or len(options)>8:raise ValueError('选项格式无效。')
        result['options']=[clean_text(v,1200) for v in options]
        if kind in ('choice','multi'):
            if not 2<=len(options)<=8:raise ValueError('选择题须有2至8个选项。')
            answer=re.sub(r'[\s,，、.．]','',result['answer']).upper()
            if not answer or any(c not in 'ABCDEFGH'[:len(options)] for c in answer) or kind=='choice' and len(answer)!=1:raise ValueError('选项答案与题目不一致。')
            result['answer']=answer
        if kind=='tf' and result['answer'].lower() not in ('正确','错误','对','错','true','false','√','×','t','f','a','b'):raise ValueError('判断题答案无效。')
        if kind in ('reading','cloze') and not children:raise ValueError('阅读或完形题必须包含完整子题。')
        if not children and (not result['answer'] or not result['analysis']):raise ValueError('每道完整试题需要答案与解析。')
        score=q.get('score',1)
        if type(score) not in (int,float) or not 0<score<=150:raise ValueError('题目分值无效。')
        result['score']=score
        fig=q.get('figure')
        if fig is not None:
            if not isinstance(fig,dict) or len(json.dumps(fig))>60000:raise ValueError('图形过大或格式无效。')
            if fig.get('kind') not in ('geometry','rays','coord','numberline','bar','pie','svg','image'):raise ValueError('图形类型无效。')
            if fig.get('kind')=='image' and not re.fullmatch(r'data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+',str(fig.get('src',''))):raise ValueError('配图仅允许内嵌PNG/JPEG，不读取外部链接。')
            result['figure']=copy.deepcopy(fig)
        if children:
            result['questions']=[question(c,depth+1) for c in children]
            result['score']=sum(c['score'] for c in result['questions'])
        else:
            counter[0]+=1
            if counter[0]>60:raise ValueError('线上清卷最多60道实际作答小题。')
        req=q.get('requirements',[])
        if not isinstance(req,list) or len(req)>10:raise ValueError('写作要求格式无效。')
        result['requirements']=[clean_text(v,1000) for v in req]
        if kind=='essay':result['grid']={'chars':min(1500,max(100,int((q.get('grid') or {}).get('chars',600))))}
        return result
    for section in raw['sections']:
        if not isinstance(section,dict):raise ValueError('大题格式无效。')
        items=section.get('questions')
        if not isinstance(items,list) or not items:raise ValueError('大题不能是空题。')
        paper['sections'].append({'title':clean_text(section.get('title',''),200),'instruction':clean_text(section.get('instruction',''),1000),
                                  'type':section.get('type','short'),'questions':[question(q) for q in items]})
    if not counter[0]:raise ValueError('没有可作答的小题。')
    paper['meta']['total_score']=sum(q['score'] for s in paper['sections'] for q in s['questions'])
    json.dumps(paper,allow_nan=False)
    return paper

def convert(paper,pid):
    out=[]
    def add(q,parent=None):
        if q.get('questions'):
            for child in q['questions']:add(child,q)
            return
        kind=q['type'];mapping={'choice':'single_choice','multi':'multiple_choice','tf':'true_false','fill':'fill_blank'}
        answer=q['answer'];options=q['options']
        if kind=='choice':answer=ord(answer)-65
        elif kind=='multi':answer=sorted(set(ord(c)-65 for c in answer))
        elif kind=='tf':options=['正确','错误'];answer=0 if answer.strip().lower() in ('正确','对','true','√','t','a') else 1
        context=(parent or {}).get('passage') or q.get('passage','')
        stem=((parent or {}).get('stem','')+'\n' if parent else '')+(context+'\n\n' if context else '')+q['stem']
        item={'type':mapping.get(kind,'short_answer'),'question':stem,'options':options,'answer':answer,'explanation':q['analysis'],
              'topic':q['knowledge'],'source_ids':[pid],'source_label':'清卷 · '+paper['meta']['title'],'qingjuan_score':q['score']}
        figure=q.get('figure') or (parent or {}).get('figure')
        if figure:item['figure']=figure
        out.append(item)
    for section in paper['sections']:
        for q in section['questions']:add(q)
    return out

def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS qingjuan_papers(user_id TEXT NOT NULL REFERENCES users(id),id TEXT NOT NULL,title TEXT NOT NULL,size INTEGER NOT NULL,cipher TEXT NOT NULL,created INTEGER NOT NULL,updated INTEGER NOT NULL,PRIMARY KEY(user_id,id))')

def install(app,core):
    db,auth,fail,payload,now=(core[k] for k in ('db','session_user','fail','payload','now'))
    services=core['study_services'];encode,decode=services['encode'],services['decode']
    def rid(value):
        try:return uuid.UUID(value).hex
        except (ValueError,TypeError,AttributeError):fail(400,'请使用有效的请求编号。')
    def load(c,uid,pid):
        row=c.execute('SELECT * FROM qingjuan_papers WHERE user_id=? AND id=?',(uid,pid)).fetchone()
        if not row:fail(404,'清卷试卷不存在或无权访问。')
        return row,decode(row['cipher'],'qingjuan:'+uid+':'+pid)
    def save(c,uid,pid,paper):
        size=len(json.dumps(paper,ensure_ascii=False).encode());old=c.execute('SELECT size FROM qingjuan_papers WHERE user_id=? AND id=?',(uid,pid)).fetchone()
        if size>512*1024:fail(413,'清卷试卷最多512KiB，请减少图片或题量。')
        if storage.used(c)-(old['size'] if old else 0)+size>storage.LIMIT:fail(409,'云端128 MiB存储额度已满。')
        if not old and c.execute('SELECT count(*) FROM qingjuan_papers WHERE user_id=?',(uid,)).fetchone()[0]>=40:fail(409,'最多保存40张清卷试卷，请删除旧卷。')
        services['room'](size)
        c.execute('INSERT INTO qingjuan_papers VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,id) DO UPDATE SET title=excluded.title,size=excluded.size,cipher=excluded.cipher,updated=excluded.updated',
                  (uid,pid,paper['meta']['title'],size,encode(paper,'qingjuan:'+uid+':'+pid),now(),now()))
    @app.get('/v1/me/qingjuan/papers')
    def papers(request:Request):
        uid=auth(request)['id']
        with db() as c:items=[dict(r) for r in c.execute('SELECT id,title,size,created,updated FROM qingjuan_papers WHERE user_id=? ORDER BY updated DESC',(uid,))]
        return {'items':items,'name':'清卷','storage_limit_bytes':storage.LIMIT}
    @app.get('/v1/me/qingjuan/papers/{pid}')
    def get(request:Request,pid:str):
        uid=auth(request)['id']
        with db() as c:row,paper=load(c,uid,pid)
        return {'id':pid,'paper':paper,'updated':row['updated']}
    @app.post('/v1/me/qingjuan/papers')
    async def store(request:Request):
        uid=auth(request)['id'];data=await payload(request);pid=rid(data.get('id') or data.get('request_id'))
        try:paper=normalize(data.get('paper'))
        except (ValueError,TypeError,KeyError,OverflowError,AttributeError) as exc:fail(400,str(exc)[:180])
        with db(True) as c:save(c,uid,pid,paper)
        return {'id':pid,'paper':paper}
    @app.delete('/v1/me/qingjuan/papers/{pid}')
    def remove(request:Request,pid:str):
        uid=auth(request)['id']
        with db(True) as c:load(c,uid,pid);c.execute('DELETE FROM qingjuan_papers WHERE user_id=? AND id=?',(uid,pid))
        return {'ok':True}
    @app.post('/v1/me/qingjuan/generate')
    async def generate(request:Request):
        user=auth(request);data=await payload(request);pid=rid(data.get('request_id'))
        with db() as c:
            if c.execute('SELECT 1 FROM qingjuan_papers WHERE user_id=? AND id=?',(user['id'],pid)).fetchone():return get(request,pid)
        try:
            cfg={key:clean_text(data.get(key,default),maximum) for key,default,maximum in [('subject','数学',30),('grade','初中二年级',40),('title','清卷 · 专项练习',120),('knowledge','',1500)]}
            count=data.get('count',10);duration=data.get('duration',30)
            if type(count)!=int or count not in (5,10,15,20) or type(duration)!=int or not 5<=duration<=120:raise ValueError('题量或时长无效。')
            if not cfg['knowledge']:raise ValueError('请填写知识点或范围，避免随意出卷。')
        except (ValueError,TypeError) as exc:fail(400,str(exc))
        prompt=qingjuan_prompts.SYSTEM+'\n'+qingjuan_prompts.scope_rule({**cfg,'paper_scope':'special'})
        prompt+='\n输出完整JSON {"meta":{"title":"标题","subject":"学科","grade":"年级","duration":30},"sections":[{"title":"大题","type":"choice","questions":[题目对象]}]}。所有非阅读题必须给answer/analysis。只按指定知识点命题，恰好'+str(count)+'道独立作答小题。题干每题最多150字、解析每题最多100字，使用结构化配图，严禁外链图片。'
        context={'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps(cfg,ensure_ascii=False)}],'max_tokens':min(8500,800+count*360),'temperature':0.35}
        def validate(raw):
            paper=normalize(raw)
            if len(convert(paper,pid))!=count:raise ValueError('出题数量不符。')
            paper['meta'].update(title=cfg['title'],subject=cfg['subject'],grade=cfg['grade'],duration=duration)
            return {'paper':paper}
        await services['ai'](user,pid,'qingjuan_generate','text',context,'qingjuan:'+json.dumps({**cfg,'count':count,'duration':duration},sort_keys=True),validate,lambda c,v:save(c,user['id'],pid,v['paper']))
        return get(request,pid)
    @app.post('/v1/me/qingjuan/papers/{pid}/start')
    async def start(request:Request,pid:str):
        uid=auth(request)['id'];data=await payload(request);aid=rid(data.get('request_id'));anti=data.get('anti_cheat',False)
        if type(anti)!=bool:fail(400,'专注模式开关无效。')
        with db(True) as c:
            _,paper=load(c,uid,pid)
            old=c.execute('SELECT id FROM study_attempts WHERE user_id=? AND id=?',(uid,aid)).fetchone()
            if old:
                previous=services['attempt'](c,uid,aid)
                if previous.get('qingjuan_id')!=pid:fail(409,'该请求编号已用于另一场考试，请刷新后重试。')
                return services['public'](previous)
            questions=convert(paper,pid)
            record=services['create_paper'](c,uid,aid,'exam',paper['meta']['title'],questions,paper['meta']['duration'],anti)
            total=sum(q['qingjuan_score'] for q in record['questions'])
            for q in record['questions']:q['points']=100*q['qingjuan_score']/total
            record['qingjuan_id']=pid;services['put_attempt'](c,uid,record)
        return services['public'](record)
