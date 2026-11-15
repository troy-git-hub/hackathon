"""Bounded question schema, server grading and Beijing calendar planning."""
import math
import unicodedata
from datetime import datetime,timedelta,timezone

TZ=timezone(timedelta(hours=8))
DEFAULTS={'daily_count':3,'exam_enabled':True,'exam_weekday':6,'exam_hour':20,'exam_minute':0,
          'exam_count':10,'exam_duration':30,'anti_cheat':False}
LIMITS={'max_file_bytes':3*1024*1024,'max_image_bytes':1024*1024,'max_files':10,
        'user_storage_bytes':10*1024*1024,'global_storage_bytes':40*1024*1024,
        'max_text_chars':30000,'max_analysis_questions':20,'analysis_scope_chars':12000,'max_pdf_pages':20,'max_sources':12,'max_attempts':200,
        'max_bank_questions':600,'ai_requests_per_day':15,'timezone':'Asia/Shanghai',
        'formats':['pdf','txt','md','docx','png','jpg','jpeg']}

def text(value,limit,required=False):
    if not isinstance(value,str) or len(value)>limit or required and not value.strip():raise ValueError('文本内容为空或过长。')
    return value.strip()

def preferences(data):
    result=dict(DEFAULTS)
    if not isinstance(data,dict) or set(data)-set(result):raise ValueError('学习计划设置字段无效。')
    for key,value in data.items():
        if key in ('exam_enabled','anti_cheat'):
            if type(value)!=bool:raise ValueError('计划开关无效。')
        else:
            ranges={'daily_count':(1,5),'exam_weekday':(0,6),'exam_hour':(0,23),'exam_minute':(0,59),'exam_count':(5,20),'exam_duration':(5,120)}
            lo,hi=ranges[key]
            if type(value)!=int or not lo<=value<=hi:raise ValueError('计划时间或题量超出范围。')
            if key=='exam_count' and value not in (5,10,15,20):raise ValueError('考试题量须为5、10、15或20题。')
        result[key]=value
    return result

def plan(pref,stamp,last_exam=0):
    date=datetime.fromtimestamp(stamp,TZ)
    scheduled=date.replace(hour=pref['exam_hour'],minute=pref['exam_minute'],second=0,microsecond=0)
    scheduled-=timedelta(days=(date.weekday()-pref['exam_weekday'])%7)
    due=pref['exam_enabled'] and scheduled.timestamp()<=stamp and last_exam<scheduled.timestamp()
    next_date=scheduled if due or scheduled.timestamp()>stamp else scheduled+timedelta(days=7)
    return {'timezone':'Asia/Shanghai','daily_day':date.date().isoformat(),'exam_due':bool(due),
            'scheduled_at':int(scheduled.timestamp()),'next_exam_at':int(next_date.timestamp()) if pref['exam_enabled'] else None}

def question(raw,allowed_sources):
    if not isinstance(raw,dict):raise ValueError('题目格式无效。')
    kind=raw.get('type');options=raw.get('options',[]);answer=raw.get('answer')
    if kind not in ('single_choice','multiple_choice','true_false','fill_blank','short_answer'):raise ValueError('题型不受支持。')
    if kind=='true_false':options=['正确','错误']
    if not isinstance(options,list) or len(options)>8:raise ValueError('选项格式无效。')
    options=[text(v,800,True) for v in options]
    if kind in ('single_choice','multiple_choice','true_false'):
        if not 2<=len(options)<=8:raise ValueError('选择题需要2至8个选项。')
        if kind=='multiple_choice':
            if not isinstance(answer,list) or not answer or any(type(a)!=int or not 0<=a<len(options) for a in answer) or len(set(answer))!=len(answer):raise ValueError('多选答案无效。')
            answer=sorted(answer)
        elif type(answer)!=int or not 0<=answer<len(options):raise ValueError('选择题答案必须是选项下标。')
    else:
        answer=text(answer,1600,True);options=[]
    sources=raw.get('source_ids')
    if not isinstance(sources,list) or not sources or any(not isinstance(s,str) or s not in allowed_sources for s in sources):raise ValueError('题目缺少有效来源。')
    return {'type':kind,'question':text(raw.get('question'),2400,True),'options':options,'answer':answer,
            'explanation':text(raw.get('explanation'),2400,True),'topic':text(raw.get('topic','综合复习'),120) or '综合复习',
            'source_ids':list(dict.fromkeys(sources)), 'answer_source':raw.get('answer_source') if raw.get('answer_source') in ('provided','inferred') else 'inferred'}

def clean_answer(q,value):
    if value is None or value=='':return None
    if q['type']=='multiple_choice':
        if not isinstance(value,list) or len(value)>len(q['options']) or any(type(a)!=int or not 0<=a<len(q['options']) for a in value) or len(set(value))!=len(value):raise ValueError('多选答案无效。')
        return sorted(value)
    if q['type'] in ('single_choice','true_false'):
        if type(value)!=int or not 0<=value<len(q['options']):raise ValueError('请选择有效选项。')
        return value
    return text(value,4000)

def grade(q,value):
    if value is None or value=='' or value==[]:return {'status':'unanswered','score':0,'feedback':'未作答'}
    if q['type']=='short_answer':return {'status':'pending','score':None,'feedback':'主观题待批改，可手动调用AI批改。'}
    if q['type']=='fill_blank':
        normal=lambda v:''.join(unicodedata.normalize('NFKC',v).casefold().split())
        if normal(value)!=normal(q['answer']):return {'status':'pending','score':None,'feedback':'与参考文字不同，保留待批改，避免误判。'}
        correct=True
    else:correct=value==q['answer']
    return {'status':'correct' if correct else 'incorrect','score':int(correct),'feedback':'答对了' if correct else '请对照参考答案与解析复习。'}

def report(questions,answers,previous=None):
    result={q['id']:dict((previous or {}).get(q['id']) or grade(q,answers.get(q['id']))) for q in questions}
    score=round(sum((result[q['id']]['score'] or 0)*q['points'] for q in questions),2)
    pending=sum(v['status']=='pending' for v in result.values())
    return result,score,pending
