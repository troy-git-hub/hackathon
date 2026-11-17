'use strict';
// Learning views share account.js authentication, CSRF protection and API errors.
(() => {
  if (adminPage || !document.querySelector('[data-pane="study"]')) return;
  const views = new Set(['study', 'materials', 'exams']);
  const S = {owner:null,root:null,materials:[],attempts:[],daily:null,loading:null,loaded:0,
    attempt:null,draft:{},edit:0,savedEdit:0,saving:null,saveTimer:null,conflict:false,
    submitting:false,clock:null,expired:false,offset:0,requests:new Map(),aiBusy:0,loggedOut:false};
  const q = selector => document.querySelector(selector);
  const el = (tag,text,cls) => node(tag,text,cls);
  const seconds = () => Date.now()/1000;
  const cnDate = value => value ? new Date(value*1000).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}) : '未安排';
  const errText = error => error.name==='TimeoutError' || error.name==='AbortError'
    ? '请求超时，结果可能仍在处理中。请用原按钮重试，系统会复用请求编号；也可以刷新查看已有结果。' : error.message;
  function status(text,tone='info') {
    document.querySelectorAll('.study-status').forEach(n=>{n.textContent=text;n.dataset.tone=tone;n.classList.toggle('study-loading',tone==='loading');});
  }
  function button(text,fn,cls='table-action') {
    const b=el('button',text,cls);b.type='button';
    b.addEventListener('click',async()=>{b.disabled=true;try{await fn();}catch(e){status(errText(e),'error');}finally{b.disabled=false;}});
    return b;
  }
  function empty(text,action) {
    const n=el('div',undefined,'workspace-empty');n.append(el('p',text));
    if(action)n.append(button(action[0],action[1]));return n;
  }
  function actionRow(...buttons) {const n=el('div',undefined,'study-actions');n.append(...buttons);return n;}
  async function request(path,body,method,timeout) {
    if(S.loggedOut)throw new Error('已退出登录，请重新登录。');
    const owner=S.owner,result=await api('me/study'+path,body,method,timeout);
    if(S.loggedOut||S.owner!==owner||ownerKey()!==owner)throw new Error('账户已变更，请刷新学习空间。');
    return result;
  }
  function ownerKey() {return String(currentUser?.id||currentUser?.email||'');}
  function clearUser() {
    clearBrowserState(S.owner);
    clearInterval(S.clock);clearTimeout(S.saveTimer);
    Object.assign(S,{owner:ownerKey(),root:null,materials:[],attempts:[],daily:null,loaded:0,loading:null,
      attempt:null,draft:{},edit:0,savedEdit:0,saving:null,conflict:false,submitting:false,expired:false});
    S.requests.clear();q('#web-exam-active').hidden=true;q('#daily-current').hidden=true;
    q('#material-detail').hidden=true;
    q('#exam-setup').hidden=false;
    ['#study-topics','#study-plan-list','#material-list','#material-detail','#web-exam-history','#web-exam-active','#daily-current','#exam-sources','#daily-source'].forEach(selector=>q(selector).replaceChildren());
    q('#material-form').reset();
  }
  function clearBrowserState(owner) {
    if(!owner)return;
    try{for(const key of Object.keys(sessionStorage))if(key.startsWith('echo-study-draft:'+owner+':')||key.startsWith('echo-study-request:'+owner+':'))sessionStorage.removeItem(key);}catch{}
  }
  q('#logout')?.addEventListener('click',()=>{
    clearBrowserState(S.owner);clearTimeout(S.saveTimer);clearInterval(S.clock);
    clearUser();S.loggedOut=true;S.owner=null;S.attempt=null;S.draft={};S.edit=S.savedEdit=0;S.aiBusy=0;
  });
  // Reuse the same id after ambiguous timeouts. Session scope survives reloads.
  function requestId(key,payload) {
    const signature=JSON.stringify(payload),storage='echo-study-request:'+ownerKey()+':'+key;
    let record=S.requests.get(key);
    if(!record){try{record=JSON.parse(sessionStorage.getItem(storage));}catch{}}
    if(!record||record.signature!==signature)record={signature,id:crypto.randomUUID()};
    S.requests.set(key,record);try{sessionStorage.setItem(storage,JSON.stringify(record));}catch{}
    return record.id;
  }
  function finishRequest(key) {S.requests.delete(key);try{sessionStorage.removeItem('echo-study-request:'+ownerKey()+':'+key);}catch{}}
  function draftKey(id) {return 'echo-study-draft:'+ownerKey()+':'+id;}
  function stashDraft() {if(!S.attempt)return;try{sessionStorage.setItem(draftKey(S.attempt.id),JSON.stringify({answers:S.draft,revision:S.attempt.revision}));}catch{}}
  function removeDraft(id) {try{sessionStorage.removeItem(draftKey(id));}catch{}}
  async function charged(key,payload,call) {
    // Never invoked by refresh, scheduling, timers or an automatic fallback.
    S.aiBusy++;
    try {
      const result=await call(requestId(key,payload));finishRequest(key);
      if(payload.generate||key.startsWith('analyze:')||key.startsWith('grade:')) {
        // Refresh only the balance, not the entire account/learning console.
        api('me').then(data=>{if(ownerKey()===S.owner){currentUser=data.user;message('#balance',data.user.balance);message('#w-balance',data.user.balance);}}).catch(()=>{});
      }
      return result;
    } catch(error) {
      // A definite server rejection can be retried as a new user action. Keep
      // ambiguous timeouts / in-progress ids so retries cannot charge twice.
      if(error.status&&![408,409,504].includes(error.status))finishRequest(key);
      throw error;
    }
    finally {S.aiBusy=Math.max(0,S.aiBusy-1);}
  }
  async function refresh(force=false) {
    if(!currentUser||S.loggedOut)return;
    if(S.owner!==ownerKey())clearUser();
    if(S.loading)return S.loading;
    if(!force&&S.loaded&&Date.now()-S.loaded<60000)return;
    const who=S.owner;
    status('正在加载你的学习空间…','loading');
    const task=(async()=>{
      try {
        const [root,materials,attempts,daily]=await Promise.all([request(''),request('/materials'),request('/attempts'),request('/daily')]);
        if(who!==ownerKey())return;
        S.root=root;S.materials=materials.items;S.attempts=attempts.items;S.daily=daily;S.loaded=Date.now();
        renderPreferences();renderSources();renderTopics();renderMaterials();renderAttempts();renderDaily();
        status('');
      } catch(e) {if(who===S.owner&&!S.loggedOut)status(errText(e)+' 点击上方“刷新状态”重试。','error');}
      finally {if(S.loading===task)S.loading=null;}
    })();
    S.loading=task;return task;
  }
  window.ensureStudyView = view => {if(views.has(view))void refresh();};
  window.addEventListener('echo:workspace',()=>{if(views.has(location.hash.slice(1)))void refresh();});
  async function refreshMainWorkspace() {
    try{await window.loadWorkspace?.();return true;}catch{return false;}
  }
  function prefs() {return S.root?.preferences||{};}
  function renderPreferences() {
    const p=prefs(),plan=S.root.plan||{};
    q('#study-plan-goal').value=String(p.daily_count||3);q('#daily-count').value=String(p.daily_count||3);
    // A one-question saved goal is also available in the quick daily form.
    if(!q('#daily-count').value){q('#daily-count').prepend(new Option('1 道 · 保持节奏','1'));q('#daily-count').value=String(p.daily_count||3);}
    q('#study-plan-enabled').checked=Boolean(p.exam_enabled);q('#study-plan-weekday').value=String(p.exam_weekday??6);
    q('#study-plan-time').value=String(p.exam_hour??19).padStart(2,'0')+':'+String(p.exam_minute??30).padStart(2,'0');
    q('#study-plan-exam-count').value=String(p.exam_count||10);q('#study-plan-duration').value=p.exam_duration||30;
    q('#study-plan-anti').checked=Boolean(p.anti_cheat);q('#web-exam-anti').checked=Boolean(p.anti_cheat);
    q('#web-exam-count').value=String(p.exam_count||10);
    if([...q('#web-exam-minutes').options].some(o=>Number(o.value)===p.exam_duration))q('#web-exam-minutes').value=String(p.exam_duration);
    const host=q('#study-plan-list');host.replaceChildren();
    host.append(el('p','每日 '+(p.daily_count||3)+' 道 · '+(plan.daily_day||'今日'),'fine'));
    if(p.exam_enabled){host.append(el('p',(plan.exam_due?'阶段考试已到时间':'下次阶段考试')+' · '+cnDate(plan.next_exam_at),'practice-feedback'),button('去组一张试卷 →',()=>showWorkspace('exams')));}
    else host.append(el('p','未开启每周考试提醒。你仍可随时手动组卷。','fine'));
    const bill=S.root.billing||{};
    if(bill.input_points_per_1000!==undefined&&bill.output_points_per_1000!==undefined)
      document.querySelectorAll('[data-study-cost]').forEach(n=>n.textContent=`AI 生成 / 整理 / 主观批改按 token 结算：每千输入 ${bill.input_points_per_1000} 点、输出 ${bill.output_points_per_1000} 点。免费抽题和客观判分不调用模型。`);
    const limits=S.root.limits||{};
    const maxBytes=limits.material_bytes||limits.max_file_bytes||limits.file_bytes||3*1024*1024;
    q('#material-file-hint').textContent='TXT / MD / 文字 PDF / DOCX ≤ '+(maxBytes/1024/1024).toFixed(0)+' MB；PNG / JPEG ≤ 1 MB。扫描件可手动补充文字。';
    q('#material-quota').textContent='已保存 '+S.materials.length+' / '+(limits.max_files||10)+' 份资料 · '+((S.root.storage?.used_bytes??S.materials.reduce((sum,m)=>sum+m.size,0))/1024/1024).toFixed(1)+' / '+((limits.user_storage_bytes||10485760)/1024/1024).toFixed(0)+' MiB 云端总使用量 · 可用题库 '+(S.root.stats?.bank_questions||0)+' 道。每次最多 '+(limits.max_sources||12)+' 个来源，AI 操作每日限 '+(limits.ai_requests_per_day||15)+' 次，服务器统一校验。';
  }
  function sources() {
    return [...(S.root?.knowledge||[]).map(k=>({value:'k:'+k.id,label:(k.subject?k.subject+' / ':'')+k.topic,kind:'knowledge'})),
      ...S.materials.filter(m=>m.status==='ready'&&m.text_length>0).map(m=>({value:'m:'+m.id,label:'资料 / '+m.filename,kind:'material'}))];
  }
  function scope(values) {return {knowledge_ids:values.filter(v=>v.startsWith('k:')).map(v=>v.slice(2)),material_ids:values.filter(v=>v.startsWith('m:')).map(v=>v.slice(2))};}
  function renderSources() {
    const items=sources(),selected=q('#daily-source').value,host=q('#exam-sources');
    const checked=new Set([...host.querySelectorAll('input:checked')].map(n=>n.value));
    q('#daily-source').replaceChildren(new Option(items.length?'选择一个知识点或资料':'暂无范围，请先上传资料或同步知识点',''),...items.map(s=>new Option(s.label,s.value)));
    if(items.some(s=>s.value===selected))q('#daily-source').value=selected;
    host.replaceChildren();
    items.forEach(s=>{const label=el('label'),input=el('input');input.type='checkbox';input.value=s.value;input.checked=checked.has(s.value);label.append(input,el('span',s.label));host.append(label);});
    if(!items.length)host.append(empty('还没有可用于组卷的内容。上传资料并核对解析，或同步桌面知识点。',['上传资料 →',()=>showWorkspace('materials')]));
  }
  function renderTopics() {
    const host=q('#study-topics'),topics=S.root?.knowledge||[];host.replaceChildren();
    for(const k of topics.slice(0,12)) {
      const card=el('article',undefined,'study-topic');card.append(el('h3',k.topic),el('p',(k.subject||'未分类')+' · '+(topicStates[k.state]||'暂无记录')),
        actionRow(button('回忆与自评',()=>{selectedReview=k.id;showWorkspace('review');renderReview();}),button('练一道题',()=>focusPractice(k.id))));host.append(card);
    }
    if(!topics.length)host.append(empty('同步桌面学习档案后，知识点会出现在这里。你也可以先上传资料，开始今日小题。',['管理云端数据 →',()=>showWorkspace('cloud')]));
    if(topics.length>12)host.append(button('查看全部 '+topics.length+' 个知识点 →',()=>showWorkspace('review')));
  }
  function renderDaily() {
    const host=q('#daily-current'),daily=S.daily;host.hidden=!daily?.attempt;if(!daily?.attempt)return;
    const a=daily.attempt;host.replaceChildren(el('p',(a.status==='submitted'?'今日小题已完成':'今日小题进行中')+' · '+daily.day,'practice-feedback'),button(a.status==='submitted'?'查看今日解析':'继续今日小题',()=>openAttempt(a.id)));
  }
  q('#study-plan-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget,[hour,minute]=q('#study-plan-time').value.split(':').map(Number);busy(form,true);
    try {await request('/preferences',{daily_count:Number(q('#study-plan-goal').value),exam_enabled:q('#study-plan-enabled').checked,
      exam_weekday:Number(q('#study-plan-weekday').value),exam_hour:hour,exam_minute:minute,exam_count:Number(q('#study-plan-exam-count').value),
      exam_duration:Number(q('#study-plan-duration').value),anti_cheat:q('#study-plan-anti').checked});await refresh(true);status('学习安排已保存，按北京时间提醒；不会自动调用 AI。','success');}
    catch(e){status(errText(e),'error');}finally{busy(form,false);}
  });
  async function startDaily(event) {
    event.preventDefault();const form=event.currentTarget,generate=event.submitter?.value==='generate',value=q('#daily-source').value;
    if(!value){status('先选择一个知识点或资料。','error');return;}
    if(generate&&!confirm('生成新题会按 token 消耗学习点，确认开始？已有今日小题会直接恢复。'))return;
    busy(form,true);status(generate?'AI 正在生成今日小题，请保持页面打开…':'正在免费抽取题库…','loading');
    const payload={generate,...scope([value])};
    try {
      if(Number(q('#daily-count').value)!==prefs().daily_count)await request('/preferences',{...prefs(),daily_count:Number(q('#daily-count').value)});
      const result=await charged('daily',payload,id=>request('/daily',{...payload,request_id:id},undefined,120000));
      await openAttempt(result.attempt?.id||result.id);await refresh(true);status(generate?'今日小题已准备好。':'已从题库抽取，不消耗 AI 学习点。','success');
    } catch(e){status(errText(e),'error');}finally{busy(form,false);}
  }
  q('#daily-form').addEventListener('submit',startDaily);
  function fileBytes(file) {return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败，请重新选择。'));reader.readAsDataURL(file);});}
  q('#material-file').addEventListener('change',()=>{const f=q('#material-file').files[0];q('#material-progress-note').textContent=f?f.name+' · '+(f.size/1024).toFixed(1)+' KB':'';});
  q('#material-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget,file=q('#material-file').files[0];if(!file||!q('#material-consent').checked)return;
    const image=/\.(png|jpe?g)$/i.test(file.name),limit=image?1024*1024:3*1024*1024;
    if(file.size>limit){status('文件超出大小限制：'+(image?'图片最多 1 MB。':'单份资料最多 3 MB。'),'error');return;}
    busy(form,true);q('#material-progress').hidden=false;q('#material-progress').removeAttribute('value');
    q('#material-progress-note').textContent='正在读取、上传并解析文件…';status('正在上传资料，请勿关闭页面。','loading');
    try {
      const content=await fileBytes(file),payload={filename:file.name,content_base64:content};
      const result=await charged('upload',payload,id=>request('/materials',{...payload,request_id:id},undefined,90000));
      form.reset();await refresh(true);await showMaterial(result.material?.id||result.id);
      q('#material-progress-note').textContent='上传完成。请检查解析文字；尚未调用 AI 整理。';status('资料已保存。','success');
    }catch(e){q('#material-progress-note').textContent='未完成。保留所选文件，可用原按钮重试。';status(errText(e),'error');}
    finally{busy(form,false);q('#material-progress').hidden=true;}
  });
  const materialStates={ready:'文字已就绪',needs_ocr:'需要补充文字',image:'图片 · 需文字说明'};
  function renderMaterials() {
    const query=q('#material-search').value.trim().toLowerCase(),host=q('#material-list');host.replaceChildren();
    const items=S.materials.filter(m=>m.filename.toLowerCase().includes(query));
    items.forEach(m=>{
      const row=el('div',undefined,'study-record'),info=el('div',undefined,'study-record-main');
      info.append(el('strong',m.filename),el('small',(materialStates[m.status]||m.status)+' · '+(m.size/1024).toFixed(1)+' KB · '+(m.text_length||0)+' 字符'+(m.analyzed?' · 已 AI 整理':'')+'\n'+cnDate(m.created)));
      const download=el('a','下载原件','table-action');download.href='/api/account/me/study/materials/'+encodeURIComponent(m.id)+'/download';
      row.append(info,actionRow(button('查看与校正',()=>showMaterial(m.id)),download,button('删除',async()=>{
        if(!confirm('删除“'+m.filename+'”的在线原件、解析与关联题库？已开始或提交的试卷保留快照。删除无法撤销。'))return;
        await request('/materials/'+encodeURIComponent(m.id),{},'DELETE');q('#material-detail').hidden=true;await refresh(true);
        const ready=await refreshMainWorkspace();
        status('资料、解析与关联题库已删除；已开始的试卷保留快照。'+(ready?'':' 知识点列表暂未刷新，请稍后刷新学习空间。'),'success');
      },'table-action danger')));host.append(row);
    });
    if(!items.length)host.append(empty(query?'没有匹配的资料。试试其他关键词。':'还没有上传资料。选择一份课件、复习材料或试卷，开始建立自己的题库。'));
  }
  q('#material-search').addEventListener('input',renderMaterials);
  async function showMaterial(id) {
    const data=await request('/materials/'+encodeURIComponent(id)),m=data.material||data,host=q('#material-detail');host.hidden=false;host.replaceChildren();
    host.append(el('span','MATERIAL / '+(materialStates[m.status]||m.status),'study-kicker'),el('h2',m.filename));
    if(m.status==='image') {
      const image=el('img');image.src='/api/account/me/study/materials/'+encodeURIComponent(id)+'/download';image.alt=m.filename;image.className='study-material-image';host.append(image);
      host.append(el('p','图片可以手动调用设置的视觉服务解析，按 token 消耗学习点；不会自动识图或计费。','study-cost fine'));
    }
    (m.warnings||[]).forEach(w=>host.append(el('p',w,'practice-feedback')));
    if(m.analysis) {
      host.append(el('h3','AI 复习提要'),el('p',m.analysis.summary||'暂无提要。','study-preview'));
      (m.analysis.topics||[]).forEach(t=>{const card=el('div',undefined,'study-topic');card.append(el('h3',t.name),el('p',t.notes));host.append(card);});
      (m.analysis.warnings||[]).forEach(w=>host.append(el('p',w,'fine')));
      const questions=m.analysis.questions||[];
      host.append(el('p','AI 推导的题目与答案可能有误，请逐题核对后再加入题库。','study-cost fine'));
      questions.forEach((item,i)=>{
        const details=el('details',undefined,'study-question');details.append(el('summary',(i+1)+'. '+item.question));
        (item.options||[]).forEach((text,j)=>details.append(el('p',String.fromCharCode(65+j)+'. '+text,'fine')));
        if(item.answer_source==='inferred')details.append(el('p','此答案由 AI 推导，请核对原题和教材。','study-tag'));
        details.append(el('p','参考答案：'+formatAnswer(item,item.answer),'study-review-answer'),el('p','解析：'+(item.explanation||item.explain||'暂无解析'),'fine'));host.append(details);
      });
      host.append(m.analysis.confirmed?el('p','已确认加入题库。','study-tag'):button('我已核对，免费确认加入题库',async()=>{
        if(!confirm('确认已核对 AI 题目、参考答案和解析？确认后这些题目将参与免费抽题。'))return;
        await request('/materials/'+encodeURIComponent(id)+'/confirm',{});await refresh(true);
        const workspaceReady=await refreshMainWorkspace();
        await showMaterial(id);status(workspaceReady?'已确认加入题库，知识点复习已同步更新，现在可以免费抽题。':'已确认加入题库。知识点列表暂未刷新，请稍后刷新学习空间。','success');
      }));
    }
    const form=el('form'),label=el('label','解析文字 · 可以免费校正'),text=el('textarea');text.value=m.text||'';text.rows=12;text.maxLength=120000;text.setAttribute('aria-label','校正解析文字');label.append(text);
    text.maxLength=S.root?.limits?.max_text_chars||30000;
    const save=el('button','免费保存校正','table-action');save.type='submit';form.append(label,save);
    form.addEventListener('submit',async e=>{e.preventDefault();busy(form,true);try{
      await request('/materials/'+encodeURIComponent(id)+'/text',{text:text.value});await refresh(true);
      const ready=await refreshMainWorkspace();await showMaterial(id);
      status('文字已更新，请重新解析并核对题目。'+(ready?' 知识点复习列表已同步更新。':' 知识点列表暂未刷新，请稍后刷新学习空间。'),'success');
    }catch(error){status(errText(error),'error');}finally{busy(form,false);}});
    host.append(form,el('p','AI 整理将基于已保存文字生成知识点和题库，按 token 消耗学习点。先保存校正，再开始整理。','study-cost fine'),actionRow(button('让 AI 整理并建立题库',async()=>{
      if(text.value!==(m.text||'')){status('请先保存文字校正，再调用 AI。','error');return;}
      if(!text.value.trim()&&m.status!=='image'){status('请先补充可用的文字内容。扫描 PDF 暂不自动 OCR。','error');return;}
      if(!confirm('确认使用账户学习点，整理这份资料并生成题库？'))return;
      status('AI 正在整理资料并建立题库，请保持页面打开…','loading');
      await charged('analyze:'+id,{id,text:m.text},rid=>request('/materials/'+encodeURIComponent(id)+'/analyze',{request_id:rid},undefined,120000));
      await refresh(true);const ready=await refreshMainWorkspace();await showMaterial(id);
      status('AI 整理完成，请核对提要和题目。'+(ready?'':' 知识点列表暂未刷新，请稍后刷新学习空间。'),'success');
    }),button('用这份资料练习 →',()=>{showWorkspace('study');q('#daily-source').value='m:'+id;})));
    host.scrollIntoView?.({block:'start',behavior:'smooth'});
  }
  q('#web-exam-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget,generate=event.submitter?.value==='generate';
    const values=[...q('#exam-sources').querySelectorAll('input:checked')].map(n=>n.value);
    if(values.length<1||values.length>12){status('请选择 1 至 12 个知识点或资料。','error');return;}
    if(generate&&!confirm('生成整张新试卷会按 token 消耗学习点，确认开始？'))return;
    const payload={title:q('#web-exam-title').value.trim(),...scope(values),count:Number(q('#web-exam-count').value),duration_minutes:Number(q('#web-exam-minutes').value),generate,anti_cheat:q('#web-exam-anti').checked};
    busy(form,true);status(generate?'AI 正在组卷，请保持页面打开，避免重复请求…':'正在从题库免费组卷…','loading');
    try {const result=await charged('exam',payload,id=>request('/exams',{...payload,request_id:id},undefined,120000));await openAttempt(result.attempt?.id||result.id);await refresh(true);status('试卷已开始计时。答案会自动保存，退出后计时继续。','success');}
    catch(e){status(errText(e),'error');}finally{busy(form,false);}
  });
  function renderAttempts() {
    const host=q('#web-exam-history');host.replaceChildren();
    S.attempts.forEach(a=>{const row=el('div',undefined,'study-record'),info=el('div',undefined,'study-record-main');
      info.append(el('strong',a.title),el('small',(a.kind==='daily'?'每日小题':'阶段考试')+' · '+a.count+' 题 · '+(a.status==='submitted'?'已交卷'+(a.pending_count?' · '+a.pending_count+' 题待批改':''):'作答中 · 截止 '+cnDate(a.deadline))+'\n'+cnDate(a.created)));
      const actions=actionRow(button(a.status==='submitted'?'查看解析与判分':'继续作答',()=>openAttempt(a.id)));
      if(a.status==='submitted'&&a.wrong_count>0)actions.append(button('错题重做（免费）',()=>retryAttempt(a)));
      row.append(info,actions);host.append(row);});
    if(!S.attempts.length)host.append(empty('尚未开始考试或每日练习。先选择复习范围，可从已有题库免费抽取。'));
  }
  const typeNames={single_choice:'单选',multiple_choice:'多选',true_false:'判断',fill_blank:'填空',short_answer:'简答'};
  async function retryAttempt(attempt) {
    if(S.attempt?.status==='active'&&S.edit!==S.savedEdit){
      await saveAnswers();if(S.edit!==S.savedEdit)throw new Error('当前作答尚未保存，请先保存进度。');
    }
    const key='retry:'+attempt.id,payload={id:attempt.id};
    const result=await charged(key,payload,rid=>request('/attempts/'+encodeURIComponent(attempt.id)+'/retry',{request_id:rid}));
    await openAttempt(result.attempt?.id||result.id);await refresh(true);
    status('已免费创建错题练习。原试卷与结果保留，本次未调用 AI。','success');
  }
  async function openAttempt(id) {
    if(!id)throw new Error('未获取到试卷编号，请刷新列表查看。');
    if(S.attempt?.status==='active'&&S.attempt.id!==id&&S.edit!==S.savedEdit)await saveAnswers();
    if(S.edit!==S.savedEdit&&S.attempt?.id!==id)throw new Error('当前作答尚未保存，请先处理保存提示。');
    const data=await request('/attempts/'+encodeURIComponent(id));adoptAttempt(data.attempt||data);
    showWorkspace('exams');q('#web-exam-active').scrollIntoView?.({block:'start',behavior:'smooth'});
  }
  function adoptAttempt(a) {
    clearInterval(S.clock);clearTimeout(S.saveTimer);
    S.attempt=a;S.draft=structuredClone(a.answers||{});S.edit=S.savedEdit=0;S.conflict=false;S.expired=false;
    S.offset=(a.server_time||seconds())-seconds();
    if(a.status==='submitted')removeDraft(a.id);
    renderAttempt();S.clock=setInterval(tick,1000);tick();
    if(a.status==='active') {
      let local;try{local=JSON.parse(sessionStorage.getItem(draftKey(a.id)));}catch{}
      if(local&&JSON.stringify(local.answers)!==JSON.stringify(a.answers||{})) {
        const note=el('div',undefined,'practice-feedback');note.append(el('p','浏览器中保留了一份尚未确认保存的草稿。可查看并手动恢复；服务端版本暂时保留。'));
        note.append(actionRow(button('恢复这份草稿',()=>{S.draft=local.answers;S.edit++;stashDraft();renderAttempt();scheduleSave();}),button('使用服务端作答',()=>{removeDraft(a.id);note.remove();})));
        q('#web-exam-active').prepend(note);
      }
    }
  }
  function answerChange(id,value) {
    if(!S.attempt||S.attempt.status!=='active'||S.expired||S.submitting)return;
    S.draft[id]=value;S.edit++;stashDraft();saveNote('有新作答，等待保存…');scheduleSave();
  }
  function scheduleSave() {clearTimeout(S.saveTimer);S.saveTimer=setTimeout(()=>void saveAnswers(),800);}
  function saveNote(text) {const host=q('#study-save-note');if(host)host.textContent=text;}
  async function saveAnswers() {
    clearTimeout(S.saveTimer);
    if(S.saving){await S.saving;return;}
    if(!S.attempt||S.attempt.status!=='active'||S.conflict||S.edit===S.savedEdit)return;
    const id=S.attempt.id,owner=S.owner,edit=S.edit,answers=structuredClone(S.draft),revision=S.attempt.revision;
    saveNote('正在保存…');
    S.saving=(async()=>{
      try {
        const data=await request('/attempts/'+encodeURIComponent(id)+'/answers',{answers,revision}),a=data.attempt||data;
        if(owner!==ownerKey()||S.attempt?.id!==id)return;
        if(a.status==='submitted'){adoptAttempt(a);return;}
        S.attempt=a;S.savedEdit=edit;saveNote('答案已保存 · '+new Date().toLocaleTimeString('zh-CN'));
        if(S.edit===edit)removeDraft(id);
      }catch(e){
        if(owner!==ownerKey()||S.attempt?.id!==id)return;
        if(e.status===409){S.conflict=true;status('试卷已在其他页面更新。草稿仍保留在此浏览器，请点“重新载入”，核对后再手动恢复草稿。','error');}
        else status('答案暂未保存：'+errText(e)+' 请点“保存进度”重试。','error');
        saveNote('保存未完成 · 草稿暂留此浏览器');
      }finally{S.saving=null;}
    })();
    await S.saving;
    if(S.attempt?.id===id&&S.edit>edit&&!S.conflict)scheduleSave();
  }
  function renderAttempt() {
    const a=S.attempt,host=q('#web-exam-active');host.hidden=false;q('#exam-setup').hidden=true;host.replaceChildren();const submitted=a.status==='submitted';
    const toolbar=el('div',undefined,'study-exam-toolbar'),head=el('div');head.append(el('h2',a.title),el('p',submitted?'已交卷 · 查看解析':'退出后计时继续 · 截止 '+cnDate(a.deadline),'fine'));
    toolbar.append(head,el('span','','study-clock'));toolbar.lastChild.id='study-exam-clock';
    const actions=actionRow();
    if(!submitted){actions.append(button('保存进度',saveAnswers),button('重新载入',async()=>{
      if(S.edit!==S.savedEdit&&!confirm('重新载入服务端进度？未保存草稿会保留，可在重新载入后手动恢复。'))return;
      await openAttempt(a.id);
    }),button('交卷',submitAttempt,'button'));
      if(a.anti_cheat)actions.append(button('进入全屏',async()=>{await host.requestFullscreen();}));
      actions.append(button('暂时退出',async()=>{
        if(!confirm('保存后暂时退出？计时继续，回到试卷列表可恢复。'))return;
        await saveAnswers();if(S.edit!==S.savedEdit)throw new Error('仍有答案未保存，请先重试保存。');
        await recordEvent('exit');if(document.fullscreenElement)await document.exitFullscreen();host.hidden=true;q('#exam-setup').hidden=false;await refresh(true);
      }));
    }
    else {
      actions.append(button('返回组卷',()=>{host.hidden=true;q('#exam-setup').hidden=false;}));
      if(a.wrong_count>0)actions.append(button('错题重做（免费）',()=>retryAttempt(a)));
      if(a.pending_count>0)actions.append(button('让 AI 批改主观题',async()=>{
      if(!confirm('批改待批主观题将按 token 消耗学习点，确认开始？'))return;
      status('AI 正在批改主观题，请稍候…','loading');
      const data=await charged('grade:'+a.id,{id:a.id,revision:a.revision},rid=>request('/attempts/'+encodeURIComponent(a.id)+'/grade',{request_id:rid},undefined,120000));
      adoptAttempt(data.attempt||data);await refresh(true);status('批改结果已更新。AI 判分请结合教材核对。','success');
      }));
    }
    toolbar.append(actions);host.append(toolbar);const note=el('p',submitted?'客观判分完成；待批题不等于判错。':'答案自动保存；网络失败时草稿暂存当前浏览器会话。','study-save-note');note.id='study-save-note';host.append(note);
    if(submitted)host.append(el('p',`已判得分 ${Number(a.score||0).toFixed(1)} 分 · ${a.pending_count||0} 题待批改${a.pending_count?'，当前分数不是最终成绩。':'。'} · 切屏等记录 ${a.events_count||0} 次`,'practice-feedback'));
    for(const item of a.questions) {
      const card=el('article',undefined,'study-question');card.append(el('span',(typeNames[item.type]||item.type)+' · '+Number(item.points||0).toFixed(2)+' 分'+(item.source_label?' · '+item.source_label:''),'study-kicker'),el('h3',item.question));
      if(item.figure&&window.QJFigures){const figure=el('div',undefined,'qj-paper-dark');figure.innerHTML=window.QJFigures.renderFigure(item.figure,'line');card.append(figure);}
      if(['single_choice','multiple_choice','true_false'].includes(item.type)) {
        const options=el('div',undefined,'practice-options');(item.options||[]).forEach((text,i)=>{
          const label=el('label'),input=el('input');input.type=item.type==='multiple_choice'?'checkbox':'radio';input.name='study-'+a.id+'-'+item.id;input.disabled=submitted;
          input.checked=item.type==='multiple_choice'?Array.isArray(S.draft[item.id])&&S.draft[item.id].includes(i):S.draft[item.id]===i;
          input.addEventListener('change',()=>{
            if(item.type==='multiple_choice')answerChange(item.id,[...options.querySelectorAll('input')].flatMap((n,j)=>n.checked?[j]:[]));
            else answerChange(item.id,i);
          });label.append(input,el('span',String.fromCharCode(65+i)+'. '+text));options.append(label);
        });card.append(options);
      } else {
        const input=el('textarea');input.value=typeof S.draft[item.id]==='string'?S.draft[item.id]:'';input.disabled=submitted;input.maxLength=4000;input.setAttribute('aria-label',item.question+' 作答');input.placeholder=item.type==='fill_blank'?'填写答案…':'写下你的思路和答案…';input.addEventListener('input',()=>answerChange(item.id,input.value));card.append(input);
      }
      if(submitted) {
        const r=a.results?.[item.id],review=el('div',undefined,'study-review-answer');review.dataset.state=r?.status||'pending';
        review.append(el('strong',r?({correct:'答对了',incorrect:'需要巩固',partial:'部分正确',pending:'主观题待批改',unanswered:'未作答'}[r.status]||'判分待确认'):'判分记录暂不可用'),
          el('p',r?.feedback||'请刷新后查看结果。'));
        if(r&&Object.hasOwn(r,'answer'))review.append(el('p','参考答案：'+formatAnswer(item,r.answer)));
        if(r?.explanation)review.append(el('p','解析：'+r.explanation));card.append(review);
      }
      host.append(card);
    }
    if(window.renderMathInElement)window.renderMathInElement(host,{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false},{left:'\\(',right:'\\)',display:false},{left:'\\[',right:'\\]',display:true}],throwOnError:false,trust:false});
  }
  function formatAnswer(question,answer) {
    if(Array.isArray(answer))return answer.map(a=>typeof a==='number'?String.fromCharCode(65+a):String(a)).join('、');
    if(typeof answer==='number'&&question.options?.length)return String.fromCharCode(65+answer)+'. '+(question.options[answer]||'');
    return String(answer??'暂无参考答案');
  }
  async function submitAttempt() {
    if(!S.attempt||S.attempt.status==='submitted'||S.submitting)return;
    const answered=S.attempt.questions.filter(q=>Object.hasOwn(S.draft,q.id)&&S.draft[q.id]!==''&&(!Array.isArray(S.draft[q.id])||S.draft[q.id].length)).length;
    if(!confirm('已填写 '+answered+' / '+S.attempt.count+' 题。确认交卷？提交后不能修改。'))return;
    S.submitting=true;
    try {
      await saveAnswers();if(S.conflict)throw new Error('先重新载入并核对作答，再交卷。');
      const id=S.attempt.id,data=await request('/attempts/'+encodeURIComponent(id)+'/submit',{answers:structuredClone(S.draft),revision:S.attempt.revision});
      if(document.fullscreenElement)await document.exitFullscreen();adoptAttempt(data.attempt||data);await refresh(true);status('已交卷。客观题已判分，主观题可手动请求 AI 批改。','success');
    }catch(e){status(errText(e),'error');}finally{S.submitting=false;}
  }
  function tick() {
    const a=S.attempt,clock=q('#study-exam-clock');if(!a||!clock)return;
    if(a.status==='submitted'){clock.textContent='试卷回顾';clearInterval(S.clock);return;}
    const remain=Math.max(0,Math.ceil(a.deadline-seconds()-S.offset));clock.textContent='剩余 '+String(Math.floor(remain/60)).padStart(2,'0')+':'+String(remain%60).padStart(2,'0');
    if(!remain&&!S.expired){S.expired=true;clearTimeout(S.saveTimer);saveNote('答题时间已到，正在获取服务端判定。');
      request('/attempts/'+encodeURIComponent(a.id)).then(data=>{
        const updated=data.attempt||data;
        if(S.attempt?.id!==a.id)return;
        if(updated.status==='submitted'||updated.deadline>updated.server_time)adoptAttempt(updated);
        else saveNote('时间已到，服务端正在结算。请点击“重新载入”查看，避免重复提交。');
      }).catch(e=>{status('时间已到。'+errText(e)+' 请重新载入查看服务端结果。','error');});}
  }
  let lastEvent=0;
  async function recordEvent(kind) {
    if(!S.attempt||S.attempt.status!=='active'||!S.attempt.anti_cheat||ownerKey()!==S.owner)return;
    if(kind==='blur'&&seconds()-lastEvent<1)return;lastEvent=seconds();
    try{await request('/attempts/'+encodeURIComponent(S.attempt.id)+'/events',{kind});}catch{saveNote('作答仍在本地；部分专注记录暂未上传。');}
  }
  window.addEventListener('blur',()=>void recordEvent('blur'));
  document.addEventListener('visibilitychange',()=>{if(document.hidden){void recordEvent('blur');if(S.edit!==S.savedEdit)void saveAnswers();}});
  document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement)void recordEvent('fullscreen_exit');});
  window.addEventListener('beforeunload',event=>{if(S.aiBusy||S.edit!==S.savedEdit){event.preventDefault();event.returnValue='';}});
  document.querySelectorAll('[data-study-refresh]').forEach(b=>b.addEventListener('click',()=>void refresh(true)));
  window.openEchoStudyMaterial=async id=>{showWorkspace('materials');await refresh(true);await showMaterial(id);};
  window.openEchoStudyAttempt=async id=>{await refresh(true);await openAttempt(id);};
  window.echoStudyHasUnsaved=()=>Boolean(S.aiBusy||S.edit!==S.savedEdit);
  if(currentUser&&views.has(location.hash.slice(1)))void refresh();
})();
