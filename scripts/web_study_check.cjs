/* Isolated browser contract checks. Every API request is mocked; no real AI. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),pub=path.join(root,'Echo Website','public');
const moduleRoot=process.env.ECHO_TEST_NODE_MODULES||path.join(process.env.USERPROFILE||'', '.cache','codex-runtimes','codex-primary-runtime','dependencies','node','node_modules');
const {chromium}=require(path.join(moduleRoot,'playwright'));
function browserOptions(){
  let executablePath=process.env.ECHO_TEST_BROWSER;
  if(!executablePath&&process.platform==='win32'){
    const edge=path.join(process.env['ProgramFiles(x86)']||'C:\\Program Files (x86)','Microsoft','Edge','Application');
    if(fs.existsSync(edge))executablePath=fs.readdirSync(edge,{withFileTypes:true}).filter(d=>d.isDirectory()&&/^\d+\./.test(d.name))
      .map(d=>d.name).sort((a,b)=>b.localeCompare(a,undefined,{numeric:true})).map(d=>path.join(edge,d,'msedge.exe')).find(p=>fs.existsSync(p));
  }
  return executablePath?{executablePath,headless:true}:{channel:'msedge',headless:true};
}
const now=Math.floor(Date.now()/1000),calls=[],errors=[];
const preferences={daily_count:3,exam_enabled:true,exam_weekday:6,exam_hour:19,exam_minute:30,exam_count:5,exam_duration:30,anti_cheat:false};
let confirmed=false,failSave=false,conflict=false,daily=null,material=null;
let attempt={id:'a1',title:'鲁迅专题检测',kind:'exam',status:'active',created:now,deadline:now+1800,server_time:now,revision:1,anti_cheat:false,
  questions:[{id:'q1',type:'single_choice',question:'鲁迅的作品是哪一部？',options:['朝花夕拾','其他作品'],points:20,topic:'鲁迅',source_label:'语文'},
    {id:'q2',type:'multiple_choice',question:'选择回忆性散文的特点。',options:['回顾往事','结合感受','纯粹虚构'],points:20},
    {id:'q3',type:'true_false',question:'朝花夕拾属于回忆性散文集。',options:['正确','错误'],points:20},
    {id:'q4',type:'fill_blank',question:'填写作者。',options:[],points:20},
    {id:'q5',type:'short_answer',question:'解释弃医从文的原因。',options:[],points:20}],answers:{},results:null,score:0,pending_count:0,count:5,events_count:0};
const clone=v=>structuredClone(v);
const shim=`'use strict';const $=s=>document.querySelector(s);const adminPage=false;let currentUser={id:'u1',name:'测试同学',email:'test@example.com',balance:1000};
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e;}
function message(s,text){const n=$(s);if(n)n.textContent=text;}
function busy(f,b){f.querySelectorAll('button').forEach(n=>n.disabled=b);}
function date(t){return String(t);}
async function api(p,b,m){const r=await fetch('/api/account/'+p,{method:m||(b?'POST':'GET'),headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});const d=await r.json();if(!r.ok){const e=Error(d.detail);e.status=r.status;throw e;}return d;}
document.querySelector('#auth-panel').hidden=true;document.querySelector('#member-panel').hidden=false;`;
(async()=>{
  const browser=await chromium.launch(browserOptions());
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.setDefaultTimeout(10000);
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  await page.route('https://echo.test/**',async route=>{
    const u=new URL(route.request().url()),method=route.request().method();
    if(u.pathname.startsWith('/api/account/')) {
      const p=u.pathname.slice('/api/account/'.length),body=route.request().postDataJSON();calls.push({p,method,body});
      let data={},status=200;
      if(p==='public/config')data={billing:{input_points_per_1000:1,output_points_per_1000:2}};
      else if(p==='me')data={user:{id:'u1',name:'测试同学',email:'test@example.com',balance:900}};
      else if(p==='me/study')data={preferences,limits:{},billing:{input_points_per_1000:1,output_points_per_1000:2},plan:{next_exam_at:now+86400,exam_due:false,daily_day:'2026-11-15'},stats:{materials:material?1:0,bank_questions:confirmed?5:0},knowledge:[{id:'k1',topic:'鲁迅与朝花夕拾',subject:'语文',state:'weakness'}]};
      else if(p==='me/study/preferences'){Object.assign(preferences,body);data=preferences;}
      else if(p==='me/study/materials'&&method==='GET')data={items:material?[material]:[],limits:{}};
      else if(p==='me/study/materials'&&method==='POST'){material={id:'m1',filename:body.filename,mime:'text/plain',size:80,status:'ready',created:now,pages:1,text_length:40,analyzed:false,warnings:[],text:'鲁迅弃医从文，希望通过文学改变人们的精神。',analysis:null};data=clone(material);}
      else if(p==='me/study/materials/m1'&&method==='GET')data=clone(material);
      else if(p==='me/study/materials/m1'&&method==='DELETE'){material=null;confirmed=false;data={ok:true};}
      else if(p==='me/study/materials/m1/text'){material.text=body.text;data=clone(material);}
      else if(p==='me/study/materials/m1/analyze'){material.analyzed=true;material.analysis={summary:'鲁迅的文学选择',topics:[{name:'弃医从文',notes:'文学与思想启蒙'}],question_count:1,warnings:[],confirmed:false,questions:[{type:'single_choice',question:'鲁迅为何弃医从文？',options:['思想启蒙','其他原因'],answer:0,explanation:'希望改变精神。'}]};data=clone(material);}
      else if(p==='me/study/materials/m1/confirm'){confirmed=true;material.analysis.confirmed=true;data=clone(material);}
      else if(p==='me/study/daily'&&method==='GET')data={day:'2026-11-15',count:3,attempt:daily,available_questions:confirmed?5:0};
      else if(p==='me/study/daily'&&method==='POST'){if(!body.generate&&!confirmed){status=409;data={detail:'题库不足，请先确认资料题目或手动生成。'};}else{daily=clone(attempt);data=daily;}}
      else if(p==='me/study/attempts')data={items:[attempt]};
      else if(p==='me/study/exams'){data=clone(attempt);}
      else if(p==='me/study/attempts/a1')data=clone(attempt);
      else if(p==='me/study/attempts/a1/answers'){
        if(conflict){status=409;data={detail:'revision conflict'};conflict=false;}
        else if(failSave){status=503;data={detail:'模拟网络故障'};}
        else{attempt.answers=body.answers;attempt.revision++;data=clone(attempt);}
      }
      else if(p==='me/study/attempts/a1/submit'){
        assert.equal(body.revision,attempt.revision);attempt.answers=body.answers;attempt.status='submitted';attempt.revision++;attempt.score=60;attempt.pending_count=2;
        attempt.results=Object.fromEntries(attempt.questions.map((q,i)=>[q.id,{status:i<3?'correct':'pending',score:i<3?1:null,feedback:i<3?'回答正确':'等待手动 AI 批改',answer:i<3?0:'鲁迅',explanation:'结合原文理解。'}]));data=clone(attempt);
      }
      else if(p==='me/study/attempts/a1/grade'){attempt.pending_count=0;attempt.score=100;Object.values(attempt.results).forEach(r=>{r.status='correct';r.score=1;});data=clone(attempt);}
      else if(p==='me/study/attempts/a1/retry'){
        assert.ok(body.request_id);attempt={...clone(attempt),status:'active',answers:{},results:null,revision:1,wrong_count:0,pending_count:0,deadline:now+1800};data=clone(attempt);
      }
      else if(p.endsWith('/events'))data={ok:true};
      else {status=404;data={detail:'unmocked '+p};}
      return route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
    }
    if(u.pathname==='/account.js')return route.fulfill({contentType:'application/javascript',body:shim});
    const filename=path.join(pub,u.pathname==='/'?'user.html':u.pathname.slice(1));
    if(fs.existsSync(filename))return route.fulfill({path:filename});
    return route.fulfill({status:404,body:''});
  });
  try {
    for(const view of ['materials','exams']){
      await page.goto('https://echo.test/user.html#'+view);
      await page.locator('#daily-source option[value="k:k1"]').waitFor({state:'attached'});
      assert.equal(await page.locator('[data-pane='+view+']').isVisible(),true,'direct hash route '+view);
    }
    await page.goto('https://echo.test/user.html#study');
    await page.locator('#daily-source option[value="k:k1"]').waitFor({state:'attached'});
    await page.evaluate(()=>{window.workspaceRefreshes=0;window.loadWorkspace=async()=>{window.workspaceRefreshes++;};});
    assert.equal(calls.filter(c=>c.method==='POST').length,0,'loading must not trigger AI');
    await page.locator('#daily-source').selectOption('k:k1');
    await page.locator('#daily-form button[value="reuse"]').click();
    await page.locator('[data-pane=study] .study-status').filter({hasText:'题库不足'}).waitFor();
    assert.equal(calls.filter(c=>c.body?.generate===true).length,0,'409 must not trigger paid fallback');
    await page.locator('[data-view=materials]').click();
    await page.locator('#material-file').setInputFiles({name:'鲁迅专题.txt',mimeType:'text/plain',buffer:Buffer.from('鲁迅弃医从文，希望通过文学改变人们的精神。')});
    await page.locator('#material-consent').check();await page.locator('#material-form button').click();
    await page.locator('#material-detail h2').filter({hasText:'鲁迅专题.txt'}).waitFor();
    await page.getByRole('button',{name:'让 AI 整理并建立题库'}).click();
    await page.getByRole('button',{name:'我已核对，免费确认加入题库'}).waitFor();
    await page.locator('#material-detail details summary').click();
    assert.match(await page.locator('#material-detail').textContent(),/参考答案：A/);
    await page.getByRole('button',{name:'我已核对，免费确认加入题库'}).click();
    await page.locator('#material-detail .study-tag').filter({hasText:'已确认加入题库'}).waitFor();
    await page.locator('[data-view=exams]').click();
    await page.locator('#web-exam-title').fill('鲁迅专题检测');await page.locator('#exam-sources input[value="k:k1"]').check();
    await page.locator('#web-exam-form button[value=reuse]').click();
    await page.locator('#web-exam-active').waitFor();
    assert.equal(await page.locator('#web-exam-active .study-review-answer').count(),0,'active exam must not display answers');
    await page.locator('input[name=study-a1-q1]').first().check();
    await page.locator('input[name=study-a1-q2]').first().check();
    await page.locator('input[name=study-a1-q2]').nth(1).check();
    await page.locator('input[name=study-a1-q3]').first().check();
    await page.locator('.study-question textarea').first().fill('鲁迅');
    await page.locator('.study-question textarea').nth(1).fill('改变人们的精神。');
    await page.getByRole('button',{name:'保存进度',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#study-save-note').textContent.includes('已保存'));
    assert.deepEqual(attempt.answers.q2,[0,1]);assert.equal(attempt.answers.q1,0);
    failSave=true;await page.locator('.study-question textarea').first().fill('鲁迅先生');
    await page.getByRole('button',{name:'保存进度',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#study-save-note').textContent.includes('保存未完成'));
    assert.match(await page.locator('[data-pane=exams] .study-status').textContent(),/模拟网络故障/);
    failSave=false;conflict=true;await page.getByRole('button',{name:'保存进度',exact:true}).click();
    await page.locator('[data-pane=exams] .study-status').filter({hasText:'其他页面更新'}).waitFor();
    await page.getByRole('button',{name:'重新载入',exact:true}).click();
    await page.getByRole('button',{name:'恢复这份草稿'}).click();
    await page.getByRole('button',{name:'保存进度',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#study-save-note').textContent.includes('已保存'));
    await page.getByRole('button',{name:'交卷',exact:true}).click();
    await page.getByRole('button',{name:'让 AI 批改主观题'}).waitFor();
    assert.equal(await page.locator('#web-exam-active .study-review-answer[data-state=pending]').count(),2);
    await page.getByRole('button',{name:'让 AI 批改主观题'}).click();
    await page.waitForFunction(()=>!document.querySelector('#web-exam-active .study-review-answer[data-state=pending]'));
    // Simulate a submitted report with one graded wrong answer, then reopen.
    attempt.wrong_count=1;
    await page.locator('#web-exam-history').getByRole('button',{name:'查看解析与判分'}).click();
    await page.locator('#web-exam-active').getByRole('button',{name:'错题重做（免费）'}).click();
    await page.locator('#web-exam-active').getByRole('button',{name:'交卷',exact:true}).waitFor();
    assert.equal(await page.locator('#web-exam-active .study-review-answer').count(),0,'retry must hide reference answers');
    assert.deepEqual(attempt.answers,{});assert.equal(calls.filter(c=>c.p.endsWith('/retry')).length,1);
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile page must not overflow');
    const out=path.join(root,'artifacts');fs.mkdirSync(out,{recursive:true});
    await page.screenshot({path:path.join(out,'echo-web-study-mobile.png'),fullPage:true});
    await page.setViewportSize({width:1440,height:1050});await page.locator('[data-view=study]').click();
    await page.screenshot({path:path.join(out,'echo-web-study.png'),fullPage:true});
    const refreshBefore=await page.evaluate(()=>window.workspaceRefreshes);
    assert.ok(refreshBefore>=2,'analyze and confirm refresh main knowledge views');
    await page.locator('[data-view=materials]').click();
    await page.locator('#material-list').getByRole('button',{name:'查看与校正'}).click();
    await page.locator('#material-detail textarea').fill('校正：鲁迅通过文学关注人们的精神。');
    await page.getByRole('button',{name:'免费保存校正'}).click();
    await page.waitForFunction(n=>window.workspaceRefreshes===n+1,refreshBefore);
    await page.locator('#material-list').getByRole('button',{name:'删除',exact:true}).click();
    await page.waitForFunction(n=>window.workspaceRefreshes===n+2,refreshBefore);
    await page.locator('#material-list .workspace-empty').waitFor();
    // The account script calls loadWorkspace after login; this event is the
    // integration hook, without coupling authentication to study internals.
    await page.evaluate(()=>{currentUser={id:'u2',name:'另一个账户',email:'other@example.com',balance:1};window.dispatchEvent(new CustomEvent('echo:workspace'));});
    await page.waitForFunction(()=>document.querySelector('#daily-source option[value="k:k1"]'));
    await page.evaluate(()=>sessionStorage.setItem('echo-study-draft:u2:test',JSON.stringify({answers:{q1:0}})));
    await page.locator('#logout').click();
    assert.equal(await page.evaluate(()=>sessionStorage.getItem('echo-study-draft:u2:test')),null,'logout clears account-scoped browser drafts');
    assert.equal(await page.locator('#web-exam-active').textContent(),'','logout clears displayed answer content');
    assert.deepEqual(errors,[]);
    console.log('PASS: direct study/materials/exams routes, login hook, logout draft clearing, zero AI on load, no paid fallback, upload/analyze/confirm, five question types, autosave/retry/conflict/draft, submit/pending/manual grade, mobile layout');
  }catch(error){
    console.error('DEBUG',JSON.stringify({errors,calls:calls.map(c=>({p:c.p,method:c.method})),status:await page.locator('.study-status').allTextContents()}));
    fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});await page.screenshot({path:path.join(root,'artifacts','echo-web-study-failure.png'),fullPage:true});throw error;
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
