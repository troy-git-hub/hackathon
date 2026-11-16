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


const errors=[],calls=[];
const fixture={user_id:'u1',server_time:1794835800,study:{submitted:6,in_progress:1,awaiting_submit:0,answered:86,wrong:12,pending:2,average_score:87.5,best_score:96,graded:5,materials:4,papers:3,bank_questions:42},usage_7d:{completed:12,input_tokens:6400,output_tokens:6000,points:18.4},storage:{used_bytes:7*1048576,shared_limit_bytes:128*1048576},daily:[5,12,8,18,10,20,13].map((answered,i)=>({day:'11-'+(10+i),answered,submitted:1})),recent_attempts:[{id:'a1',title:'一次函数 · 清卷专项',status:'submitted',score:92,created:1794830000},{id:'a2',title:'每日小题 · 数学',status:'submitted',score:80,created:1794750000},{id:'a3',title:'函数图像综合检测',status:'active',deadline:1794836800,created:1794830000}]};
const shim=`const $=s=>document.querySelector(s);const adminPage=false;let currentUser={id:'u1'};function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}function date(t){return new Date(t*1000).toLocaleDateString('zh-CN');}async function api(p){const r=await fetch('/api/account/'+p);return r.json();}window.openEchoStudyAttempt=async id=>window.openedAttempt=id;document.querySelector('#auth-panel').hidden=true;document.querySelector('#member-panel').hidden=false;`;
(async()=>{const browser=await chromium.launch(browserOptions());const page=await browser.newPage({viewport:{width:1440,height:1280}});page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
await page.route('https://echo.test/**',async route=>{const u=new URL(route.request().url());if(u.pathname.startsWith('/api/')){calls.push(u.pathname);return route.fulfill({contentType:'application/json',body:JSON.stringify(fixture)});}
if(u.pathname==='/account.js')return route.fulfill({contentType:'application/javascript',body:shim});
if(['/console.js','/study.js','/qingjuan.js'].includes(u.pathname))return route.fulfill({contentType:'application/javascript',body:''});const file=path.join(pub,u.pathname==='/user.html'?'user.html':u.pathname.slice(1));if(fs.existsSync(file))return route.fulfill({path:file});return route.fulfill({status:404,body:''});});
try{await page.goto('https://echo.test/user.html#overview');await page.evaluate(()=>{document.querySelectorAll('[data-pane]').forEach(e=>e.hidden=e.dataset.pane!=='overview');for(const [id,value]of Object.entries({'member-name':'晚上好，继续你的学习。','w-knowledge':'28','w-due':'4','w-weak':'3','w-balance':'126.8','goal-progress':'3 / 5'}))document.getElementById(id).textContent=value;document.getElementById('goal-meter').value=3;});
await page.waitForFunction(()=>document.getElementById('personal-answered').textContent==='86');assert.equal(await page.locator('#personal-average').textContent(),'87.5');assert.equal(await page.locator('#personal-attempts button').count(),3);assert.equal(await page.locator('#personal-trend svg circle').count(),7);assert.ok(calls.every(p=>p==='/api/account/me/summary'));
await page.screenshot({path:path.join(root,'artifacts','echo-user-center-web.png')});await page.getByRole('button',{name:/一次函数 · 清卷专项/}).click();await page.waitForFunction(()=>window.openedAttempt==='a1');
await page.setViewportSize({width:390,height:844});await page.waitForTimeout(250);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));await page.locator('#personal-summary').screenshot({path:path.join(root,'artifacts','echo-user-center-mobile.png')});
await page.evaluate(()=>{currentUser={id:'another'};window.dispatchEvent(new CustomEvent('echo:workspace'));});await page.waitForFunction(()=>document.getElementById('personal-updated').textContent.includes('账户摘要已变化'));assert.equal(await page.locator('#personal-answered').textContent(),'—');await page.locator('#logout').click();assert.equal(await page.locator('#personal-attempts').textContent(),'');assert.deepEqual(errors,[]);console.log('PASS: shared account summary, real-data labels, seven-day chart, exam resume, mobile width, account mismatch and logout clearing; read-only API only');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
