"""Account learning plan client. No local profile, model calls or write retries."""
from datetime import datetime, timedelta, timezone, date
from echo.backend import account

ROOT = '/v1/me/learning-path'
MINUTES = (5, 10, 15, 20, 30, 45)
STYLES = (('visual', '图解与比较'), ('story', '情境与例子'), ('direct', '简明推导'))
INTERESTS = ('运动', '音乐', '游戏', '科技', '自然', '阅读', '艺术', '生活')


def planning_tasks(snapshot):
    """Only return the shared server's supported, account-scoped task actions."""
    plan = snapshot.get('planner') or {}
    if plan.get('protocol') != 'echo.learning-planner/1':return []
    return [dict(t) for t in plan.get('tasks',[])[:6] if isinstance(t,dict) and t.get('action') in ('practice','qingjuan','studio','reflect')]


def today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


class Client:
    def __init__(self):
        self.owner = str((account.current_user() or {}).get('id') or '')
        self.session = account.token()

    def current(self):
        return bool(self.owner) and self.owner == str((account.current_user() or {}).get('id') or '') and self.session == account.token()

    def call(self, suffix='', data=None):
        if not self.current():
            raise account.AccountError('账户已变化，请重新打开学习目标。')
        value = account.request(ROOT + suffix, data, auth_token=self.session)
        if not self.current():
            raise account.AccountError('账户已变化，请重新打开学习目标。')
        if not isinstance(value, dict) or value.get('protocol') != 'echo.learning-path/1':
            raise account.AccountError('学习方案服务暂不可用，请稍后刷新。')
        return value

    def read(self):
        return self.call()

    def save_goal(self, goal, revision):
        data = dict(goal)
        subject = str(data.get('subject', '')).strip()
        target = str(data.get('target', '')).strip()
        interests = data.get('interests', [])
        if not subject or len(subject) > 30 or not 4 <= len(target) <= 160:
            raise ValueError('请选择学科，并填写4至160字的具体目标。')
        if type(data.get('minutes')) is not int or data['minutes'] not in MINUTES:
            raise ValueError('请选择每日投入时间。')
        if data.get('style') not in dict(STYLES):
            raise ValueError('请选择讲解偏好。')
        if not isinstance(interests, list) or len(interests) > 5 or any(not isinstance(v, str) or not 1 <= len(v.strip()) <= 24 for v in interests):
            raise ValueError('兴趣最多5项，每项1至24字。')
        data.update(subject=subject, target=target, interests=list(dict.fromkeys(v.strip() for v in interests)), revision=revision)
        if len(data.get('interest', '')) > 80:
            raise ValueError('自填兴趣最多80字。')
        if data.get('deadline'):
            try:
                due = date.fromisoformat(data['deadline'])
                current = date.fromisoformat(today())
                if not current <= due <= current + timedelta(days=730):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError('日期须为今天至未来两年内，格式为 YYYY-MM-DD。') from None
        return self.call('/goal', data)

    def set_today(self, mode, revision):
        if mode not in ('review', 'learn'):
            raise ValueError('请选择复习已学或学习新知识。')
        return self.call('/today', {'mode': mode, 'revision': revision})

    def reflect(self, value):
        return self.call('/reflections', value)

    def save_plan(self,snapshot):
        p=snapshot.get('planner') or {}
        tasks=[{k:t.get(k) for k in ('action','title','reason','topic','source_ids','minutes')} for t in planning_tasks(snapshot)]
        if not tasks or not p.get('context'):raise ValueError('请刷新并先设定目标。')
        return self.call('/planner',{'revision':p.get('revision',0),'context':p['context'],'origin':p.get('origin','rules'),
            'summary':p.get('summary','根据目标安排今日学习。'),'tasks':tasks})

    def set_task(self,snapshot,ident,state):
        p=snapshot.get('planner') or {}
        if not p.get('saved') or p.get('stale'):raise ValueError('请先保存当前规划。')
        if state not in ('pending','done') or not any(t.get('id')==ident for t in planning_tasks(snapshot)):raise ValueError('任务状态无效。')
        return self.call('/planner/task',{'id':ident,'state':state,'revision':p['revision'],'context':p['context']})
