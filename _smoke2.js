// 冒烟测试：stub document/echarts，从生成的 HTML 抽取主脚本，跑 init() 并测试筛选引擎
const fs = require('fs');
const html = fs.readFileSync('Olist电商运营分析看板.html', 'utf8');

// 抽取所有 <script>...</script>，取最后一个（主脚本，含 FACT/DATA/逻辑）
const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
let code = blocks[blocks.length - 1];
if (code.length < 1000) { console.error('主脚本抽取失败，长度=', code.length); process.exit(1); }

// ---- stub ----
class El {
  constructor(id){ this.id=id; this.children=[]; this._html=''; this.style={}; this.dataset={};
    this.classList={_s:new Set(),add(c){this._s.add(c);},remove(c){this._s.delete(c);},
      toggle(c,f){if(f===undefined)f=!this._s.has(c); f?this._s.add(c):this._s.delete(c); return f;},
      contains(c){return this._s.has(c);}}; }
  set innerHTML(v){this._html=v;} get innerHTML(){return this._html||'';}
  set textContent(v){this._text=v;} get textContent(){return this._text||'';}
  appendChild(c){this.children.push(c);return c;}
  set onclick(f){this._onclick=f;} get onclick(){return this._onclick;}
  addEventListener(){} querySelectorAll(){return [];}
}
const els={};
global.document={ getElementById:id=>(els[id]=els[id]||new El(id)),
  createElement:()=>new El('n'), createTextNode:t=>({nodeType:3,textContent:t}),
  querySelectorAll:()=>[], addEventListener(){} };
global.window={addEventListener(){}};
let n=0, errs=[], warns=[], optCount=0;
// 深度扫描 option 中的 undefined（真实浏览器里 undefined 会让 ECharts 或 formatter 崩溃）
function deepScan(o,path,id,bag){
  if(o===undefined){ bag.push('undefined@'+id+':'+path); return; }
  if(o===null||typeof o!=='object') return;
  if(Array.isArray(o)){ o.forEach((v,i)=>deepScan(v,path+'['+i+']',id,bag)); return; }
  for(const k of Object.keys(o)) deepScan(o[k],path+'.'+k,id,bag);
}
// 用合成参数调用 formatter / 动态颜色函数，模拟真实 ECharts 渲染期行为
function tryDyn(o,id,bag){
  const x0=(o.xAxis&&o.xAxis.data&&o.xAxis.data[0]);
  (o.series||[]).forEach((s,si)=>{
    if(!Array.isArray(s.data)||s.data.length===0) return; // 空 series 不调用 formatter（真实浏览器也不会触发）
    const d0=s.data[0];
    const mock={seriesName:s.name||'',name:x0!=null?x0:'0',
      value:Array.isArray(d0)?d0[1]:(d0&&typeof d0==='object'&&d0.value!==undefined?d0.value:0),
      data:d0,dataIndex:0,percent:50};
    const tag=id+'#'+(s.name||si);
    try{ if(s.label&&typeof s.label.formatter==='function') s.label.formatter(mock); }catch(e){ bag.push('label.formatter异常@'+tag+': '+e.message); }
    try{ if(s.label&&typeof s.label.position==='function') s.label.position(mock); }catch(e){ bag.push('label.position异常@'+tag+': '+e.message); }
    try{ if(s.itemStyle&&typeof s.itemStyle.color==='function') s.itemStyle.color(mock); }catch(e){ bag.push('itemStyle.color异常@'+tag+': '+e.message); }
    try{ if(s.markLine&&s.markLine.label&&typeof s.markLine.label.formatter==='function') s.markLine.label.formatter(mock); }catch(e){ bag.push('markLine.formatter异常@'+tag+': '+e.message); }
  });
  try{ if(o.tooltip&&typeof o.tooltip.formatter==='function'){
    const s0=(o.series||[]).find(s=>Array.isArray(s.data)&&s.data.length)||{};
    if(!s0.data) return; // 全部 series 为空：真实浏览器不会触发 tooltip
    const d0=s0.data[0];
    const mock={seriesName:s0.name||'',name:x0!=null?x0:'0',value:1,data:d0,dataIndex:0,axisValue:'0',percent:50};
    if(o.tooltip.trigger==='axis') o.tooltip.formatter([mock]); else o.tooltip.formatter(mock);
  }}catch(e){ bag.push('tooltip.formatter异常@'+id+': '+e.message); }
  [o.xAxis,o.yAxis].flat().filter(Boolean).forEach((ax,ai)=>{
    try{ if(ax.axisLabel&&typeof ax.axisLabel.formatter==='function') ax.axisLabel.formatter(0,0); }catch(e){ bag.push('axisLabel.formatter异常@'+id+'ax'+ai+': '+e.message); }
  });
}
global.echarts={ init:(el)=>{ const c={ _id:el&&el.id, setOption(o){
      optCount++; if(!o||typeof o!=='object'){errs.push('非对象option');return;}
      (o.series||[]).forEach((s,i)=>{ if(Array.isArray(s.data)&&s.data.length===0) warns.push('空series@'+(c._id||'?')+'#'+(s.name||i)); });
      deepScan(o,'opt',c._id||'?',errs);
      tryDyn(o,c._id||'?',errs);
    }, on(ev,f){ if(ev==='click') c._click=f; }, resize(){}, group:'' }; return c; },
  connect(){} };
