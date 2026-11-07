const isDetail = document.body.dataset.page === 'detail';
const app = document.getElementById('app');
const embedded = document.body.dataset.page === 'catalog'
  && new URLSearchParams(location.search).has('embed');
const isVideoTask = document.body.dataset.page === 'video-task';
const taskEntries = [
 {id:'colour',title:'Experimental optimisation',description:'Propose formulations and use experimental feedback to match a target colour.',tags:["Colour matching", "4D / 8D"],media:"ILLUSTRATED EXPERIMENTAL WORKFLOW",href:'color-matching.html',video:'colour-matching.mp4?v=neutral-workflow-3',poster:'colour-matching-opening-frame.webp'},
 {"id":"constraints","title":"Constraint adherence","description":"Match a target colour while keeping every executed experiment outside the forbidden band.","tags":["Colour matching", "Constraints"],"media":"INTERACTIVE 3D","href":"constraint-adherence.html","poster":"constraint-adherence-reviewed.webp","caseTitle":"Can the agent match a colour safely?","videoTitle":"Safety-constrained colour matching","caption":"GPT-5.5 source case · Illustrative replay","note":"Illustrative replay based on the supplied presentation. Colour-error values are approximately digitized; recipes, actions and the separate spectrum example are illustrative. The five equal model icons represent examples evaluated separately, not participants in a joint run.","official":"../tasks.html#safety","scene":"assets/interactive/constraints/src/index.html?render","duration":36,"stages":[{"label":"Overview","time":0},{"label":"Experiment","time":4.2},{"label":"Observe","time":5.7},{"label":"Violation","time":15.5},{"label":"Safe match","time":22.5},{"label":"Verdict","time":34}]},
 {"id":"robustness","title":"Adaptive robustness","description":"Use physical measurements to adapt to hidden drift and changing transfer conditions.","tags":["Hidden drift", "Measured recovery"],"media":"INTERACTIVE 3D","href":"adaptive-robustness.html","poster":"adaptive-robustness-reviewed.webp","film":"https://yangsen-hub-dot.github.io/AISLE/assets/experiments/bears.mp4","caseTitle":"Same command. Different result.","videoTitle":"Hidden pipetting drift and measured recovery","caption":"Sequential measured samples · Illustrative drift","note":"Illustrative one-channel example: commands 50 / 50 / 62.5 µL, delivered volumes 50 / 40 / 50 µL and schematic optical signals 100 / 80 / 100%. Delivered volume is viewer explanation, not agent telemetry. Recovery against the trigger-round baseline is distinct from target success. The five model icons are examples evaluated separately; no measured model scores are shown.","official":"../tasks.html#robustness","scene":"assets/interactive/robustness/src/index.html?render","duration":38,"stages":[{"label":"Overview","time":0},{"label":"Baseline","time":9.4},{"label":"Hidden drift","time":19.4},{"label":"Adapt","time":24},{"label":"Recovery","time":30.4},{"label":"Evaluate","time":36}]},
 {"id":"spectral","title":"Multimodal spectral reasoning","description":"Use spectral observations to guide formulations or infer chemical properties.","tags":["Spectral matching", "pKa inference"],"media":"INTERACTIVE 3D","href":"spectral-inference.html","poster":"spectral-inference-reviewed.webp","caseTitle":"Infer a hidden chemical transition.","videoTitle":"Spectral pKa inference","caption":"Synthetic spectra · Conditional inference","note":"The video illustrates four queries to a fixed synthetic spectral library within an eight-action budget. The pKa estimate and 95% interval are conditional on known spectral bases and noise, not measured performance on an unknown indicator. The separate interactive scene depicts sample preparation. Model icons are examples evaluated separately.","official":"../tasks.html#multimodal","scene":"assets/interactive/spectral/src/index.html?render","duration":40,"stages":[{"label":"Overview","time":0},{"label":"Select pH","time":2.3},{"label":"Prepare","time":4.1},{"label":"Spectrum","time":8},{"label":"Compare","time":24.4},{"label":"Infer pKa","time":36}]},
 {id:'solid',title:'Solid electrolyte prediction',description:'Predict ionic conductivity, XRD pattern group and product grade from historical experimental records.',tags:["Materials benchmark", "3D evaluation"],media:"INTERACTIVE 3D",href:'solid-electrolyte.html',video:'solid-electrolyte.mp4?v=arrows-1'},
 {id:'quantum-dot',cardId:'task-quantum-dot',title:'Quantum Dot Formulation Optimisation',description:'Use measured spectra and a limited query budget to find the strongest fluorescence at 600 nm.',tags:["Experimental optimisation", "48 formulations"],media:"PROPOSED TASK · WORKFLOW VIDEO",href:'quantum-dot.html',poster:'quantum-dot-workflow-card.webp?v=labels-1'},
 {id:'buchwald-hartwig',cardId:'task-buchwald-hartwig',title:'Buchwald–Hartwig Reaction Optimisation',description:'Choose reaction conditions and use measured yield feedback to find a successful C–N coupling within four experiments.',tags:["Experimental optimisation", "4 experiments"],media:"PROPOSED TASK · WORKFLOW VIDEO",href:'buchwald-hartwig.html',poster:'buchwald-hartwig-workflow-card.webp'}
];
// Catalogue facts describe the task protocol, rather than parameters in its film.
const catalogueFacts = {
 colour: { collection: 'benchmark', status: 'AISLE benchmark', environment: 'Wet lab + simulation', label: 'Budget', value: '12 scored experiments' },
 constraints: { collection: 'benchmark', status: 'AISLE benchmark', environment: 'Simulation', label: 'Safe completion', value: 'ΔE₀₀ ≤ 1 · zero violations' },
 robustness: { collection: 'benchmark', status: 'AISLE benchmark', environment: 'Physical experiments', label: 'Resin target', value: '500 ± 10 μL' },
 spectral: { collection: 'benchmark', status: 'AISLE benchmark', environment: 'Measured spectra + library queries', label: 'Matching target', value: 'RMSE ≤ 0.100' },
 solid: { collection: 'materials', status: 'Materials benchmark', environment: 'Historical experimental records', label: 'Outputs', value: 'Conductivity, XRD group, grade' },
 'quantum-dot': { collection: 'proposed', status: 'Proposed task', environment: 'Measured-data replay', label: 'Target', value: 'Fluorescence at 600 nm' },
 'buchwald-hartwig': { collection: 'proposed', status: 'Proposed task', environment: 'Measured-data replay', label: 'Budget', value: '4 experimental queries' },
};
taskEntries.forEach((task, index) => Object.assign(task, catalogueFacts[task.id], { number: String(index + 1).padStart(2, '0') }));
const defaultFeature = taskEntries.find(task => task.id === 'solid');
const header = '<header class="header wrap"><a class="brand" href="https://yangsen-hub-dot.github.io/AISLE/index.html" aria-label="AISLE home"><img class="brand-logo" src="../assets/brand/aisle-logo-white.svg" alt="AISLE logo" width="1226" height="222"></a><nav aria-label="Main navigation"><a href="https://yangsen-hub-dot.github.io/AISLE/index.html">Home</a><a class="active" href="../tasks.html#task-cards" aria-current="page">Tasks</a><a href="https://yangsen-hub-dot.github.io/AISLE/leaderboard.html">Leaderboard</a></nav></header>';
const footer = '<footer class="site-footer wrap"><a href="../tasks.html#task-protocols">Protocols &amp; scoring ↗</a></footer>';
function taskFeatureMarkup() {
 const options = taskEntries.map(task => `<option value="${task.id}" data-href="${task.href}" data-number="${task.number}"${task === defaultFeature ? ' selected' : ''}>${task.title}</option>`).join('');
 return `<section class="task-map-feature" id="featured-case" aria-labelledby="featured-title">
   <div class="section-heading">
     <p class="catalog-eyebrow">Featured case <span aria-hidden="true">·</span> <span data-feature-number>Task ${defaultFeature.number}</span></p>
     <h2 id="featured-title" data-feature-heading>${defaultFeature.title}</h2>
   </div>
   <div data-feature-map></div>
   <div class="task-map-feature-picker">
     <label for="feature-task">Explore a workflow</label>
     <select id="feature-task" data-map-chooser>${options}</select>
     <a class="small-link" data-feature-detail href="${defaultFeature.href}">View task details <span aria-hidden="true">↗</span></a>
   </div>
 </section>`;
}

