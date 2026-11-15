'use strict';
function renderAdminTrends(points){
 const host=document.querySelector('#admin-usage-chart');if(!host)return;
 host.replaceChildren();
 const configs=[
  {title:'请求趋势',unit:'次',lines:[['succeeded','成功','#eac45f'],['failed','失败','#df8d79'],['pending','处理中','#81aaa8']]},
  {title:'Token 用量',unit:'token',lines:[['input_tokens','输入','#eac45f'],['output_tokens','输出','#98b8d4']]},
  {title:'请求成功率',unit:'%',max:100,lines:[['success_rate','已完成请求成功率','#b5ce9b']]}
 ];
 for(const config of configs){
  const card=document.createElement('section');card.className='trend-card';
  const title=document.createElement('h3');title.textContent=config.title;card.append(title);
  const caption=document.createElement('p');caption.className='fine';caption.textContent='最近 24 个小时 · 北京时间'+(config.unit==='%'?' · 无已完成请求的时段留空':'');card.append(caption);
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 520 220');svg.setAttribute('role','img');svg.setAttribute('aria-label',config.title+'，最近24个小时，单位'+config.unit);
  const add=(tag,attrs,text)=>{const n=document.createElementNS(svg.namespaceURI,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;svg.append(n);return n;};
  const values=points.flatMap(p=>config.lines.map(([key])=>p[key])).filter(v=>typeof v==='number'&&Number.isFinite(v));
  const max=config.max||Math.max(1,...values),x=i=>48+i*450/Math.max(1,points.length-1),y=v=>174-v/max*142;
  for(let i=0;i<4;i++){const value=max*i/3;add('line',{x1:48,x2:498,y1:y(value),y2:y(value),stroke:'#39352a','stroke-width':1});add('text',{x:40,y:y(value)+4,'text-anchor':'end',fill:'#a59c89','font-size':10},Number(value.toFixed(max<10?1:0)).toLocaleString('zh-CN'));}
  points.forEach((point,i)=>{if(i%6===0||i===points.length-1)add('text',{x:x(i),y:198,'text-anchor':'middle',fill:'#a59c89','font-size':10},new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit',hourCycle:'h23',timeZone:'Asia/Shanghai'}).format(new Date(point.hour*1000)));});
  for(const [key,label,color] of config.lines){
   let segment=[];const flush=()=>{if(segment.length>1)add('polyline',{points:segment.join(' '),fill:'none',stroke:color,'stroke-width':2,'stroke-linejoin':'round'});segment=[];};
   points.forEach((point,i)=>{const value=point[key];if(typeof value!=='number'||!Number.isFinite(value)){flush();return;}segment.push(x(i)+','+y(value));const dot=add('circle',{cx:x(i),cy:y(value),r:2.7,fill:color});const tip=document.createElementNS(svg.namespaceURI,'title');tip.textContent=new Date(point.hour*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' · '+label+' '+value.toLocaleString('zh-CN')+config.unit;dot.append(tip);});flush();
  }
  card.append(svg);
  const legend=document.createElement('div');legend.className='trend-legend';for(const [,label,color] of config.lines){const item=document.createElement('span'),dot=document.createElement('span');dot.className='trend-dot';dot.style.backgroundColor=color;item.append(dot,document.createTextNode(label));legend.append(item);}card.append(legend);
  if(!points.length){const empty=document.createElement('p');empty.textContent='暂无请求统计';card.append(empty);}host.append(card);
 }
}
