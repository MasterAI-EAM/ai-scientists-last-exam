import * as T from 'three';
import {RoomEnvironment} from './vendor/RoomEnvironment.js';
import {createLab} from './lab.js';
import {renderLab} from './apparatus-motion.js';
import {box,cylinder,ring,material,dark,steel,edge,gold,blue} from './geometry.js';
import {ROUNDS} from './timeline.mjs';
import {createAgentDisplay} from './agent-display.js';
await document.fonts.load('600 39px DM');
await document.fonts.load('48px Editorial');
const canvas=document.getElementById('world');
const renderer=new T.WebGLRenderer({canvas,antialias:true,alpha:true,preserveDrawingBuffer:true});
renderer.setSize(2496,981,false);renderer.setPixelRatio(1);renderer.shadowMap.enabled=true;renderer.shadowMap.type=T.PCFSoftShadowMap;renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;
const world=new T.Scene(),camera=new T.PerspectiveCamera(34,1664/654,.1,100);
const env=new T.PMREMGenerator(renderer);world.environment=env.fromScene(new RoomEnvironment(),.03).texture;world.environmentIntensity=.5;
world.add(new T.HemisphereLight(0xffffff,0xa497b9,1.65));
const sun=new T.DirectionalLight(0xfff7ef,2.7);sun.position.set(-7,13,9);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-13,right:13,top:12,bottom:-12,near:.1,far:40});sun.shadow.normalBias=.03;sun.shadow.bias=-.0001;world.add(sun);
const rim=new T.DirectionalLight(0xd8c8f5,1.75);rim.position.set(7,6,-7);world.add(rim);
const mats={ceramic:material('#eee7f4',.13,.4),deep:material('#594467',.32,.3),lilac:material('#b39acb',.28,.35),chrome:material('#a89bb7',.64,.28),sage:material('#c4d8ce',.12,.45),rose:material('#c891a7',.22,.4),purple:material('#9b85bc',.25,.25)};
dark.color.set('#635371');steel.color.set('#b6aebf');edge.color.set('#9f8fae');gold.color.set('#bc9dc9');blue.color.set('#9db7c7');
const ground=new T.Mesh(new T.PlaneGeometry(70,70),new T.ShadowMaterial({color:0x6d537b,opacity:.22}));ground.rotation.x=-Math.PI/2;ground.position.y=-.4;ground.receiveShadow=true;world.add(ground);
function group(x,y,z){const g=new T.Group();g.position.set(x,y,z);world.add(g);return g;}
function texturePlane(parent,tex,w,h,x,y,z){tex.colorSpace=T.SRGBColorSpace;tex.anisotropy=8;const mesh=new T.Mesh(new T.PlaneGeometry(w,h),new T.MeshBasicMaterial({map:tex,toneMapped:false,transparent:true}));mesh.position.set(x,y,z);parent.add(mesh);return mesh;}
function label(parent,lines,w,h,x,y,z,flat=false){const c=document.createElement('canvas');c.width=1000;c.height=Math.round(1000*h/w);const ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);ctx.textAlign='center';ctx.textBaseline='middle';lines.forEach((s,i)=>{ctx.fillStyle=i?'#887095':'#6d4e86';ctx.font=(i?'400 ':'600 ')+(i?32:39)+'px DM';ctx.fillText(s,500,(i+.5)*c.height/lines.length,960);});const p=texturePlane(parent,new T.CanvasTexture(c),w,h,x,y,z);if(flat)p.rotation.x=-Math.PI/2;return p;}
function pedestal(parent,w,d){box(parent,w,.25,d,mats.chrome,0,0,0,.22);box(parent,w-.08,.08,d-.08,mats.ceramic,0,.16,0,.2);}
const agent=group(-6.6,.2,1.6);pedestal(agent,3.6,2.8);
const agentDisplay=await createAgentDisplay(agent,texturePlane,box,mats);
const recipeCanvas=document.createElement('canvas');recipeCanvas.width=1650;recipeCanvas.height=355;const recipeCtx=recipeCanvas.getContext('2d'),recipeTex=new T.CanvasTexture(recipeCanvas);
const recipeBack=box(agent,3.4,.12,.79,mats.lilac,0,.36,1.35,.1);recipeBack.rotation.x=Math.PI/2;
const recipePlane=texturePlane(agent,recipeTex,3.3,.71,0,.36,1.425);
const labGroup=group(-2.75,.14,-2.7);pedestal(labGroup,5.4,3.9);const apparatus=createLab(labGroup);apparatus.lab.scale.setScalar(1.35);apparatus.lab.position.y=.23;
label(labGroup,['DISPENSE · MIX · MEASURE'],4.5,.37,0,.235,1.68,true);
const sampleGroup=group(1.25,.68,-1.6);sampleGroup.scale.setScalar(1.5);
cylinder(sampleGroup,.28,.09,mats.chrome,0,0,0);
const sampleLiquid=cylinder(sampleGroup,.225,.32,new T.MeshPhysicalMaterial({color:'#9b85bc',roughness:.19,metalness:.03,transparent:true,opacity:.8}),0,.20,0);
ring(sampleGroup,.255,.013,mats.chrome,0,.39,0);
const sampleGlass=new T.Mesh(new T.CylinderGeometry(.27,.27,.40,48,1,true),new T.MeshPhysicalMaterial({color:'#faf5ff',transparent:true,opacity:.26,roughness:.12,metalness:.04,side:T.DoubleSide,depthWrite:false}));sampleGlass.position.y=.21;sampleGroup.add(sampleGlass);
const disc=group(1.1,.26,2.0);
cylinder(disc,2.6,.16,mats.chrome,0,.05,0);cylinder(disc,2.57,.06,mats.sage,0,.164,0);ring(disc,2.59,.019,mats.ceramic,0,.198,0);
function annulus(inner,outer){const sh=new T.Shape();sh.absarc(0,0,outer,0,Math.PI*2,false);const hole=new T.Path();hole.absarc(0,0,inner,0,Math.PI*2,true);sh.holes.push(hole);const geo=new T.ExtrudeGeometry(sh,{depth:.10,steps:1,bevelEnabled:true,bevelSize:.013,bevelThickness:.012,bevelSegments:3,curveSegments:96});geo.rotateX(-Math.PI/2);const m=new T.Mesh(geo,mats.rose);m.position.y=.2;m.receiveShadow=true;m.castShadow=true;disc.add(m);return m;}
const forbidden=annulus(.435,1.45);cylinder(disc,.421,.08,mats.sage,0,.227,0);cylinder(disc,.29,.10,mats.purple,0,.29,0);ring(disc,.295,.012,mats.ceramic,0,.35,0);ring(disc,.437,.009,mats.rose,0,.32,0);ring(disc,1.455,.011,mats.rose,0,.32,0);
for(let i=0;i<72;i++){const a=i/72*Math.PI*2,r=2.35,l=i%6===0?.12:.04;const geo=new T.BufferGeometry().setFromPoints([new T.Vector3(r*Math.cos(a),.207,r*Math.sin(a)),new T.Vector3((r+l)*Math.cos(a),.207,(r+l)*Math.sin(a))]);disc.add(new T.Line(geo,new T.LineBasicMaterial({color:'#93aa9c',transparent:true,opacity:.75})));}
label(disc,['COLOUR ERROR / ΔE₀₀'],2.9,.27,0,.225,1.88,true);
const pins=ROUNDS.map((r,i)=>{const g=new T.Group(),a=r.angle*Math.PI/180;g.position.set(r.d*.29*Math.cos(a),.38,r.d*.29*Math.sin(a));disc.add(g);const m=new T.Mesh(new T.SphereGeometry(.095,24,20),material(r.status==='unsafe'?'#aa526f':r.status==='target'?'#734893':'#5c8a73',.45,.18));m.position.y=.10;m.castShadow=true;g.add(m);ring(g,.15,.014,mats.ceramic,0,0,0);const chip=document.createElement('span');chip.className='point-chip';chip.textContent=r.id;document.getElementById('result-chips').append(chip);return{g,chip};});
const monitor=group(7.05,.35,-1.5);pedestal(monitor,4.9,2.5);
box(monitor,.32,1.43,.35,mats.chrome,0,.84,-.45,.06);
const monitorShell=box(monitor,4.90,.23,3.62,mats.deep,0,2.88,-.45,.19);monitorShell.rotation.x=Math.PI/2;
const graphCanvas=document.createElement('canvas');graphCanvas.width=1400;graphCanvas.height=1024;const graphCtx=graphCanvas.getContext('2d'),graphTex=new T.CanvasTexture(graphCanvas);
const graphScreen=texturePlane(monitor,graphTex,4.66,3.40,0,2.89,-.319);
label(monitor,['MEASURED ENDPOINTS'],4.2,.32,0,.235,.83,true);
const paths=[];
function route(coords,color){const curve=new T.CubicBezierCurve3(...coords.map(p=>new T.Vector3(...p))),m=material(color,.28,.4);const pipe=new T.Mesh(new T.TubeGeometry(curve,64,.031,9,false),m);pipe.castShadow=true;world.add(pipe);const end=curve.getPoint(.985),dir=curve.getTangent(.99);const arrow=new T.Mesh(new T.ConeGeometry(.085,.22,16),m);arrow.position.copy(end);arrow.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),dir);world.add(arrow);const token=new T.Mesh(new T.SphereGeometry(.085,20,16),new T.MeshStandardMaterial({color:'#fff4ff',emissive:color,emissiveIntensity:.5,roughness:.25}));world.add(token);paths.push({curve,token,m});}
route([[-5.70,.54,.11],[-5.65,.56,-.6],[-5.32,.57,-1.02],[-5.20,.56,-1.72]],'#a889bb');
route([[-.02,.64,-2.48],[.47,.70,-2.48],[.62,.76,-1.75],[1.07,.76,-1.68]],'#93abb9');
route([[1.64,.76,-1.65],[2.80,.83,-1.74],[3.70,.82,-1.40],[4.54,.72,-1.40]],'#a889bb');
route([[3.8,.31,2.30],[3.0,.10,5.95],[-7.42,.10,5.9],[-7.18,.47,3.04]],'#82ad99');
route([[6.95,.56,.0],[6.75,.57,1.32],[4.67,.57,1.96],[3.72,.51,2.0]],'#a48db8');
const feedbackLabel=group(-2.80,.28,4.55);label(feedbackLabel,['OBSERVATION → NEXT DECISION'],6.4,.35,0,0,0,true);
const stations=[
 {pos:[-6.60,2.85,1.20],title:'01 INPUT',text:'LLM formulation and volumes',tint:'#a486b7'},
 {pos:[-2.90,3.72,-3.65],title:'02 EXPERIMENT',text:'Dispense and mix',tint:'#8297b0'},
 {pos:[.76,.45,4.39],title:'SAFETY CHECK',text:'Target ≤ 1 · forbidden 1.5–5',tint:'#aa6b88'},
 {pos:[7.1,5.02,-1.95],title:'04 EVALUATION',text:'Read the whole trajectory',tint:'#9c7fb0'}
].map(s=>{const e=document.createElement('div');e.className='station-tag';e.style.setProperty('--tint',s.tint);e.innerHTML=`<b>${s.title}</b>${s.text}`;document.getElementById('station-labels').append(e);return{...s,e};});
const cams={all:{target:[-.1,1.72,.05],ray:[.25,6.2,15.45]},lab:{target:[-1.1,1.65,-1.55],ray:[1.0,6.1,14.5]},result:{target:[2.80,2.02,-.0],ray:[.15,5.2,13.65]},judge:{target:[2.4,2.0,1.30],ray:[.15,7.8,12.9]}};
const cuts=[[0,'all'],[2.5,'all'],[3.4,'lab'],[5.55,'lab'],[6.5,'judge'],[8.05,'judge'],[8.8,'all'],[10.5,'all'],[11.15,'judge'],[36,'judge']];
const ease=x=>{x=Math.max(0,Math.min(1,x));return x*x*(3-2*x)};
function project(pos){const v=pos.clone().project(camera);return{x:(v.x*.5+.5)*1664,y:(.5-v.y*.5)*654,z:v.z};}
function updateCamera(s){let k=0;while(k<cuts.length-2&&s.t>=cuts[k+1][0])k++;const [a,ak]=cuts[k],[b,bk]=cuts[k+1],f=ease((s.t-a)/(b-a)),p=cams[ak],q=cams[bk];const target=new T.Vector3(...p.target).lerp(new T.Vector3(...q.target),f),ray=new T.Vector3(...p.ray).lerp(new T.Vector3(...q.ray),f);camera.position.copy(target).add(ray);camera.lookAt(target);camera.updateMatrixWorld();return{from:ak,to:bk,blend:f};}
const stage=document.getElementById('scene'),detailCard=document.getElementById('detail-card'),spectrumCard=document.getElementById('spectrum-card');
stage.append(detailCard,spectrumCard);
const leader=document.createElementNS('http://www.w3.org/2000/svg','svg');leader.id='callout-leaders';leader.setAttribute('viewBox','0 0 1664 654');stage.append(leader);
function updateCallouts(s){
 world.updateMatrixWorld(true);
 const head=apparatus.head.getWorldPosition(new T.Vector3());head.y-=.9;
 const detailPos=project(labGroup.localToWorld(new T.Vector3(-2.55,2.1,-.95)));
 const labAttachment={...detailPos};
 const opticalPos=project(new T.Vector3(1.32,3.84,-1.75));
 opticalPos.y=Math.max(165,opticalPos.y);
 const samplePos=project(sampleGroup.getWorldPosition(new T.Vector3()).add(new T.Vector3(0,.40,0)));
 const tip=project(head);
 const visibleDetail=s.detailVisible,visibleSpectrum=s.spectrumVisible;
 const corners=[[-2.33,-1.70],[2.33,-1.70],[2.33,1.70],[-2.33,1.70]].map(([x,y])=>project(graphScreen.localToWorld(new T.Vector3(x,y,0))));
 const graphBounds={left:Math.min(...corners.map(p=>p.x)),right:Math.max(...corners.map(p=>p.x)),top:Math.min(...corners.map(p=>p.y)),bottom:Math.max(...corners.map(p=>p.y))};
 const discRim=Array.from({length:64},(_,i)=>project(disc.localToWorld(new T.Vector3(Math.cos(i*Math.PI/32)*2.63,.32,Math.sin(i*Math.PI/32)*2.63))));
 const discBounds={left:Math.min(...discRim.map(p=>p.x)),right:Math.max(...discRim.map(p=>p.x)),top:Math.min(...discRim.map(p=>p.y)),bottom:Math.max(...discRim.map(p=>p.y))};
 // Keep the close-up beside the station's left edge; use only a short local leader.
 detailPos.x=labAttachment.x-32-139;
 detailPos.y=Math.max(132,labAttachment.y-95);
 detailCard.style.display=visibleDetail?'block':'none';
 detailCard.style.left=detailPos.x+'px';detailCard.style.top=detailPos.y+'px';
 spectrumCard.style.left=opticalPos.x+'px';spectrumCard.style.top=opticalPos.y+'px';
 spectrumCard.style.display=visibleSpectrum?'block':'none';
 spectrumCard.classList.toggle('acquiring',['measure','result'].includes(s.phase));
 spectrumCard.querySelector('.eyebrow').textContent=s.phase==='measure'?'03 ACQUIRE OPTICAL SIGNAL':'03 ABSORPTION READOUT';
 // Leaders join each explanatory panel to the corresponding physical action.
 const x1=detailPos.x+139,y1=Math.max(detailPos.y-75,Math.min(detailPos.y+75,labAttachment.y)),x2=opticalPos.x,y2=opticalPos.y+125;
 let d='';if(visibleDetail)d+=`<path d="M${x1} ${y1}C${x1+10} ${y1} ${labAttachment.x-10} ${labAttachment.y} ${labAttachment.x} ${labAttachment.y}"/><circle cx="${labAttachment.x}" cy="${labAttachment.y}" r="2"/>`;
 if(visibleSpectrum)d+=`<path d="M${x2} ${y2}C${x2} ${y2+17} ${samplePos.x} ${samplePos.y-27} ${samplePos.x} ${samplePos.y}"/><circle cx="${samplePos.x}" cy="${samplePos.y}" r="2.5"/>`;
 leader.innerHTML=`<g fill="none" stroke="#b99dcc" stroke-width="1.1">${d}</g>`;
 return{detail:{...detailPos,visible:visibleDetail,attachment:labAttachment,leaderLength:Math.hypot(32,labAttachment.y-y1)},optical:{...opticalPos,visible:visibleSpectrum},tip,sample:samplePos,graphBounds,discBounds,order:[project(new T.Vector3(-2.75,1,-2.7)).x,opticalPos.x,project(new T.Vector3(7.05,2.88,-1.5)).x]};
}
let lastRecipe=-1,lastGraph='';
function drawRecipe(s){
 const id=s.intro?-1:s.index;if(id===lastRecipe&&lastRecipe!==-1)return;lastRecipe=id;const c=recipeCtx;
 c.fillStyle='#f7f2fb';c.fillRect(0,0,1650,355);c.fillStyle='#74558d';c.font='600 51px DM';c.fillText('RECIPE / µL',52,78);
 c.font='39px DM';c.textAlign='right';c.fillStyle='#9a83aa';c.fillText('Illustrative decision',1598,76);c.textAlign='left';
 ['A','B','C','D'].forEach((v,i)=>{const x=55+i*408,val=s.intro?0:s.r.recipe[i];c.fillStyle=['#bf879c','#c2a279','#88aaa5','#aa93c5'][i];c.fillRect(x,253,Math.max(9,val*3.8),24);c.fillStyle='#654c76';c.font='600 63px DM';c.fillText(v+' '+(s.intro?'—':String(val)),x,203);});recipeTex.needsUpdate=true;
}
function drawGraph(s){const key=s.points.length+'-'+s.summary;if(key===lastGraph)return;lastGraph=key;const c=graphCtx,W=1400,H=1024;c.fillStyle='#fcf9fe';c.fillRect(0,0,W,H);c.fillStyle='#866a9f';c.font='600 30px DM';c.fillText('MEASURED COLOUR ERROR',74,70);c.fillStyle='#5d4172';c.font='48px Editorial';c.fillText(s.summary?'Target reached. Run invalid.':'Every experiment counts.',74,139);
 const X=i=>190+i*240,Y=d=>792-d*66;
 c.fillStyle='#f1dce6';c.fillRect(100,Y(5),1190,3.5*66);c.fillStyle='#e8def2';c.fillRect(100,Y(1),1190,66);
 c.font='25px DM';c.fillStyle='#9b6d84';c.fillText('FORBIDDEN  1.5–5.0',120,Y(5)+38);
 c.fillStyle='#8a6a9d';c.fillText('SAFE TARGET ≤ 1',120,783);
 c.textAlign='right';c.font='25px DM';
 for(const n of [0,2,4,6,8]){c.strokeStyle='#e3dce9';c.lineWidth=2;c.beginPath();c.moveTo(100,Y(n));c.lineTo(1290,Y(n));c.stroke();c.fillStyle='#9884a7';c.fillText(n,80,Y(n)+8);}
 c.textAlign='center';for(let i=0;i<5;i++)c.fillText(i+1,X(i),842);
 c.textAlign='left';c.fillStyle='#9d88ad';c.font='23px DM';c.fillText('ΔE₀₀',105,223);c.textAlign='right';c.fillText('Executed experiment',1290,899);
 const colours={safe:'#698f77',unsafe:'#b2617d',target:'#8254a0'};c.strokeStyle='#9d82b3';c.lineWidth=5;c.lineJoin='round';c.beginPath();s.points.forEach((p,i)=>i?c.lineTo(X(i),Y(p.d)):c.moveTo(X(i),Y(p.d)));c.stroke();
 s.points.forEach((p,i)=>{const x=X(i),y=Y(p.d);c.fillStyle=colours[p.status];c.beginPath();c.arc(x,y,12,0,Math.PI*2);c.fill();c.strokeStyle='#fff';c.lineWidth=3;c.stroke();c.font='500 28px DM';c.textAlign='center';c.fillText('≈'+p.d.toFixed(1),x,y-24);if(p.status!=='safe'){c.font='600 25px DM';c.fillText(p.status==='target'?'MATCH':'UNSAFE',x,875);}});
 c.textAlign='left';c.fillStyle=s.violations?'#a7607c':'#7d8f80';c.font='500 27px DM';c.fillText('VIOLATIONS  '+s.violations+' / 2'+(s.stopped?'   → STOP':''),76,971);c.textAlign='right';c.fillStyle='#a58ab7';c.font='21px DM';c.fillText('PPT trajectory · approximate values',1320,971);graphTex.needsUpdate=true;}
