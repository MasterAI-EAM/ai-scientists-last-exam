import {T,stage,box,mats,pedestal,plane,label,panel,vessel,setLiquid,ease,mix} from './stage.js';
import {createLab} from './lab.js';
import {createAgentDisplay} from './agent-display.js';
import {stateAt,DURATION,rounds} from './timeline.mjs';
import {drawSignal,drawRecovery,drawDose} from './plots.js';
import {createComparison} from './comparison.js';
await document.fonts.load('600 39px DM');await document.fonts.load('48px Editorial');
const v=stage(),$=id=>document.getElementById(id),txt=(id,s)=>$(id).textContent=s;
function fit(){const k=Math.min(innerWidth/1720,innerHeight/1080);$('board').style.transform='translate('+((innerWidth-1720*k)/2)+'px,'+((innerHeight-1080*k)/2)+'px) scale('+k+')';}fit();addEventListener('resize',fit);
const agent=v.group(-6.6,.2,1.6);pedestal(agent,3.6,2.8);
const icons=await createAgentDisplay(agent,plane,box,mats);
const recipe=panel(agent,3.3,.71,0,.36,1.33,1650);
const labGroup=v.group(-2.6,.14,-2.7);pedestal(labGroup,4.65,3.45);const lab=createLab(labGroup);lab.lab.scale.setScalar(1.13);lab.lab.position.y=.23;
label(labGroup,'TRANSFER · MIX · READ',3.9,.31,0,.235,1.43,true);
const opticalGroup=v.group(1.55,.24,-1.5);pedestal(opticalGroup,1.4,1.25);const sample=vessel(opticalGroup,0,0,'#9b85bc',.29,.77);
const optical=panel(v.world,3.55,2.45,1.6,3.40,-1.8);
const resultGroup=v.group(6.5,.25,-1.7);pedestal(resultGroup,4.75,2.45);box(resultGroup,.3,1.35,.3,mats.chrome,0,.89,-.4,.04);
const result=panel(resultGroup,4.55,3.38,0,2.98,-.4,1400);
const comparison=createComparison(v);
const dose=panel(v.world,3.05,1.98,-5.30,3.18,-2.8,1000);
const route0=v.route([[-5.5,.54,.0],[-5.55,.60,-.7],[-4.98,.58,-1.05],[-4.84,.55,-1.7]]);
const route1=v.route([[.05,.62,-2.5],[.45,.71,-2.5],[.65,.75,-1.6],[1.0,.71,-1.5]],'#91ada7');
const route2=v.route([[2.23,.74,-1.5],[2.9,.80,-1.5],[3.58,.78,-1.7],[4.12,.72,-1.7]]);
const feedback=v.route([[5.46,.62,2.55],[4.4,.14,5.95],[-7.15,.14,5.8],[-7.16,.48,3.06]],'#82ad99');
label(v.world,'COLOUR / SPECTRUM → NEXT DECISION',6.3,.33,-2.50,.24,4.62,true);
const agentTag=v.tag([-7.2,3.38,1.2],'01 / DECIDE','Use the returned observation');
v.tag([-2.55,4.14,-3.2],'02 / EXPERIMENT','The apparatus can change');
const poses={all:{target:[-.1,1.65,.02],ray:[.25,6.2,15.85]},compare:{target:[.45,1.6,1.08],ray:[.15,6.3,15.8]}};
function animateLab(s){const u=s.u;let x=.22,head=.24,z=.13;
 if(u<2.5){const q=ease((u-.9)/.6)*(1-ease((u-1.75)/.65));x+=(-1.12-.22)*q;z+=(-.515-.13)*q;head-=.36*ease((u-1.3)/.22)*(1-ease((u-1.7)/.22));}
 if(u>=2.5&&u<4)head-=.45;
 if(u>=4&&u<4.6){const q=Math.sin((u-4)/.6*Math.PI);head-=.45*q;x+=.025*q*Math.sin(u*14);}
 if(u>=4.6)x=mix(.22,-1.1,(u-4.6)/.4);
 lab.carriage.position.x=x;lab.head.position.set(0,head,z+.89);lab.zGuide.position.z=z+.89;
 lab.camera.position.x=mix(1.13,.43,(u-4.6)/.6);
 lab.drop.visible=s.phase==='dispense'&&u>=2.5;lab.drop.position.set(.22,mix(.71,.59,((u-2.5)*3)%1),.13);lab.drop.material.color.set('#a587b4');
 const fill=ease(s.fill)*s.r.delivered/50,h=.005+.059*fill,col=new T.Color('#e8e0ed').lerp(new T.Color(s.r.colour),ease(s.fill));
 lab.sample.scale.y=h/.06;lab.sample.position.y=.547+h/2;lab.sample.material.color.copy(col);lab.meniscus.position.y=.547+h;lab.meniscus.material.color.copy(col);
 lab.scan.material.opacity=s.scanning?.56:0;lab.beam.material.opacity=s.scanning?.12:0;lab.scan.scale.setScalar(1+.1*Math.sin(u*10));
 return{readerX:lab.camera.position.x,carriageX:x,sampleHeight:h};}