global.setTimeout=f=>{try{f()}catch(e){}};
global.Math=Math;

// 暴露内部函数以便测试筛选路径与点击下钻
code += "\n;globalThis.__T={compute,renderAll,FILTER,CH,wireClicks,setFilter(y,s,c){FILTER.year=y;FILTER.states=new Set(s);FILTER.cats=new Set(c);renderAll();},getLAST(){return LAST;}};";

try{
  eval(code);
  console.log('① init() 执行成功，无运行时异常');
  console.log('   图表 setOption 次数：', optCount);
  if(errs.length){
    console.log('   ⚠ 检测到 '+errs.length+' 个致命隐患（undefined 字段 / formatter 异常）：');
    [...new Set(errs)].slice(0,15).forEach(e=>console.log('     - '+e));
    process.exit(1);
  } else console.log('   所有图表均有数据，option 无 undefined 字段，formatter 均可执行');
  if(warns.length) console.log('   （提示）空 series：'+[...new Set(warns)].slice(0,5).join(' | '));
  const ids=['kpi0','kpi1','kpi2','kpi3','kpi4','kpi5','insights','recos','hol_insights','t_hol','t_state','t_rfm','t_pq','t_pg','t_state_cust','filterInfo'];
  ids.forEach(id=>{const e=els[id]; console.log(`   #${id}: ${(e?(e.innerHTML||e.textContent||'').length:0)} 字符`);});

  // ② 筛选引擎测试
  function check(name, y, s, c){
    globalThis.__T.setFilter(y,s,c);
    const A=globalThis.__T.getLAST();
    const ok = A && A.kpi && typeof A.kpi.gmv==='number';
    console.log(`   筛选[${name}] -> 订单=${A.kpi.orders} GMV=R$ ${Math.round(A.kpi.gmv).toLocaleString()} 州数=${A.state_gmv.length} 品类数=${A.category.length} 卖家=${A.seller_top.length}`);
    if(!ok) throw new Error('compute 返回异常: '+name);
  }
  console.log('② 筛选引擎：');
  const ALL=globalThis.__T.compute();
  console.log('   全量 -> 订单', ALL.kpi.orders, 'GMV', Math.round(ALL.kpi.gmv).toLocaleString());
  console.log('   seller_state=', ALL.seller_state.length, JSON.stringify(ALL.seller_state.slice(0,3)));
  console.log('   seller_top[0]=', JSON.stringify(ALL.seller_top[0]));
  check('仅2017年', 2017, [], []);
  check('仅2018年', 2018, [], []);
  check('州=SP', 'all', [0], []);
  check('州=SP+RJ', 'all', [0,1], []);
  check('品类=health_beauty(idx0)', 'all', [], [0]);
  check('2017+SP+健康美容', 2017, [0], [0]);
  check('不可能组合(空)', 2017, [0], [50]); // 该州该品类可能为空
  console.log('③ 筛选引擎全部通过，无运行时异常');

  // ④ 点击下钻测试（模拟点击州柱 / 品类柱）
  console.log('④ 点击下钻：');
  const T=globalThis.__T;
  T.setFilter('all',[],[]);
  if(T.CH.c_state&&T.CH.c_state._click){
    T.CH.c_state._click({data:{code:0}});
    console.log('   点击州柱(SP) -> FILTER.states='+JSON.stringify([...T.FILTER.states]));
    if(T.FILTER.states.size!==1||!T.FILTER.states.has(0)) throw new Error('州下钻未生效');
  } else throw new Error('c_state 未绑定点击事件');
  if(T.CH.c_cat_gmv&&T.CH.c_cat_gmv._click){
    T.CH.c_cat_gmv._click({data:{code:0}});
    console.log('   点击品类柱 -> FILTER.cats='+JSON.stringify([...T.FILTER.cats]));
    if(T.FILTER.cats.size!==1||!T.FILTER.cats.has(0)) throw new Error('品类下钻未生效');
  } else throw new Error('c_cat_gmv 未绑定点击事件');
  if(errs.length){ console.log('   ⚠ 下钻后出现致命隐患：'+[...new Set(errs)].slice(0,10).join(' | ')); process.exit(1); }
  if(warns.length) console.log('   （提示）下钻后空 series：'+[...new Set(warns)].slice(0,8).join(' | '));
  console.log('⑤ 全部测试通过');
}catch(e){ console.error('❌ 运行时错误：', e.message); console.error(e.stack.split('\n').slice(0,5).join('\n')); process.exit(1); }
