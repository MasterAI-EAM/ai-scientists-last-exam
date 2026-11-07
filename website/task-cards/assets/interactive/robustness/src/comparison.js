import {T,mats,pedestal,vessel,setLiquid,ring,ease} from './stage.js';
import {rounds} from './timeline.mjs';

// An outcome is revealed only after acquisition; vessel levels illustrate channel A.
export function createComparison(v){
 const tray=v.group(1.02,.38,1.65);pedestal(tray,8.5,2.85);
 const positions=[-2.83,0,2.83],views=[];
 const root=document.createElement('div');root.id='outcome-comparison';document.getElementById('scene').append(root);
 const heading=document.createElement('div');heading.className='comparison-heading';
 heading.innerHTML='<b>THREE EXPERIMENTS · ONE FIXED TARGET</b><span>Measured outcomes appear here, one experiment at a time.</span>';root.append(heading);
 const title=['Baseline','Same command','Adjusted command'];
 for(let i=0;i<3;i++){
  const sample=vessel(tray,positions[i],-.29,rounds[i].colour,.45,1.30);
  sample.liquid.material=new T.MeshBasicMaterial({color:rounds[i].colour,toneMapped:false});
  sample.g.children.forEach(m=>{if(m.material?.transparent&&m!==sample.liquid)m.material.opacity=.11;});
  const surface=new T.Mesh(new T.CircleGeometry(.407,64),new T.MeshBasicMaterial({color:rounds[i].colour,toneMapped:false,side:T.DoubleSide}));surface.rotation.x=-Math.PI/2;sample.g.add(surface);
  const reference=ring(sample.g,.472,.010,new T.MeshBasicMaterial({color:'#a790ba',transparent:true,opacity:.58}),0,.07+1.30*.72,0);
  const halo=ring(tray,.63,.025,new T.MeshBasicMaterial({color:'#9b85bc',transparent:true,opacity:.45}),positions[i],.217,-.29);
  const card=document.createElement('div');card.className='outcome-card pending';
  card.innerHTML='<div class="outcome-kicker"><span>0'+(i+1)+' / '+['REFERENCE','DRIFT','ADAPT'][i]+'</span><span class="outcome-status">WAITING</span></div><h3>'+title[i]+'</h3><div class="outcome-command">'+(i===2?'Next command after feedback':'Command A · 50 µL')+'</div><div class="outcome-result"><span class="sample-swatch"></span><div><strong>—</strong><span class="signal-label">Awaiting measurement</span></div></div><div class="outcome-track"><i></i></div><p class="outcome-foot">'+['Establish the reference.','Repeat and compare.','Adjust, then measure again.'][i]+'</p>';
  root.append(card);
  views.push({sample,surface,reference,halo,card,anchor:new T.Vector3(positions[i],.20,1.38)});
 }
 const target=document.createElement('div');target.className='comparison-target';target.innerHTML='<i></i><span>Fixed target</span>';root.append(target);
 const caption=document.createElement('div');caption.className='comparison-caption';caption.textContent='Vessel level = illustrative delivered A · signal normalized to baseline';root.append(caption);
 let signature='';
 function render(s){
  const measured=views.map((item,i)=>i<s.count),key=s.count+':'+s.index+':'+s.phase;
  if(key!==signature){
   signature=key;
   heading.querySelector('span').textContent=s.count===3?'The revised command is followed by a measured recovery.':s.count===2?'Same command → lower delivered volume → changed signal.':s.count===1?'Baseline recorded. The next experiment uses the same command.':'Only completed measurements populate the comparison.';
   views.forEach(({card},i)=>{
    const ready=measured[i],running=!s.intro&&i===s.index&&!ready,known=!s.intro&&i<=s.index;
    card.className='outcome-card '+(ready?'measured '+(i===1?'changed':'recovered'):running?'acquiring':'pending');
    card.querySelector('.outcome-status').textContent=ready?'OBSERVED':running?'MEASURING':'WAITING';
    card.querySelector('.outcome-command').textContent=known?'Command A · '+rounds[i].command+' µL':i===2?'Next command after feedback':'Command A · 50 µL';
    card.querySelector('strong').textContent=ready?Math.round(rounds[i].ratio*100)+'%':'—';
    card.querySelector('.signal-label').textContent=ready?'of baseline signal':'Awaiting measurement';
    card.querySelector('.sample-swatch').style.background=ready?rounds[i].colour:'#e8e0ee';
    card.querySelector('.outcome-track i').style.width=ready?rounds[i].ratio*100+'%':'0%';
    card.querySelector('.outcome-foot').textContent=ready?['50 µL delivered · baseline recorded','40 µL delivered · signal drops','50 µL delivered · signal returns'][i]:['Establish the reference.','Repeat and compare.','Adjust, then measure again.'][i];
   });
  }
  const samples=views.map(({sample,surface,reference,halo,card,anchor},i)=>{
   const visible=measured[i],age=s.t-rounds[i].start-6.6,arrival=ease(age/.55),amount=rounds[i].delivered/50;
   sample.g.visible=visible;sample.g.position.y=.25+(1-arrival)*.18;
   setLiquid(sample,amount,rounds[i].colour);surface.position.y=.073+1.30*.72*amount;
   reference.visible=i===1;halo.material.color.set(visible?i===1?'#c1869f':'#9b85bc':'#c3b1d0');halo.material.opacity=visible?.8:.26;
   const point=v.project(tray.localToWorld(anchor.clone()));
   card.style.left=point.x+'px';card.style.top=(point.y-8)+'px';
   return{visible,amount:visible?amount:0,commandVisible:!s.intro&&i<=s.index,signal:visible?rounds[i].ratio:null};
  });
  const hp=v.project(tray.localToWorld(new T.Vector3(-3.72,1.95,-.55)));
  heading.style.left=hp.x+'px';heading.style.top=hp.y+'px';
  const tp=v.project(tray.localToWorld(new T.Vector3(3.1,1.72,-.35)));
  target.style.left=tp.x+'px';target.style.top=tp.y+'px';
  const cp=v.project(tray.localToWorld(new T.Vector3(0,.06,1.42)));
  caption.style.left=cp.x+'px';caption.style.top=(cp.y+116)+'px';
  return{samples,measuredCount:samples.filter(x=>x.visible).length};
 }
 return{render,tray};
}
