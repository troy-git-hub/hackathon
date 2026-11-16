"""Read-only personal study and usage totals, with no provider calls."""
from datetime import datetime,timezone
from fastapi import Request
import billing,storage

def install(app,core):
 db,auth,now=(core[k] for k in ('db','session_user','now'))
 decode=core['study_services']['decode']
 @app.get('/v1/me/summary')
 def summary(request:Request):
  uid=auth(request)['id'];stamp=now();today=(stamp+28800)//86400;since=(today-6)*86400-28800
  daily=[{'day':datetime.fromtimestamp((today-i)*86400,timezone.utc).strftime('%m-%d'),'submitted':0,'answered':0} for i in range(6,-1,-1)]
  stats={'attempts':0,'submitted':0,'in_progress':0,'awaiting_submit':0,'answered':0,'wrong':0,'pending':0,'average_score':None,'best_score':None,'graded':0}
  recent=[];scores=[]
  with db() as c:
   stats.update(materials=c.execute('SELECT count(*) FROM study_materials WHERE user_id=?',(uid,)).fetchone()[0],bank_questions=c.execute('SELECT count(*) FROM study_bank WHERE user_id=?',(uid,)).fetchone()[0],papers=c.execute('SELECT count(*) FROM qingjuan_papers WHERE user_id=?',(uid,)).fetchone()[0])
   for row in c.execute('SELECT * FROM study_attempts WHERE user_id=? ORDER BY created DESC LIMIT 200',(uid,)):
    paper=decode(row['cipher'],'study-attempt:'+uid+':'+row['id']);stats['attempts']+=1
    if len(recent)<3:recent.append({k:paper.get(k) for k in ('id','title','kind','status','created','deadline','score','pending_count')})
    if row['status']!='submitted':
     stats['in_progress' if row['deadline']>stamp else 'awaiting_submit']+=1;continue
    stats['submitted']+=1;results=list(paper.get('results',{}).values());answered=sum(r['status']!='unanswered' for r in results)
    stats['answered']+=answered;stats['wrong']+=sum(r['status'] in ('incorrect','partial','unanswered') for r in results);stats['pending']+=paper.get('pending_count',0)
    if not paper.get('pending_count',0):scores.append(paper.get('score',0))
    # Study records retain creation time; this chart intentionally groups by paper creation day.
    day=(row['created']+28800)//86400;ix=day-(today-6)
    if 0<=ix<7:daily[ix]['submitted']+=1;daily[ix]['answered']+=answered
   stats['graded']=len(scores)
   if scores:stats['average_score']=round(sum(scores)/len(scores),1);stats['best_score']=round(max(scores),1)
   usage=dict(c.execute("SELECT count(*) AS requests,coalesce(sum(CASE WHEN state='succeeded' THEN 1 ELSE 0 END),0) AS completed,coalesce(sum(CASE WHEN state='failed' THEN 1 ELSE 0 END),0) AS failed,coalesce(sum(CASE WHEN state='succeeded' THEN input_tokens ELSE 0 END),0) AS input_tokens,coalesce(sum(CASE WHEN state='succeeded' THEN output_tokens ELSE 0 END),0) AS output_tokens,coalesce(sum(CASE WHEN state='succeeded' THEN cost ELSE 0 END),0) AS points FROM inference_requests WHERE user_id=? AND created>=?",(uid,since)).fetchone())
   usage['points']=billing.points(usage['points']);quota={'used_bytes':storage.used(c,uid),'shared_limit_bytes':storage.LIMIT}
  return {'user_id':uid,'server_time':stamp,'study':stats,'recent_attempts':recent,'daily':daily,'usage_7d':usage,'storage':quota,'note':'统计当前保存的考试/每日小题记录，重做计为新题次；均分不含待批改试卷。七日图按试卷创建日归组，采用北京时间。'}
