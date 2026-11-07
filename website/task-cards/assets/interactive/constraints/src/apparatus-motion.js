import * as T from 'three';

const $ = selector => document.querySelector(selector);
const clamp = value => Math.min(1,Math.max(0,value));
function ease(value) {
 const u = clamp(value);
 return u*u*(3-2*u);
}
const blend = (a,b,t) => a+(b-a)*ease(t);
const runOne = [.71,.32,.63,.49];
const stockColours = ['#c1748c','#c5a16e','#6b9da0','#8c7eac'];
const liquidColours = ['#e3dce8','#c591a8','#be9fac','#a2a8ad','#b197b4'].map(colour=>new T.Color(colour));
const observation = '#b197b4';
const start = 2.9, cycle = 1.55, mixed = 10.08, captured = 11.35, returned = 13.45;
const dispenseEnd = start+cycle*4;

export function renderLab(lab,t,runOne=[.71,.32,.63,.49],finalColour='#b197b4') {
 let x = .22, z = .13, head = .24, fill = 0, scan = 0, active = -1;
 let colour = liquidColours[0].clone(), action = 'Sample well ready';
 lab.drop.visible = false;
 if (t>=start && t<dispenseEnd) {
  active = Math.floor((t-start)/cycle);
  const u = (t-start)/cycle-active;
  const stockZ = lab.stocks[active].position.z;
  const overStock = ease(u/.22)*(1-ease((u-.49)/.22));
  x = .22+(-1.12-.22)*overStock;
  z = .13+(stockZ-.13)*overStock;
  head -= .37*ease((u-.22)/.09)*(1-ease((u-.40)/.09));
  head -= .48*ease((u-.71)/.10)*(1-ease((u-.93)/.07));
  const amount = ease((u-.81)/.12);
  fill = (runOne.slice(0,active).reduce((sum,value)=>sum+value,0)+amount*runOne[active])/runOne.reduce((a,b)=>a+b,0);
  colour.copy(liquidColours[active]).lerp(active===3?new T.Color(finalColour):liquidColours[active+1],amount);
  if (u>=.81 && u<.93) {
   lab.drop.visible = true;
   lab.drop.position.y = blend(.704,.548+.064*fill,(u-.81)/.12);
   lab.drop.material.color.set(stockColours[active]);
   lab.drop.scale.set(.82,1.22,.82);
  }
  const component = 'ABCD'[active];
  action = u<.49?'Pick up component '+component:
   u<.81?'Move '+component+' to the sample well':'Dispense component '+component;
 } else if (t>=dispenseEnd) {
  fill = 1;
  colour.set(finalColour);
  if (t<mixed) {
   const u = (t-dispenseEnd)/(mixed-dispenseEnd);
   const reach = Math.sin(Math.PI*u);
   head -= .60*reach;
   x += .038*reach*Math.sin(u*Math.PI*5);
   z += .038*reach*Math.cos(u*Math.PI*5);
   action = 'Mix the sample';
  } else {
   x = blend(.22,-1.1,(t-mixed)/.36);
   scan = t>=mixed+.6 && t<captured ? ease((t-mixed-.6)/.12) : 0;
   action = t<captured?'Scan the mixed sample':'Spectrum → observed colour';
  }
 }
 const h = .005+.059*fill;
 lab.carriage.position.x = x;
 lab.head.position.set(0,head,z+.89);
 lab.zGuide.position.z = z+.89;
 lab.camera.position.x = blend(1.13,.43,(t-mixed-.08)/.52);
 lab.scan.material.opacity = scan*.58;
 lab.scan.scale.setScalar(1+scan*.13*Math.sin(t*11));
 lab.beam.material.opacity = scan*.12;
 lab.sample.scale.y = h/.06;
 lab.sample.position.y = .547+h/2;
 lab.sample.material.color.copy(colour);
 lab.meniscus.position.y = .547+h;
 lab.meniscus.material.color.copy(colour).lerp(new T.Color('#ffffff'),.35);
 return {active,action};
}
