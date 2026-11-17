"""Adapts Echo's account protocol to existing local model call sites; no provider key ships."""
from types import SimpleNamespace
from echo.backend import account

class _AccountStream:
    def __init__(self,events):self.events=events;self.closed=False
    def __iter__(self):
        try:
            for event,data in self.events:
                if self.closed:break
                if event in ('delta','reasoning'):
                    yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                        content=data['text'] if event=='delta' else None,
                        reasoning_content=data['text'] if event=='reasoning' else None))])
        finally:self.close()
    def close(self):
        self.closed=True
        self.events.close()

class EchoModelClient:
    def __init__(self):self.chat=SimpleNamespace(completions=self)
    def create(self,*,model,messages,max_tokens=1200,temperature=0.3,stream=False,response_format=None,**kwargs):
        if model not in ('echo-text','echo-vision'):raise account.AccountError('未知的 Echo 模型任务。')
        context={'messages':messages,'max_tokens':max_tokens,'temperature':temperature}
        if response_format is not None:context['response_format']=response_format
        extra=kwargs.get('extra_body') or {}
        purpose=extra.get('echo_purpose') if isinstance(extra,dict) else None
        task='vision' if model=='echo-vision' else 'text'
        if stream:
            import os
            context['reasoning_effort']=os.getenv('ECHO_REASONING_EFFORT','low')
            return _AccountStream(account.inference_stream(task,context,purpose=purpose))
        result=account.inference(task,context,purpose=purpose)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=result['text']),finish_reason=result.get('finish_reason','stop'))],usage=result.get('usage',{}))
