"""Adapts Echo's account protocol to existing local model call sites; no provider key ships."""
from types import SimpleNamespace
from echo.backend import account

class _SingleResultStream:
    def __init__(self,text):self.text=text;self.closed=False
    def __iter__(self):
        if not self.closed:yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=self.text))])
    def close(self):self.closed=True

class EchoModelClient:
    def __init__(self):self.chat=SimpleNamespace(completions=self)
    def create(self,*,model,messages,max_tokens=1200,temperature=0.3,stream=False,response_format=None,**kwargs):
        if model not in ('echo-text','echo-vision'):raise account.AccountError('未知的 Echo 模型任务。')
        context={'messages':messages,'max_tokens':max_tokens,'temperature':temperature}
        if response_format is not None:context['response_format']=response_format
        extra=kwargs.get('extra_body') or {}
        purpose=extra.get('echo_purpose') if isinstance(extra,dict) else None
        result=account.inference('vision' if model=='echo-vision' else 'text',context,purpose=purpose)
        if stream:return _SingleResultStream(result['text'])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=result['text']),finish_reason=result.get('finish_reason','stop'))],usage=result.get('usage',{}))
