const {DURATION}=await import(new URL('timeline.mjs',location.href).href);
const $=id=>document.getElementById(id);
const text=id=>$(id)?.textContent.trim()||'';
const origin=location.origin;
let loaded=false;
function resize(){const scale=innerWidth/1664;$('scene').style.transform='scale('+scale+')';}
addEventListener('resize',resize);
function send(type){
 const s=window.currentState;
 parent.postMessage({type,time:s.t,duration:DURATION,phase:text('phase'),headline:text('headline'),explanation:text('explanation'),metricLabel:text('metric-label'),metricValue:text('metric-value'),metricDetail:text('metric-detail'),criteria:text('criteria'),caption:text('caption-title'),captionText:text('caption-text'),target:$('target')?.innerText||'',count:s.count??s.points?.length??0,final:Boolean(s.summary)},origin);
}
function render(time){window.renderAt(Math.max(0,Math.min(DURATION-.001,time)));resize();send('aisle-scene-state');}
addEventListener('message',event=>{
 if(event.source!==parent||event.origin!==origin||!loaded)return;
 if(event.data?.type==='aisle-scene-seek'&&Number.isFinite(event.data.time))render(event.data.time);
 if(event.data?.type==='aisle-scene-ping')send('aisle-scene-ready');
});
const started=performance.now();
function ready(){
 if(window.ready&&window.renderAt){loaded=true;resize();window.renderAt(0);send('aisle-scene-ready');}
 else if(performance.now()-started<45000)setTimeout(ready,50);
 else parent.postMessage({type:'aisle-scene-error'},origin);
}
ready();