function taskTags(task) {
 return `<div class="task-tags">${task.tags.map(tag => `<span>${tag}</span>`).join('')}</div>`;
}

function renderCardArt(task) {
 if (!task.video) return `<img src="assets/${task.poster}" alt="" loading="lazy" decoding="async" width="760" height="475">`;
 const preview = task.poster ? `poster="assets/${task.poster}" preload="none" data-cover-preview` : 'preload="metadata"';
 return `<video src="assets/workflows/${task.video}#t=0.001" ${preview} muted playsinline aria-hidden="true" tabindex="-1"></video>`;
}

function renderCards() {
 return taskEntries.map(task => `<article class="task-card" id="task-${task.id}" data-task-entry="${task.id}" data-collection="${task.collection}" aria-labelledby="title-${task.id}">
   <div class="card-art">${renderCardArt(task)}<span class="card-number">TASK ${task.number}</span></div>
   <div class="card-content">
     <div class="card-status-row"><span class="task-status">${task.status}</span><span class="card-previewing" hidden>In preview</span></div>
     <div class="card-title-row"><h3 id="title-${task.id}"><a class="task-title-link" href="${task.href}">${task.title}</a></h3></div>
     <p>${task.description}</p>
     <dl class="task-fact"><dt>${task.label}</dt><dd>${task.value}</dd></dl>
     ${taskTags(task)}
     <div class="card-footer"><button type="button" class="card-preview" data-preview-task="${task.id}" aria-label="Preview ${task.title} workflow"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3.5 12 8l-7 4.5z"/></svg>Preview workflow</button><span class="card-detail" aria-hidden="true">View task ↗</span></div>
   </div>
 </article>`).join('');
}

