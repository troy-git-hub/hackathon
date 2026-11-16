'use strict';
(()=>{
if(typeof adminPage==='undefined'||adminPage||!document.querySelector('[data-pane="qingjuan"]'))return;
const $=s=>document.querySelector(s),n=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
let owner='',paper=null,pid='',view='paper',photo=null,angle=0,busy=false;
const note=text=>{$('#qj-status').textContent=text;},identity=()=>String(currentUser?.id||'');
async function request(path,body,method){const who=identity();if(!who)throw Error('请先登录 Echo。');const result=await api('me/qingjuan'+path,body,method,120000);if(who!==identity())throw Error('账户已变更，结果未在当前页面展示。');return result;}
function action(text,fn,cls='table-action'){const b=n('button',text);b.className=cls;b.type='button';b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){note(e.message);}finally{b.disabled=false;}};return b;}
async function refresh(){if(!identity())return;if(owner!==identity()){paper=null;pid='';$('#qingjuan-preview').replaceChildren();$('#qj-library').replaceChildren();owner=identity();}
 const result=await request('/papers');$('#qj-library').replaceChildren(...result.items.map(item=>action(item.title,()=>open(item.id))));if(!result.items.length)$('#qj-library').append(n('p','还没有清卷试卷。可生成，或导入原清卷导出的 JSON。'));
}
async function open(id){const result=await request('/papers/'+encodeURIComponent(id));paper=result.paper;pid=result.id;view='paper';render();}
function scale(){const host=$('#qingjuan-preview'),frame=$('#qj-paper-frame');if(!paper)return;const factor=Math.min(1,Math.max(0.25,frame.clientWidth/794));host.style.width='794px';host.style.transform='scale('+factor+')';host.style.transformOrigin='top left';frame.style.height=Math.ceil(host.scrollHeight*factor+10)+'px';}
function render(){const host=$('#qingjuan-preview');host.replaceChildren();$('#qj-paper-name').textContent=paper?.meta?.title||'清卷预览';$('#qj-paper-actions').hidden=!paper;if(!paper)return;
 try{QJPaper.renderPaper(host,paper,{colorMode:'color',template:'modern',density:'normal',subject:paper.meta.subject,paper:'a4',watermark:false},view);scale();setTimeout(scale,200);}catch(e){host.replaceChildren(n('p','卷面暂未完整显示，可导出 JSON 保留数据：'+e.message));}
}
function downloadJson(){if(!paper)return;const url=URL.createObjectURL(new Blob([JSON.stringify(paper,null,2)],{type:'application/json'})),a=n('a');a.href=url;a.download=(paper.meta.title||'清卷')+'.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);}
async function start(){if(!pid)throw Error('请先生成或打开试卷。');const result=await request('/papers/'+pid+'/start',{request_id:crypto.randomUUID(),anti_cheat:$('#qj-focus').checked});await window.openEchoStudyAttempt(result.id);note('清卷已接入同一账户作答，成绩按百分制记录。');}
$('#qj-generate').onsubmit=async event=>{event.preventDefault();if(busy)return;
 const data={subject:$('#qj-subject').value,grade:$('#qj-grade').value,title:$('#qj-title').value,knowledge:$('#qj-knowledge').value,count:Number($('#qj-count').value),duration:Number($('#qj-duration').value)};
 if(!data.knowledge.trim()){note('请先填写知识点或课文范围。');return;}
 if(!confirm('清卷生成将按实际 token 消耗学习点。确认生成 '+data.count+' 道小题？题干与参考答案仍需核对。'))return;
 const key='echo-qingjuan-generation:'+identity(),sig=JSON.stringify(data);let pending;
 try{pending=JSON.parse(sessionStorage.getItem(key)||'null');}catch{}
 if(!pending||pending.sig!==sig)pending={sig,id:crypto.randomUUID()};sessionStorage.setItem(key,JSON.stringify(pending));
 busy=true;$('#qj-generate-button').disabled=true;note('正在命题，请保持页面打开。完整试卷生成可能需要一些时间…');
 try{const result=await request('/generate',{...data,request_id:pending.id});sessionStorage.removeItem(key);paper=result.paper;pid=result.id;view='paper';render();await refresh();note('清卷已保存。请核对题目和参考答案，再开始答题。');}
 catch(e){if(e.status&&![408,409,504].includes(e.status))sessionStorage.removeItem(key);note(e.message+' 可先刷新已存试卷，避免重复生成。');}
 finally{busy=false;$('#qj-generate-button').disabled=false;}
};
$('#qj-import').onchange=async event=>{const file=event.target.files?.[0];if(!file)return;try{if(file.size>512*1024)throw Error('JSON试卷最多512KiB。');const value=JSON.parse(await file.text());const result=await request('/papers',{request_id:crypto.randomUUID(),paper:value.paper||value});paper=result.paper;pid=result.id;view='paper';render();await refresh();note('已导入清卷原格式，未调用 AI。');}catch(e){note(e.message);}finally{event.target.value='';}};
$('#qj-paper-actions').append(action('试卷',()=>{view='paper';render();}),action('答案与解析',()=>{view='answers';render();}),action('答题卡',()=>{view='sheet';render();}),action('开始答题（免费）',start,'button'),action('下载 JSON',downloadJson),action('打印 / 存为 PDF',async()=>{if(document.fonts)await document.fonts.ready;render();window.print();}),action('删除试卷',async()=>{if(!confirm('删除这张清卷原卷？已经开始的作答记录会保留。'))return;await request('/papers/'+pid,{},'DELETE');paper=null;pid='';render();await refresh();}));
$('#qj-refresh').onclick=()=>refresh().catch(e=>note(e.message));
// Capture is a user-triggered native camera/file picker; no background camera access.
$('#qj-camera-file').onchange=async event=>{const file=event.target.files?.[0];if(!file)return;try{
 if(!/^image\/(jpeg|png|webp|heic|heif)$/.test(file.type))throw Error('请选择照片。HEIC若不能预览，请在手机上转为JPEG。');
 if(file.size>20*1024*1024)throw Error('原照片超过20MiB，请先压缩或裁剪。');
 const url=URL.createObjectURL(file),image=new Image();await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(Error('照片无法预览，请换用JPEG/PNG。'));image.src=url;});
 if(photo?.url)URL.revokeObjectURL(photo.url);photo={image,url};angle=0;$('#qj-photo-preview').src=url;$('#qj-photo-preview').hidden=false;$('#qj-photo-actions').hidden=false;$('#qj-photo-preview').style.transform='';note('请确认整页清晰、方向正确。上传时会生成优化照片并移除EXIF元数据。');
 }catch(e){note(e.message);}finally{event.target.value='';}};
