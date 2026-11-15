'use strict';
(()=>{
let paused=false;
const el=id=>document.getElementById(id);
const text=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n;};
async function call(path,body){const response=await fetch('/api/account/admin/releases'+path,{method:body?'POST':'GET',credentials:'same-origin',headers:body?{'Content-Type':'application/json','X-Echo-CSRF':'1'}:{},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(90000)});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'更新管理请求失败。');return data;}
async function load(){try{const data=await call('');paused=data.paused;el('release-pause').textContent=paused?'恢复自动更新分发':'暂停自动更新分发';el('release-status').textContent=paused?'自动更新已暂停；官网安装包仍可下载。':'自动更新分发正常。';el('release-list').replaceChildren(...data.items.map(item=>{const row=text('div','');row.className='record';const info=text('div','');info.append(text('strong',(item.channel==='beta'?'内测':'正式')+' '+item.release.version+' · '+(item.state==='published'?'已发布':'待发布')),text('p',item.release.filename+' · '+(item.release.size/1048576).toFixed(1)+' MB'),text('code','SHA-256: '+item.release.sha256));row.append(info);if(item.candidate){const button=text('button','发布此版本');button.type='button';button.onclick=async()=>{if(!confirm('确认发布 '+item.release.version+'？该操作将改变对应渠道的下载/更新版本。'))return;button.disabled=true;try{await call('/publish',{channel:item.channel,candidate:item.candidate});await load();}catch(e){el('release-status').textContent=e.message;button.disabled=false;}};row.append(button);}return row;}));}catch(e){el('release-status').textContent=e.message;}}
window.loadReleases=load;
el('release-refresh')?.addEventListener('click',load);
el('release-pause')?.addEventListener('click',async()=>{try{await call('/pause',{paused:!paused});await load();}catch(e){el('release-status').textContent=e.message;}});
})();