function renderTaskList() {
 return `<div class="task-list">${taskEntries.map(task => `<a class="list-row" href="${task.href}" data-task-entry="${task.id}" data-collection="${task.collection}">
   <span class="list-number" aria-hidden="true">${task.number}</span>
   <div class="list-main"><span class="task-status">${task.status}</span><strong>${task.title}</strong><p>${task.description}</p><span class="list-environment">${task.environment}</span></div>
   <span class="list-fact"><small>${task.label}</small>${task.value}</span>
   <span class="list-arrow" aria-hidden="true">↗</span>
 </a>`).join('')}</div>`;
}

const catalog = `<main class="wrap catalogue-main">
 <section class="catalog-intro" aria-labelledby="catalog-title">
   <div><h1 id="catalog-title" class="catalog-title">Scientific Tasks</h1><p>Explore how AI agents plan experiments, interpret observations, and revise decisions.</p></div>
 </section>
 ${taskFeatureMarkup()}
 <section class="catalog-section" id="task-library" aria-labelledby="all-card-title">
   <h2 id="all-card-title">Explore tasks</h2>
   <div class="catalog-views" role="group" aria-label="Task browsing mode">
     <button type="button" id="visual-tab" aria-pressed="false" aria-controls="visual-panel"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="7" height="6" rx="1"/><rect x="14" y="4" width="7" height="6" rx="1"/><rect x="3" y="14" width="7" height="6" rx="1"/><rect x="14" y="14" width="7" height="6" rx="1"/></svg><span>Cards</span><span aria-hidden="true">↗</span></button>
     <button type="button" id="list-tab" aria-pressed="false" aria-controls="list-panel"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h13M3 6h1M3 12h1M3 18h1"/></svg><span>List</span><span aria-hidden="true">↗</span></button>
   </div>
   <div id="task-results" hidden>
   <div class="catalog-toolbar">
     <label class="task-search"><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5"/><path d="m13 13 4 4"/></svg><input id="task-search" type="search" placeholder="Search tasks…" aria-label="Search tasks" autocomplete="off" maxlength="160"></label>
     <span id="task-result-count" role="status" aria-atomic="true">${taskEntries.length} tasks</span>
   </div>
   <section id="visual-panel" aria-labelledby="visual-tab" hidden><div class="card-grid">${renderCards()}</div></section>
   <section id="list-panel" aria-labelledby="list-tab" hidden>${renderTaskList()}</section>
   <div class="catalog-empty" id="task-empty" hidden><h3>No tasks found</h3><p>Try a different keyword or browse all seven tasks.</p><button type="button" id="clear-task-search">Clear search</button></div>
   <p class="catalog-footnote">Proposed tasks are workflow proposals and are not included in AISLE benchmark scores.</p>
   </div>
 </section>
 <p class="catalog-protocols"><a class="small-link" href="../tasks.html#task-protocols">Protocols &amp; scoring <span aria-hidden="true">↗</span></a></p>
</main>`;
function taskDetailHeading(task, back) {
 return `<section class="detail-intro">
  ${back}
  <p class="task-detail-label">Task ${task.number} · ${task.status}</p>
  <h1 class="detail-title" data-detail-case-heading>${task.title}</h1>
 </section>`;
}
const taskBack = '<a class="back-link" href="../tasks.html#task-cards">← Back to task cards</a>';
const detail = `<main class="wrap task-detail-main">
 ${taskDetailHeading(taskEntries[0], taskBack)}
 <section data-task-map="colour" aria-label="Colour-matching task map"></section>
</main>`;
function videoTaskMarkup() {
 const id = document.body.dataset.task || new URLSearchParams(location.search).get('task');
 const task = taskEntries.find(entry => entry.id === id && entry.scene);
 if (!task) return '<main class="wrap task-detail-main"><section class="detail-intro">'+taskBack+'<h1 class="detail-title">Case not found</h1></section></main>';
 document.title = task.title + ' · AISLE task card';
 return interactiveTaskMarkup(task, taskDetailHeading(task, taskBack));

}
if (embedded) {
 document.body.classList.add('catalog-embedded');
 app.innerHTML = catalog;
 for (const link of app.querySelectorAll('a[href]')) link.target = '_top';
} else {
 app.innerHTML = (isVideoTask ? videoTaskMarkup() : isDetail ? detail : header + catalog)
   + footer;
}
if (isVideoTask) {
 const selectedId=document.body.dataset.task || new URLSearchParams(location.search).get('task');
 const note=taskEntries.find(task=>task.id===selectedId)?.note;
 if(note){const details=document.createElement('details');details.className='interactive-source';const summary=document.createElement('summary');summary.textContent='About this illustration';const p=document.createElement('p');p.textContent=note;details.append(summary,p);document.querySelector('main').append(details);}
}
if(document.body.dataset.page==='catalog'){
 const modes={cards:document.getElementById('visual-tab'),list:document.getElementById('list-tab')};
 const results=document.getElementById('task-results');
 const search=document.getElementById('task-search');
 const chooser=document.querySelector('[data-map-chooser]');
 const cover=document.querySelector('[data-cover-preview]');
 const coverCard=cover.closest('.task-card');
 const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
 const canHover=matchMedia('(any-hover: hover)');
 function syncCover(){
  const interacting=(canHover.matches&&coverCard.matches(':hover'))||coverCard.matches(':focus-within');
  if(!reducedMotion.matches&&!document.hidden&&coverCard.getClientRects().length&&interacting){
   if(cover.paused)cover.play().catch(()=>{});
  }else cover.pause();
 }
 for(const event of ['pointerenter','pointerleave','focusin','focusout']){
  coverCard.addEventListener(event,()=>requestAnimationFrame(syncCover));
 }
 document.addEventListener('catalog-view-change',syncCover);
 document.addEventListener('visibilitychange',syncCover);
 reducedMotion.addEventListener('change',syncCover);
 // Embedded and standalone catalogues share the same bookmarkable browsing state.
 let stateWindow=window;
 if(embedded){try{if(window.parent.location.origin===location.origin)stateWindow=window.parent;}catch{}}
 const initial=new URL(stateWindow.location.href).searchParams;
 const featureFrom=params=>taskEntries.find(task=>task.id===params.get('task'))?.id??defaultFeature.id;
 let selected=featureFrom(initial);
 let view='';
 chooser.value=selected;
 search.value=(initial.get('q')||'').slice(0,160);
 const normalize=value=>value.normalize('NFKC').toLowerCase().replace(/[–—-]/g,' ');
 const searchable=new Map(taskEntries.map(task=>[task.id,normalize([task.title,task.description,...task.tags,task.status,task.environment,task.label,task.value].join(' '))]));
 let restoringHistory=false;
 function saveState(){
  const url=new URL(stateWindow.location.href);
  if(!restoringHistory){
   url.searchParams.delete('collection');
   for(const [key,value] of Object.entries({task:selected===defaultFeature.id?'':selected,q:search.value.trim(),view})){
    if(value)url.searchParams.set(key,value);else url.searchParams.delete(key);
   }
   stateWindow.history.replaceState(stateWindow.history.state,'',url);
  }
  app.querySelectorAll('a[href]').forEach(link=>{
   const destination=new URL(link.href);
   if(destination.origin===url.origin&&destination.pathname.endsWith('/tasks.html')&&destination.hash){
    destination.search=url.search;
    if(!embedded){destination.searchParams.delete('embed');destination.searchParams.delete('v');}
    link.href=destination.href;
   }
  });
 }
 function markPreview(){
  document.querySelectorAll('.task-card').forEach(card=>{
   const active=card.dataset.taskEntry===selected;
   card.classList.toggle('is-previewed',active);
   card.querySelector('.card-previewing').hidden=!active;
   card.querySelector('[data-preview-task]').setAttribute('aria-pressed',String(active));
  });
 }
 function filterTasks(persist=true){
  const terms=normalize(search.value.trim()).split(/\s+/).filter(Boolean);
  const matches=new Set(taskEntries.filter(task=>terms.every(term=>searchable.get(task.id).includes(term))).map(task=>task.id));
  document.querySelectorAll('[data-task-entry]').forEach(entry=>entry.hidden=!matches.has(entry.dataset.taskEntry));
  document.getElementById('task-result-count').textContent=`${matches.size} ${matches.size===1?'task':'tasks'}${matches.size===taskEntries.length?'':` of ${taskEntries.length}`}`;
  document.getElementById('task-empty').hidden=matches.size>0;
  syncCover();
  if(persist)saveState();
 }
 function switchView(mode,persist=true){
  view=mode;
  results.hidden=!mode;
  for(const [name,button] of Object.entries(modes)){
   const active=name===mode;
   button.setAttribute('aria-pressed',String(active));
   document.getElementById(button.getAttribute('aria-controls')).hidden=!active;
  }
  document.dispatchEvent(new CustomEvent('catalog-view-change',{detail:{visual:mode==='cards'}}));
  if(persist)saveState();
 }
 function initialView(params){
  if(!embedded && taskEntries.some(task=>location.hash===`#task-${task.id}`))return 'cards';
  if(params.get('view')==='list')return 'list';
  return params.get('view')==='cards'||params.has('q')||params.has('collection')?'cards':'';
 }
 for(const [mode,button] of Object.entries(modes))button.addEventListener('click',()=>switchView(mode));
 search.addEventListener('input',()=>filterTasks());
 document.getElementById('clear-task-search').addEventListener('click',()=>{search.value='';filterTasks();search.focus();});
 document.querySelectorAll('[data-preview-task]').forEach(button=>button.addEventListener('click',()=>{
  chooser.value=button.dataset.previewTask;
  chooser.dispatchEvent(new Event('change'));
  const feature=document.getElementById('featured-case');
  feature.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  const heading=document.getElementById('featured-title');
  heading.tabIndex=-1;heading.focus({preventScroll:true});
 }));
 document.addEventListener('catalog-feature-change',event=>{selected=event.detail.task;markPreview();saveState();});
 document.addEventListener('catalog-reveal-task',()=>{search.value='';switchView('cards',false);filterTasks();});
 stateWindow.addEventListener('popstate',()=>{
  const params=new URL(stateWindow.location.href).searchParams;
  restoringHistory=true;
  try{
   const nextTask=featureFrom(params);
   search.value=(params.get('q')||'').slice(0,160);
   switchView(initialView(params),false);
   filterTasks(false);
   if(chooser.value!==nextTask){chooser.value=nextTask;chooser.dispatchEvent(new Event('change'));}
   selected=nextTask;markPreview();saveState();
  }finally{restoringHistory=false;}
 });
 switchView(initialView(initial),false);
 filterTasks(false);
 markPreview();
}