$('#qj-rotate').onclick=()=>{angle=(angle+90)%360;$('#qj-photo-preview').style.transform='rotate('+angle+'deg)';};
async function photoBytes(){if(!photo)throw Error('请先拍摄或选择照片。');const im=photo.image,factor=Math.min(1,1800/Math.max(im.width,im.height)),w=Math.round(im.width*factor),h=Math.round(im.height*factor),canvas=document.createElement('canvas');canvas.width=angle%180?h:w;canvas.height=angle%180?w:h;const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.translate(canvas.width/2,canvas.height/2);ctx.rotate(angle*Math.PI/180);ctx.drawImage(im,-w/2,-h/2,w,h);let data;for(let quality=.9;quality>=.4;quality-=.1){data=canvas.toDataURL('image/jpeg',quality).split(',')[1];if(data.length*3/4<=1024*1024)return data;}throw Error('照片压缩后仍超过1MiB，请裁剪后重试。');}
$('#qj-upload-photo').onclick=async()=>{if(busy)return;busy=true;$('#qj-upload-photo').disabled=true;let mid=null;try{
 note('正在优化和上传照片…');const data=await photoBytes(),who=identity();
 const material=await api('me/study/materials',{filename:'清卷拍照-'+new Date().toISOString().slice(0,10)+'.jpg',content_base64:data},undefined,45000);if(who!==identity())throw Error('账户已变更。');mid=material.id;
 note('照片已私有保存，尚未消耗学习点。');
 if(confirm('照片已上传。现在调用视觉模型解析题目、总结知识点？此操作按 token 消耗学习点。')){
  const key='echo-qj-photo:'+who+':'+mid;let rid=sessionStorage.getItem(key);if(!rid){rid=crypto.randomUUID();sessionStorage.setItem(key,rid);}
  note('正在解析照片…');await api('me/study/materials/'+mid+'/analyze',{request_id:rid},undefined,120000);sessionStorage.removeItem(key);
 }
 await window.openEchoStudyMaterial(mid);note('请核对解析内容，再确认加入个人知识与题库。');
 }catch(e){note(e.message);if(mid)note(e.message+' 照片已保存在“资料与试卷”，可在那里继续。');}finally{busy=false;$('#qj-upload-photo').disabled=false;}};
window.ensureQingjuanView=view=>{if(view==='qingjuan')void refresh().catch(e=>note(e.message));};
window.addEventListener('echo:workspace',()=>{if(location.hash==='#qingjuan')void refresh().catch(e=>note(e.message));});
$('#logout')?.addEventListener('click',()=>{owner='';pid='';paper=null;busy=false;render();$('#qj-library').replaceChildren();if(photo?.url)URL.revokeObjectURL(photo.url);photo=null;$('#qj-photo-preview').removeAttribute('src');$('#qj-photo-preview').hidden=true;$('#qj-photo-actions').hidden=true;$('#qj-generate').reset();});
const previousDirty=window.echoStudyHasUnsaved;window.echoStudyHasUnsaved=()=>busy||Boolean(previousDirty?.());
new ResizeObserver(()=>scale()).observe($('#qj-paper-frame'));
if(currentUser&&location.hash==='#qingjuan')void refresh().catch(e=>note(e.message));
})();
