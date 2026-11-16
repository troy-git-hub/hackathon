/* Shared personal learning overview. Read-only; never triggers AI. */
'use strict';
(()=>{
 if(typeof adminPage==='undefined'||adminPage||!document.querySelector('#personal-summary'))return;
 const get=id=>document.getElementById('personal-'+id),text=(id,value)=>{get(id).textContent=String(value);};
 const who=()=>String(currentUser?.id||'');let owner='',loading=null;
 function clear(){owner='';for(const id of ['submitted','answered','average','materials'])text(id,'—');get('attempts').replaceChildren();get('trend').replaceChildren();text('updated','登录后显示你的学习记录');text('progress','');text('wrong','');text('best','待批试卷不计入均分');text('bank','');text('storage','');text('usage','');}
 function trend(items){const host=get('trend');host.replaceChildren();if(!items.some(i=>i.answered)){host.append(node('p','完成一次作答后，这里会显示真实变化。','personal-empty'));return;}
  const NS='http://www.w3.org/2000/svg',svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 430 152');svg.setAttribute('role','img');svg.setAttribute('aria-label',items.map(i=>i.day+'：'+i.answered+'题次').join('；'));
  const add=(tag,attrs,content)=>{const e=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));if(content!==undefined)e.textContent=String(content);svg.append(e);return e;};
  const max=Math.max(1,...items.map(i=>i.answered)),x=i=>22+i*386/Math.max(1,items.length-1),y=i=>113-items[i].answered/max*83;
  for(const value of [0,.5,1])add('line',{x1:22,x2:408,y1:113-value*83,y2:113-value*83,class:'personal-gridline'});
  const points=items.map((_,i)=>x(i)+','+y(i)).join(' ');add('polygon',{points:'22,113 '+points+' 408,113',class:'personal-area'});add('polyline',{points,class:'personal-line',fill:'none'});
  items.forEach((d,i)=>{add('circle',{cx:x(i),cy:y(i),r:3,class:'personal-dot'});add('text',{x:x(i),y:y(i)-10,'text-anchor':'middle'},d.answered);add('text',{x:x(i),y:140,'text-anchor':'middle'},d.day);});host.append(svg);
 }
 function render(data){const s=data.study,u=data.usage_7d,q=data.storage;text('submitted',s.submitted);text('answered',s.answered);text('average',s.average_score===null?'—':s.average_score);text('materials',s.materials+' / '+s.papers);
  text('progress',s.in_progress+' 份进行中'+(s.awaiting_submit?' · '+s.awaiting_submit+' 份到时待交卷':''));text('wrong',s.wrong+' 题次待回顾 · '+s.pending+' 题待批');text('best',s.best_score===null?'还没有完成批改的试卷':'最高 '+s.best_score+' 分 · 已批 '+s.graded+' 卷');text('bank',s.bank_questions+' 道已确认题库题目');
  text('storage','个人云端占用 '+(q.used_bytes/1048576).toFixed(1)+' MiB · 实例共享 '+Math.round(q.shared_limit_bytes/1048576)+' MiB');text('usage','近七日 AI：'+u.completed+' 次 · '+(u.input_tokens+u.output_tokens).toLocaleString()+' token · '+u.points+' 学习点');
  text('updated','刚刚更新 · 不调用 AI');get('attempts').replaceChildren();
  for(const a of data.recent_attempts){const b=node('button',undefined,'personal-attempt'),info=node('span'),title=node('strong',a.title||'学习检测');info.append(title,node('small',date(a.created)));let state;
   if(a.status==='submitted')state=a.pending_count?'待批改':a.score+' 分';else state=a.deadline>data.server_time?'进行中':'到时待交卷';
   b.append(info,node('span',state,'personal-score'));b.type='button';b.onclick=async()=>{b.disabled=true;try{await window.openEchoStudyAttempt(a.id);}catch(e){text('updated',e.message);}finally{b.disabled=false;}};get('attempts').append(b);}
  if(!data.recent_attempts.length)get('attempts').append(node('p','还没有作答记录。可以从每日小题或清卷开始。','personal-empty'));
  trend(data.daily);
 }
 async function refresh(){const user=who();if(!user)return;if(owner!==user){clear();owner=user;}if(loading?.owner===user)return loading.task;
  text('updated','正在读取账户摘要…');const task=(async()=>{try{const data=await api('me/summary');if(who()!==user||owner!==user)return;if(data.user_id!==user)throw Error('账户摘要已变化，请重新登录。');render(data);}catch(e){if(who()===user&&owner===user)text('updated','摘要暂未更新，可刷新重试：'+e.message);}finally{if(loading?.task===task)loading=null;}})();loading={owner:user,task};return task;
 }
 window.addEventListener('echo:workspace',()=>void refresh());document.querySelector('#logout')?.addEventListener('click',clear);
 window.refreshPersonalSummary=refresh;if(currentUser)void refresh();
})();
