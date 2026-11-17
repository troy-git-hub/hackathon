"""Bounded SSE relay; credentials and upstream errors remain server-side."""
import asyncio
import json
import os
from urllib.parse import urlsplit
import httpx
from fastapi.responses import StreamingResponse


def frame(event, data):
    return 'event: '+event+'\ndata: '+json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n\n'


def model_body(task, context):
    prefix='ECHO_VISION' if task=='vision' else 'ECHO_TEXT'
    origin=os.environ.get(prefix+'_ORIGIN','')
    key=os.environ.get(prefix+'_KEY','')
    model=os.environ.get(prefix+'_MODEL','')
    if not origin.startswith('https://') or not key or not model:
        raise ValueError('账户模型服务尚未配置。')
    body=dict(model=model,messages=context['messages'],max_tokens=context.get('max_tokens',1200),
              temperature=context.get('temperature',0.3),stream=True,stream_options={'include_usage':True})
    if task=='vision' and model.startswith('qwen3-vl') and urlsplit(origin).hostname in ('dashscope.aliyuncs.com','dashscope-intl.aliyuncs.com'):
        body['enable_thinking']=False
    if context.get('response_format')=={'type':'json_object'}:
        body['response_format']=context['response_format']
    if urlsplit(origin).hostname=='api.deepseek.com':
        level=context.get('reasoning_effort','low')
        body['thinking']={'type':'disabled' if level=='none' else 'enabled'}
        if level!='none':body['reasoning_effort']=level
    return origin,key,body


async def upstream(task, context):
    origin,key,body=model_body(task,context)
    size=0;finished=False;done=False
    async with httpx.AsyncClient(timeout=httpx.Timeout(60,connect=10)) as client:
        async with client.stream('POST',origin.rstrip('/')+'/chat/completions',
                                 headers={'Authorization':'Bearer '+key},json=body) as reply:
            if reply.status_code!=200:raise ValueError('账户模型暂时不可用，请稍后重试。')
            async for line in reply.aiter_lines():
                size+=len(line.encode('utf-8'))
                if size>2*1024*1024:raise ValueError('模型返回内容过大。')
                if not line.startswith('data:'):continue
                raw=line[5:].strip()
                if raw=='[DONE]':done=True;break
                if not raw:continue
                item=json.loads(raw)
                if item.get('error'):raise ValueError('模型生成未完成，请重试。')
                if isinstance(item.get('usage'),dict):yield 'usage',item['usage']
                for choice in item.get('choices',[])[:1]:
                    delta=choice.get('delta') or {}
                    for field,event in [('reasoning_content','reasoning'),('content','delta')]:
                        value=delta.get(field)
                        if isinstance(value,str) and value:yield event,{'text':value}
                    if choice.get('finish_reason'):
                        finished=True
                        yield 'finish',{'reason':choice['finish_reason']}
    if not done and not finished:raise ValueError('模型连接中断，请重试。')


def response(core,user,ident,task,context,protocol):
    async def events():
        settled=False;parts=[];reasoning=[];usage={};finish='stop'
        try:
            yield frame('ready',{'request_id':ident})
            async with asyncio.timeout(90):
                async for event,data in upstream(task,context):
                    if event=='usage':usage=data
                    elif event=='finish':finish=data['reason']
                    else:
                        (parts if event=='delta' else reasoning).append(data['text'])
                        yield frame(event,data)
            text=''.join(parts)
            if not text.strip():raise ValueError('模型未返回答案，请缩短问题或关闭思考后重试。')
            result={'text':text,'finish_reason':finish,'usage':usage}
            # Count reasoning output too when an upstream omits its usage receipt.
            estimate=dict(result,text=''.join(reasoning)+text)
            with core['db'](True) as c:
                receipt=core['billing'].settle(c,core,user['id'],ident,estimate,context)
                encoded=core['seal'](json.dumps(result,ensure_ascii=False),'result:'+user['id']+':'+ident)
                c.execute("UPDATE inference_requests SET state='succeeded',result=?,finished=? WHERE user_id=? AND request_id=? AND state='pending'",(encoded,core['now'](),user['id'],ident))
                core['audit'](c,user['id'],'ai-request',{'request_id':ident,'task':task,**receipt})
                row=c.execute('SELECT * FROM inference_requests WHERE user_id=? AND request_id=?',(user['id'],ident)).fetchone()
                reply=core['inference_reply'](c,row,protocol)
            settled=True
            yield frame('done',reply)
        except asyncio.CancelledError:
            raise
        except Exception:
            yield frame('error',{'detail':'生成未完成，学习点已返还。请重试；图片请求请检查账户视觉模型配置。'})
        finally:
            if not settled:
                with core['db'](True) as c:core['refund_inference'](c,user['id'],ident,'流式生成中断，学习点已返还。')
    return StreamingResponse(events(),media_type='text/event-stream',
                             headers={'X-Accel-Buffering':'no','Cache-Control':'no-store'})
