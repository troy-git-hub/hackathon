/* Arithmetic-only parser: no eval/Function and no relaxed script CSP. */
(()=>{'use strict';
window.QJExpression={compile(source){
 try{
  if(typeof source!=='string'||source.length>180)return null;
  const input=source.replace(/Math\./g,'').replace(/π/g,'pi').replace(/\^/g,'**');
  const tokens=input.match(/\*\*|(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?|[A-Za-z]+|[+*/%(),-]/gi)||[];
  if(tokens.join('')!==input.replace(/\s/g,'')||tokens.length>120)return null;
  let pos=0,depth=0;const funcs={sin:Math.sin,cos:Math.cos,tan:Math.tan,abs:Math.abs,sqrt:Math.sqrt,log:Math.log,exp:Math.exp,pow:Math.pow,min:Math.min,max:Math.max};
  const peek=()=>tokens[pos],take=()=>tokens[pos++];
  function atom(){if(++depth>24)throw Error();let fn,t=take();
   if(t==='('){fn=add();if(take()!==')')throw Error();}
   else if(/^\d|^\./.test(t||'')){const v=Number(t);if(!Number.isFinite(v))throw Error();fn=()=>v;}
   else if(t==='x'||t==='X')fn=x=>x;
   else if(t==='pi'||t==='PI')fn=()=>Math.PI;
   else if(t==='e'||t==='E')fn=()=>Math.E;
   else if(Object.hasOwn(funcs,t)&&take()==='('){const args=[add()];while(peek()===','){take();if(args.length>=4)throw Error();args.push(add());}if(take()!==')')throw Error();fn=x=>funcs[t](...args.map(f=>f(x)));}
   else throw Error();depth--;return fn;
  }
  function power(){const left=atom();if(peek()==='**'){take();const right=unary();return x=>left(x)**right(x);}return left;}
  function unary(){if(peek()==='+'||peek()==='-'){const t=take(),v=unary();return t==='-'?x=>-v(x):v;}return power();}
  function mult(){let left=unary();while(['*','/','%'].includes(peek())){const t=take(),a=left,b=unary();left=t==='*'?x=>a(x)*b(x):t==='/'?x=>a(x)/b(x):x=>a(x)%b(x);}return left;}
  function add(){let left=mult();while(peek()==='+'||peek()==='-'){const t=take(),a=left,b=mult();left=t==='+'?x=>a(x)+b(x):x=>a(x)-b(x);}return left;}
  const fn=add();if(pos!==tokens.length)throw Error();return x=>{const y=fn(x);return Number.isFinite(y)?y:null;};
 }catch{return null;}
}};
})();