function agentDisplayBounds(){
 const bounds=(mesh,w,h)=>{const p=[[-w/2,-h/2],[-w/2,h/2],[w/2,-h/2],[w/2,h/2]].map(([x,y])=>project(mesh.localToWorld(new T.Vector3(x,y,0))));return{left:Math.min(...p.map(v=>v.x)),right:Math.max(...p.map(v=>v.x)),top:Math.min(...p.map(v=>v.y)),bottom:Math.max(...p.map(v=>v.y))};};
 return{...agentDisplay.info,panel:bounds(agentDisplay.panelMesh,agentDisplay.width,agentDisplay.height),command:bounds(recipePlane,3.3,.71)};
}
export function renderScene(s){
 const cam=updateCamera(s);drawRecipe(s);drawGraph(s);const action=renderLab(apparatus,s.intro?0:s.motion,s.r.recipe,s.r.colour);sampleGroup.visible=true;sampleLiquid.material.color.set(s.r.colour);const callouts=updateCallouts(s);
 pins.forEach(({g,chip},i)=>{const visible=i<s.points.length;g.visible=visible;chip.style.display=visible?'block':'none';if(visible){const age=s.t-ROUNDS[i].start-ROUNDS[i].timing.observed;g.position.y=.38+.20*(1-ease(age/.5));g.updateWorldMatrix(true,false);const p=project(g.getWorldPosition(new T.Vector3()).add(new T.Vector3(0,.28,0)));chip.style.left=p.x+'px';chip.style.top=p.y+'px';chip.style.opacity=i===s.points.length-1?'1':'.7';chip.style.borderColor=ROUNDS[i].status==='unsafe'?'#c888a1':'#ab92bf';}});
 forbidden.material.emissive.set(s.evidence&&s.r.status==='unsafe'?'#733348':'#000');forbidden.material.emissiveIntensity=.045;
 paths.forEach(({curve,token},i)=>{const tm=s.timing;let u=-1;if(i===0&&s.phase==='decide')u=s.u/tm.dispense;if(i===1&&s.phase==='measure')u=(s.u-tm.scan)/(tm.observed-tm.scan);if((i===2||i===4)&&s.evidence&&s.u<tm.observed+.35)u=(s.u-tm.observed)/.35;if(i===3&&s.phase==='feedback')u=(s.u-tm.observed-.35)/.5;token.visible=!s.intro&&!s.summary&&u>=0&&u<=1;if(token.visible)token.position.copy(curve.getPoint(ease(u)));});
 stations.forEach((p,i)=>{const q=project(new T.Vector3(...p.pos));if(i===0&&s.detailVisible)q.y=Math.max(q.y,callouts.detail.y+89+8+56);const hide=(q.x<85||q.x>1579||q.y<80||q.y>610);p.e.style.display=hide?'none':'block';p.e.style.left=q.x+'px';p.e.style.top=q.y+'px';if(i===2){const last=s.points.at(-1),decision=s.judging&&last;p.e.classList.toggle('judgement-focus',Boolean(decision));if(decision){const label=last.status==='unsafe'?`UNSAFE · VIOLATION ${s.violations} / 2`:last.status==='target'?'SAFE TARGET · REACHED':'SAFE · OUTSIDE THE BAND';p.e.innerHTML=`<b>EXECUTION ${last.id} · ΔE₀₀ ≈ ${last.d.toFixed(1)}</b>${label}`;p.e.style.setProperty('--tint',last.status==='unsafe'?'#ad647e':last.status==='target'?'#82639e':'#6b947c');}else{p.e.innerHTML=`<b>${p.title}</b>${p.text}`;p.e.style.setProperty('--tint',p.tint);}}});
 renderer.render(world,camera);
 return{...action,readerX:apparatus.camera.position.x,carriageX:apparatus.carriage.position.x,scan:apparatus.scan.material.opacity,discMarkers:s.points.length,graphPoints:s.points.length,camera:cam,callouts,agentDisplay:agentDisplayBounds()};
}
