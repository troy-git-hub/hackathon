"""Token accounting in integer milli-points. Provider keys never leave the server."""
import json,math
from decimal import Decimal,InvalidOperation

SCALE=1000
PURPOSES={'assistant':'通用辅助','blackboard':'AI 黑板','quiz':'出题','grading':'答案批改','classroom':'听课知识分析','catchup':'补课讲解','qa':'课堂答疑','review':'复习','summary':'课堂总结','persona':'学习画像','booklet':'复习小册','problem_solving':'做题解析','vision':'截图识别','web_practice':'网页练习出题'}
PURPOSES.update(material_parse='资料与试卷解析',daily_quiz='每日小题生成',exam_generate='整卷考试出题',exam_grading='整卷答案批改')
def points(units):return int(units)/SCALE
def units(value):
    try:
        number=Decimal(str(value))
        if not number.is_finite() or number*SCALE!=(number*SCALE).to_integral_value():raise ValueError()
        return int(number*SCALE)
    except (InvalidOperation,ValueError,TypeError):raise ValueError('学习点最多保留三位小数。')
def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS billing_settings(key TEXT PRIMARY KEY,value INTEGER NOT NULL)')
    if not c.execute("SELECT 1 FROM billing_settings WHERE key='milli_points_v1'").fetchone():
        # Each pre-existing integer point becomes 1000 integer units exactly once.
        for table,column in [('users','balance'),('ledger','amount'),('invitations','credits'),('inference_requests','cost')]:c.execute('UPDATE '+table+' SET '+column+'='+column+'*1000')
        c.execute("INSERT INTO billing_settings VALUES('milli_points_v1',1)")
    c.execute("INSERT OR IGNORE INTO billing_settings VALUES('input_rate',100)")
    c.execute("INSERT OR IGNORE INTO billing_settings VALUES('output_rate',200)")
def pricing(c):
    rates=dict(c.execute("SELECT key,value FROM billing_settings WHERE key IN ('input_rate','output_rate')").fetchall())
    return {'input_rate':rates.get('input_rate',100),'output_rate':rates.get('output_rate',200)}
def public_pricing(c):
    rates=pricing(c)
    return {'mode':'tokens','input_points_per_1000':points(rates['input_rate']),'output_points_per_1000':points(rates['output_rate']),'precision':3,'usage_fallback':'estimated','minimum_charge':0.001}
def cost(rates,input_tokens,output_tokens):return max(1,math.ceil((input_tokens*rates['input_rate']+output_tokens*rates['output_rate'])/1000))
def estimate_input(context):
    size=0
    for message in context.get('messages',[]):
        content=message.get('content','')
        if isinstance(content,str):size+=len(content.encode('utf-8'))
        elif isinstance(content,list):
            for item in content:
                if isinstance(item,dict):
                    if item.get('type')=='text':size+=len(str(item.get('text','')).encode('utf-8'))
                    elif item.get('type')=='image_url':size+=12288
    return max(1,size+64*len(context.get('messages',[])))
def usage(result,context):
    raw=result.get('usage')
    if isinstance(raw,dict):
        incoming=raw.get('prompt_tokens',raw.get('input_tokens'));outgoing=raw.get('completion_tokens',raw.get('output_tokens'))
        if type(incoming)==int and type(outgoing)==int and 0<=incoming<=2_000_000 and 0<=outgoing<=100_000 and incoming+outgoing>0:return incoming,outgoing,'provider'
    return estimate_input(context),max(1,math.ceil(len(str(result.get('text','')).encode('utf-8'))/3)),'estimated'
def reserve(c,core,user,ident,request_hash,task,purpose,context):
    rates=pricing(c);incoming=estimate_input(context);context=dict(context);maximum=context.get('max_tokens',1200)
    available=c.execute('SELECT balance FROM users WHERE id=? AND disabled=0 AND ai_enabled=1',(user['id'],)).fetchone()
    if not available:core['fail'](403,'账户 AI 服务未开通。')
    balance=available['balance'];minimum=cost(rates,incoming,32)
    if balance<minimum:core['fail'](402,'学习点不足以预留本次 token 预算。请缩短输入或领取学习点后重试。')
    affordable=max(32,int((balance*1000-incoming*rates['input_rate'])/rates['output_rate']))
    context['max_tokens']=min(maximum,affordable)
    held=cost(rates,incoming,context['max_tokens'])
    if c.execute('UPDATE users SET balance=balance-? WHERE id=? AND balance>=?',(held,user['id'],held)).rowcount!=1:core['fail'](402,'学习点不足。')
    prefix='ECHO_VISION' if task=='vision' else 'ECHO_TEXT'
    import os
    c.execute("INSERT INTO inference_requests(user_id,request_id,request_hash,task,state,cost,created,purpose,model,api_origin,input_rate,output_rate) VALUES(?,?,?,?,'pending',?,?,?,?,?,?,?)",(user['id'],ident,request_hash,task,held,core['now'](),purpose,os.environ.get(prefix+'_MODEL',''),os.environ.get(prefix+'_ORIGIN',''),rates['input_rate'],rates['output_rate']))
    core['audit'](c,user['id'],'ai-request-started',{'request_id':ident,'purpose':purpose})
    c.execute('INSERT INTO ledger(user_id,amount,note,created,reference) VALUES(?,?,?,?,?)',(user['id'],-held,PURPOSES[purpose]+' · token 预算预留',core['now'](),'inference:'+user['id']+':'+ident))
    return context
def settle(c,core,uid,ident,result,context):
    row=c.execute('SELECT * FROM inference_requests WHERE user_id=? AND request_id=?',(uid,ident)).fetchone()
    if not row or row['state']!='pending':core['fail'](409,'此请求已结算。')
    incoming,outgoing,source=usage(result,context);actual=cost({'input_rate':row['input_rate'],'output_rate':row['output_rate']},incoming,outgoing)
    adjustment=row['cost']-actual
    if c.execute('UPDATE users SET balance=balance+? WHERE id=? AND balance+?>=0',(adjustment,uid,adjustment)).rowcount!=1:core['fail'](402,'实际 token 用量超出可用额度，本次未返回模型结果并返还预留。')
    if adjustment:c.execute('INSERT INTO ledger(user_id,amount,note,created,reference) VALUES(?,?,?,?,?)',(uid,adjustment,PURPOSES.get(row['purpose'],'AI')+' · token 用量结算',core['now'](),'inference-settle:'+uid+':'+ident))
    c.execute('UPDATE inference_requests SET cost=?,input_tokens=?,output_tokens=?,usage_source=? WHERE user_id=? AND request_id=?',(actual,incoming,outgoing,source,uid,ident))
    return {'input_tokens':incoming,'output_tokens':outgoing,'total_tokens':incoming+outgoing,'usage_source':source,'charged_points':points(actual)}
