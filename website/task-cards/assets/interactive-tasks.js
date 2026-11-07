function interactiveTaskMarkup(task,heading){
 const stages=task.stages.map((s,i)=>'<button type="button" data-stage="'+i+'" aria-pressed="'+(i===0)+'">'+s.label+'</button>').join('');
 return `<main class="wrap task-detail-main">
  ${heading}
  <section data-task-map="${task.id}" aria-label="${task.title} task map"></section>
  <details class="task-map-extra"><summary>Interactive 3D walkthrough</summary>
  <section class="case interactive-case" data-scene="${task.id}">
   <div class="interactive-body">
    <div class="interactive-visual">
     <div class="interactive-viewport">
      <img class="interactive-poster" src="assets/${task.poster}" alt="${task.videoTitle}">
      <iframe id="experiment-scene" loading="lazy" src="${task.scene}" title="${task.videoTitle}"></iframe>
      <span id="scene-loading" role="status">Preparing the experiment…</span>
     </div>
    </div>
    <aside class="interactive-aside">
     <h2 id="interactive-heading">${task.caseTitle}</h2>
     <p id="interactive-copy">${task.description}</p>
     <span id="scene-target" class="interactive-target"></span>
     <div class="interactive-metric"><span id="interactive-metric-label"></span><strong id="interactive-metric-value"></strong><small id="interactive-metric-detail"></small></div>
     <p id="interactive-criteria"></p>
    </aside>
   </div>
   <div class="interactive-controls">
    <button class="subtle-btn" id="experiment-play" type="button" disabled aria-label="Play experiment">▷ Play</button>
    <div class="interactive-timeline"><input id="experiment-scrub" type="range" min="0" max="5" step="any" value="0" disabled aria-label="Experiment stage" aria-valuetext="Overview"><div class="interactive-stages">${stages}</div></div>
    <span id="experiment-counter">01 / 06</span>
   </div>
   <div class="interactive-foot"><span>${task.caption}</span><a href="${task.official}" target="_blank" rel="noreferrer">Official task ↗</a>${task.film ? `<a href="${task.film}" target="_blank" rel="noreferrer">Experiment footage ↗</a>` : ''}</div>
  </section>
  </details>
 </main>`;
}
addEventListener('DOMContentLoaded',()=>{
 const frame=document.getElementById('experiment-scene');if(!frame)return;
 const task=taskEntries.find(t=>t.id===document.querySelector('.interactive-case').dataset.scene),stages=task.stages;
 const $=id=>document.getElementById(id),buttons=[...document.querySelectorAll('.interactive-stages button')];
 let ready=false,time=0,playing=false,raf=0,baseTime=0,started=0,lastSent=0;
 const phaseAt=t=>{let i=0;while(i<stages.length-1&&t>=stages[i+1].time-.001)i++;return i;};
 function progress(t){const i=phaseAt(t);return i===5?5:i+(t-stages[i].time)/(stages[i+1].time-stages[i].time);}
 function atPosition(value){const i=Math.min(4,Math.floor(value)),f=value-i;return stages[i].time+(stages[i+1].time-stages[i].time)*f;}
 function controls(){const i=phaseAt(time);$('experiment-scrub').value=progress(time);$('experiment-scrub').setAttribute('aria-valuetext',stages[i].label);$('experiment-counter').textContent=String(i+1).padStart(2,'0')+' / 06';buttons.forEach((b,k)=>b.setAttribute('aria-pressed',String(k===i)));}
 function seek(t){time=Math.max(0,Math.min(task.duration-.001,t));controls();if(ready)frame.contentWindow.postMessage({type:'aisle-scene-seek',time},location.origin);}
 function pause(){playing=false;cancelAnimationFrame(raf);$('experiment-play').textContent='▷ Play';$('experiment-play').setAttribute('aria-label','Play experiment');}
 function tick(now){if(!playing)return;const t=baseTime+(now-started)/1000;if(now-lastSent>=50||t>=task.duration-.001){seek(t);lastSent=now;}if(t>=task.duration-.001){pause();return;}raf=requestAnimationFrame(tick);}
 $('experiment-play').addEventListener('click',()=>{if(playing){pause();return;}if(time>=task.duration-.1)seek(0);baseTime=time;started=performance.now();playing=true;$('experiment-play').textContent='Ⅱ Pause';$('experiment-play').setAttribute('aria-label','Pause experiment');raf=requestAnimationFrame(tick);});
 $('experiment-scrub').addEventListener('input',e=>{pause();seek(atPosition(Number(e.target.value)));});
 $('experiment-scrub').addEventListener('keydown',e=>{const delta={ArrowLeft:-.05,ArrowDown:-.05,ArrowRight:.05,ArrowUp:.05,PageDown:-1,PageUp:1}[e.key];if(delta!==undefined||e.key==='Home'||e.key==='End'){e.preventDefault();pause();const pos=e.key==='Home'?0:e.key==='End'?5:Math.max(0,Math.min(5,Number(e.target.value)+delta));seek(atPosition(pos));}});
 buttons.forEach((b,i)=>{b.disabled=true;b.addEventListener('click',()=>{pause();seek(stages[i].time);});});
 const fields={headline:'interactive-heading',explanation:'interactive-copy',metricLabel:'interactive-metric-label',metricValue:'interactive-metric-value',metricDetail:'interactive-metric-detail',criteria:'interactive-criteria',target:'scene-target'};
 addEventListener('message',event=>{
  if(event.source!==frame.contentWindow||event.origin!==location.origin)return;
  const data=event.data;if(!data||!['aisle-scene-ready','aisle-scene-state','aisle-scene-error'].includes(data.type))return;
  if(data.type==='aisle-scene-error'){ready=false;pause();document.querySelector('.interactive-visual').classList.remove('ready');$('experiment-play').disabled=true;$('experiment-scrub').disabled=true;buttons.forEach(b=>b.disabled=true);$('scene-loading').textContent='The interactive scene could not load. Please refresh to try again.';return;}
  if(!ready){ready=true;document.querySelector('.interactive-visual').classList.add('ready');$('experiment-play').disabled=false;$('experiment-scrub').disabled=false;buttons.forEach(b=>b.disabled=false);}
  for(const [key,id] of Object.entries(fields))$(id).textContent=data[key]||'';
  document.querySelector('.interactive-case').dataset.time=data.time;
 });
 frame.addEventListener('load',()=>frame.contentWindow.postMessage({type:'aisle-scene-ping'},location.origin));
 document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
 new IntersectionObserver(entries=>{if(!entries[0].isIntersecting)pause();},{threshold:.02}).observe(document.querySelector('.interactive-case'));
 controls();
});