function drawRecipe(s){const c=recipe.ctx;c.fillStyle='#faf6fd';c.fillRect(0,0,recipe.c.width,recipe.c.height);
 c.fillStyle='#8a6aa0';c.font='600 50px DM';c.fillText('COMMAND A',52,86);c.font='600 89px DM';c.fillStyle='#624575';c.textAlign='right';c.fillText((s.intro?'?':s.r.command)+' µL',1598,231);c.textAlign='left';c.font='42px DM';c.fillStyle='#9985a6';c.fillText('Illustrative decision',52,254);recipe.tex.needsUpdate=true;}
function describe(s){const k=s.index,ready=s.observed;txt('phase',s.intro?'THE TASK':s.summary?'THE FINAL CHECK':'EXPERIMENT '+(k+1)+' / 3');
 const headings=['First, establish a baseline.','Same command. Different result.','Use feedback, then check again.'];
 txt('headline',s.summary?'Recovery is an observed outcome.':headings[k]);
 txt('explanation',s.summary?'Compare the new measurement with the trigger-round baseline; do not infer recovery from the command alone.':s.intro?'A hidden transfer change alters the result. Only colour and spectral observations return to the agent.':k===0?'The first measured sample becomes the reference for later observations.':k===1?'The target and command stay fixed. The measured signal changes after an unseen transfer loss.':'The next command changes after feedback. A fresh experiment must confirm whether it worked.');
 txt('metric-label',ready?'ACQUIRED OBSERVATION':'NEXT COMMAND');txt('metric-value',ready?(k===1?'Signal changes':k===2?'Signal recovers':'Baseline recorded'):s.intro?'Result unknown':s.r.command+' µL');txt('metric-detail',ready?'Baseline-normalized optical response · schematic':'Result remains unknown until the reader finishes');
 $('criteria').innerHTML='Evaluator: recovery vs. trigger-round baseline<small>Keep target success and recovery as separate criteria.</small>';
 txt('caption-title',s.summary?'The experiment changes. The agent must adapt.':ready?'Observation → revised decision → measured outcome':'Command → physical transfer → optical observation');txt('caption-text','Hidden volume is shown for explanation; it is not telemetry supplied to the agent.');
 txt('scene-index',({intro:'HIDDEN DRIFT / ONE EXPERIMENT LOOP',decide:'LLM / CHOOSE A COMMAND',dispense:'EXPERIMENT / TRANSFER THE LIQUID',mix:'EXPERIMENT / MIX',align:'OPTICAL READER / ALIGN',scan:'OBSERVE / ACQUIRE SPECTRUM',feedback:'FEEDBACK / RETURN THE OBSERVATION',compare:'EVALUATE / COMPARE THE OUTCOMES',summary:'RECOVERY / MEASURE IT AGAIN'})[s.phase]);txt('scene-foot','Spectra and volume loss are schematic; no benchmark scores are shown.');
 [...$('rounds').children].forEach((e,i)=>e.className=(i===k?'current ':'')+(i<s.count?'done':''));}
$('rounds').innerHTML='<span>01</span><span>02</span><span>03</span>';
function renderAt(t){const s=stateAt(t),focus=ease((s.u-6.6)/1.6)*(s.intro?0:1),a=poses.all,b=poses.compare;
 v.pose(a.target.map((x,i)=>x+(b.target[i]-x)*focus),a.ray.map((x,i)=>x+(b.ray[i]-x)*focus));
 const motion=animateLab(s);drawRecipe(s);drawSignal(optical,s);drawRecovery(result,s);drawDose(dose,s);
 dose.g.visible=s.phase==='dispense';optical.g.visible=true;
 const outcome=comparison.render(s);
 setLiquid(sample,s.observed?1:s.fill,s.r.colour);route0.move(s.phase==='decide'?s.u/.9:-1);route1.move(s.scanning?s.scanProgress:-1);route2.move(s.observed&&s.u<7?(s.u-6.6)/.4:-1);feedback.move(s.feedback);
 agentTag.s.textContent=s.phase==='feedback'?'Observation received':'Use the returned observation';describe(s);v.draw();
 const bounds={models:v.bounds(icons.panelMesh,icons.width,icons.height),command:v.bounds(recipe.screen,recipe.w,recipe.h),spectrum:v.bounds(optical.screen,optical.w,optical.h),result:v.bounds(result.screen,result.w,result.h),dose:dose.g.visible?v.bounds(dose.screen,dose.w,dose.h):null};
 window.currentState={...s,...motion,bounds,agentDisplay:icons.info,outcome,visualAcceptance:false};return window.currentState;}
window.renderAt=renderAt;await document.fonts.ready;renderAt(0);window.ready=true;
if(!new URLSearchParams(location.search).has('render')){const start=performance.now();const tick=n=>{renderAt((n-start)/1000%DURATION);requestAnimationFrame(tick)};requestAnimationFrame(tick);}
