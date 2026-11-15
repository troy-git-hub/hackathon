import http from 'node:http';
import {readFile,stat} from 'node:fs/promises';
import {dirname,join,resolve,extname} from 'node:path';
import {fileURLToPath} from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'public');
const upstream=process.env.UPDATE_ORIGIN||'http://127.0.0.1:8787';
const types={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.png':'image/png','.ico':'image/x-icon','.json':'application/json; charset=utf-8'};
const headers={
  'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'",
  'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'strict-origin-when-cross-origin',
  'Permissions-Policy':'camera=(), microphone=(), geolocation=()','Cross-Origin-Opener-Policy':'same-origin'
};
const server=http.createServer({maxHeaderSize:8192},async(req,res)=>{
  const send=(status,body,type='text/plain; charset=utf-8',extra={})=>{res.writeHead(status,{...headers,'Content-Type':type,'Content-Length':Buffer.byteLength(body),'Cache-Control':'no-store',...extra});res.end(req.method==='HEAD'?undefined:body);};
  if(!['GET','HEAD'].includes(req.method))return send(405,'Method not allowed',undefined,{Allow:'GET, HEAD'});
  try{
    const url=new URL(req.url,'http://localhost');
    if(url.pathname==='/healthz')return send(200,'ok');
    if(url.pathname==='/api/release'){
      try{
        const reply=await fetch(new URL('/v1/catalog/stable/windows-x64',upstream),{signal:AbortSignal.timeout(5000),redirect:'error'});
        if(!reply.ok)return send(503,'Release service unavailable');
        const reader=reply.body.getReader();let size=0;const chunks=[];
        while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>65536){await reader.cancel();throw new Error('Release too large');}chunks.push(Buffer.from(value));}
        const body=Buffer.concat(chunks).toString('utf8');const envelope=JSON.parse(body);
        if(!envelope.release||typeof envelope.signature!=='string')throw new Error('Invalid release');
        return send(200,JSON.stringify(envelope),'application/json; charset=utf-8');
      }catch{return send(503,'Release service unavailable');}
    }
    let name;try{name=decodeURIComponent(url.pathname);}catch{return send(400,'Bad request');}
    if(name==='/'||name==='/index.html')name='/index.html';
    if(name==='/beta')name='/beta.html';
    if(name==='/download')name='/download.html';
    if(name==='/updates')name='/updates.html';
    if(name==='/user')name='/user.html';
    if(name==='/admin'||name==='/mail')name='/admin.html';
    if(name.includes('\\')||name.includes('\0')||name.split('/').some(part=>part.startsWith('.')))return send(404,'Not found');
    const path=resolve(root,'.'+name);
    if(!path.startsWith(root+'/')&&!path.startsWith(root+'\\'))return send(404,'Not found');
    const type=types[extname(path)];if(!type)return send(404,'Not found');
    if(!(await stat(path)).isFile())return send(404,'Not found');
    return send(200,await readFile(path),type,{'Cache-Control':extname(path)==='.html'?'no-cache':'public, max-age=3600'});
  }catch{return send(404,'Not found');}
});
server.requestTimeout=15000;server.headersTimeout=10000;server.keepAliveTimeout=5000;server.maxRequestsPerSocket=100;
server.listen(Number(process.env.PORT||8080),process.env.HOST||'127.0.0.1',()=>console.log('Echo Website listening on port '+(process.env.PORT||8080)));
