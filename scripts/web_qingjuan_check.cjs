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

const errors=[],calls=[],papers=[];
let sample={meta:{title:'清卷·一次函数',subject:'数学',grade:'八年级',duration:30,total_score:5},sections:[{title:'选择题',type:'choice',questions:[{id:'q1',type:'choice',stem:'当 $x=2$ 时，$y=x^2$ 等于？',options:['4','5'],answer:'A',analysis:'代入即可',score:5,figure:{kind:'coord',functions:[{expr:'x*x',label:'y=x²'}],xRange:[-3,3],yRange:[-1,9]}}]}]};
const shim=`const $=s=>document.querySelector(s);const adminPage=false;let currentUser={id:'u1'};async function api(p,b,m){const r=await fetch('/api/account/'+p,{method:m||(b?'POST':'GET'),headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});const data=await r.json();if(!r.ok){const e=Error(data.detail);e.status=r.status;throw e;}return data;}window.openEchoStudyAttempt=async id=>window.started=id;window.openEchoStudyMaterial=async id=>window.openedMaterial=id;document.querySelector('#auth-panel').hidden=true;document.querySelector('#member-panel').hidden=false;`;
(async()=>{const browser=await chromium.launch(browserOptions());const page=await browser.newPage({viewport:{width:1440,height:1100}});page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
await page.route('https://echo.test/**',async route=>{const u=new URL(route.request().url());if(u.pathname.startsWith('/api/')){const p=u.pathname.slice('/api/account/'.length),b=route.request().postDataJSON();calls.push(p);let data={};
if(p==='me/qingjuan/papers'&&b){papers.push({id:'p1',title:sample.meta.title});data={id:'p1',paper:b.paper};}
else if(p==='me/qingjuan/papers')data={items:papers};
else if(p==='me/qingjuan/papers/p1')data={id:'p1',paper:sample};
else if(p==='me/qingjuan/papers/p1/start')data={id:'a1'};
return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});}
if(u.pathname==='/account.js')return route.fulfill({contentType:'application/javascript',body:shim});
if(['/console.js','/study.js'].includes(u.pathname))return route.fulfill({contentType:'application/javascript',body:''});
const filename=path.join(pub,u.pathname==='/user.html'?'user.html':u.pathname.slice(1));if(fs.existsSync(filename))return route.fulfill({path:filename});return route.fulfill({status:404,body:''});});
try{await page.goto('https://echo.test/user.html#qingjuan');await page.evaluate(()=>{document.querySelectorAll('[data-pane]').forEach(x=>x.hidden=x.dataset.pane!=='qingjuan');});
await page.locator('#qj-library').waitFor();assert.equal(calls.some(x=>x.includes('generate')),false);
await page.locator('#qj-import').setInputFiles({name:'paper.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(sample))});
await page.locator('.a4-page').waitFor();assert.equal(await page.locator('#qj-paper-name').textContent(),sample.meta.title);assert.ok(await page.locator('.katex').count());
const color=await page.locator('.a4-page').first().evaluate(e=>getComputedStyle(e).backgroundColor);assert.equal(color,'rgb(33, 31, 24)');
await page.getByRole('button',{name:'开始答题（免费）'}).click();await page.waitForFunction(()=>window.started==='a1');
assert.equal(await page.evaluate(()=>QJExpression.compile('sin(pi/2)+x*x')(2)),5);
for(const expression of ['window.alert(1)','x;alert(1)','constructor.constructor("return 1")()'])assert.equal(await page.evaluate(e=>QJExpression.compile(e),expression),null);
await page.screenshot({path:path.join(root,'artifacts','echo-web-qingjuan.png'),fullPage:true});
await page.setViewportSize({width:390,height:844});await page.waitForTimeout(300);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+2));
await page.screenshot({path:path.join(root,'artifacts','echo-web-qingjuan-mobile.png'),fullPage:true});assert.deepEqual(errors,[]);console.log('PASS: original Qingjuan JSON import, dark paper, KaTeX, safe expressions, free shared-account answer bridge, mobile layout, no paid AI on load');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
