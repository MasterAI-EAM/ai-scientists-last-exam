import * as T from 'three';
import {RoomEnvironment} from './vendor/RoomEnvironment.js';
import {box,cylinder,ring,material} from './geometry.js';
const $=id=>document.getElementById(id),canvas=$('detail-canvas');
const renderer=new T.WebGLRenderer({canvas,antialias:true,alpha:true,preserveDrawingBuffer:true});renderer.setSize(916,410,false);renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1.04;renderer.shadowMap.enabled=true;
const scene=new T.Scene(),camera=new T.PerspectiveCamera(31,458/205,.1,60);camera.position.set(3.8,4.5,9.2);camera.lookAt(0,.92,0);
const pm=new T.PMREMGenerator(renderer);scene.environment=pm.fromScene(new RoomEnvironment(),.035).texture;scene.environmentIntensity=.55;scene.add(new T.HemisphereLight(0xffffff,0xb6a4c6,1.8));
const key=new T.DirectionalLight(0xfff9f2,3.0);key.position.set(-3,7,4);key.castShadow=true;scene.add(key);const rim=new T.DirectionalLight(0xd2c4ed,1.2);rim.position.set(4,4,-3);scene.add(rim);
const ceramic=material('#e9e0f1',.12,.39),metal=material('#a491b4',.6,.3),purple=material('#9b85bc',.3,.28),deep=material('#816293',.2,.36);
const ground=new T.Mesh(new T.PlaneGeometry(30,30),new T.ShadowMaterial({opacity:.12,color:0x735d85}));ground.rotation.x=-Math.PI/2;ground.position.y=-.11;ground.receiveShadow=true;scene.add(ground);
box(scene,6.2,.12,2.3,ceramic,0,0,0,.2);
const glass=new T.MeshPhysicalMaterial({color:'#f1e9fb',roughness:.12,metalness:0,transparent:true,opacity:.21,side:T.DoubleSide,depthWrite:false});
const vessels=[];const colour=['#c08a9f','#c9ac82','#8fb4ad','#ac95c9'];
for(let i=0;i<4;i++){const x=-2.52+i*.49;cylinder(scene,.19,.055,metal,x,.1,.08);const g=new T.Mesh(new T.CylinderGeometry(.165,.165,.65,40,1,true),glass);g.position.set(x,.47,.08);scene.add(g);cylinder(scene,.13,.44,material(colour[i],.08,.28),x,.38,.08);ring(scene,.165,.016,metal,x,.79,.08);vessels.push(g);}
const cup=new T.Group();cup.position.set(.5,.12,.1);scene.add(cup);box(cup,.81,.055,.74,metal,0,0,0,.07);
for(const[x,z,w,d]of [[-.34,0,.02,.55],[.34,0,.02,.55],[0,-.275,.69,.025],[0,.275,.69,.025]]){box(cup,w,1.15,d,glass,x,.61,z,.01);}
const liquid=box(cup,.61,.80,.48,new T.MeshPhysicalMaterial({color:'#9b85bc',roughness:.22,metalness:.03,transparent:true,opacity:.88}),0,.44,0,.025);ring(cup,.28,.006,material('#cebfde',.1,.4),0,.86,0);
const pipette=new T.Group();pipette.position.set(.5,2.12,.1);scene.add(pipette);cylinder(pipette,.09,.42,ceramic,0,0,0);cylinder(pipette,.06,.30,metal,0,-.34,0);const tip=new T.Mesh(new T.ConeGeometry(.049,.39,32),glass);tip.rotation.z=Math.PI;tip.position.y=-.68;pipette.add(tip);
const drop=new T.Mesh(new T.SphereGeometry(.06,24,20),new T.MeshPhysicalMaterial({color:'#ae93c2',roughness:.12,transparent:true,opacity:.9}));drop.scale.set(.7,1,.7);scene.add(drop);
box(scene,.52,.70,.72,metal,1.98,.43,.13,.10);box(scene,.05,.33,.40,deep,1.69,.45,.13,.05);
const rayMat=new T.MeshBasicMaterial({color:'#bca3d4',transparent:true,opacity:0,depthWrite:false});const ray=new T.Mesh(new T.CylinderGeometry(.09,.09,1.15,24,1,true),rayMat);ray.rotation.z=Math.PI/2;ray.position.set(1.13,.56,.13);scene.add(ray);
const coil=new T.Mesh(new T.TorusGeometry(.225,.012,8,60,Math.PI*1.6),material('#d9c8e7',.2,.25));coil.rotation.x=Math.PI/2;coil.position.set(.5,.72,.1);scene.add(coil);
const txt=(id,t)=>$(id).textContent=t;
export function renderDetail(s){
 const dispense=s.phase==='execute',mix=s.phase==='mix',measure=['measure','result','feedback','judge','verdict'].includes(s.phase);
 const fill=s.intro?.72:s.phase==='decide'?.14:s.u<s.timing.mix?Math.max(.15,(s.u-s.timing.dispense)/(s.timing.mix-s.timing.dispense)):1;liquid.scale.y=fill;liquid.position.y=.08+.36*fill;liquid.material.color.set(s.intro?'#9b85bc':s.r.colour);
 pipette.visible=!measure;drop.visible=dispense;
 if(dispense){const p=((s.u-s.timing.dispense)*3)%1;drop.position.set(.5,1.24-.4*p,.1);pipette.position.y=2.12-.07*Math.sin(p*Math.PI);}
 coil.visible=mix;coil.rotation.z=s.t*9;rayMat.opacity=measure?.18:0;
 const step=s.intro||s.phase==='decide'?'FORMULATE':dispense?'DISPENSE':mix?'MIX':'MEASURE';
 txt('detail-step',step);
 txt('detail-title',step==='FORMULATE'?'Choose component volumes.':step==='DISPENSE'?'Add the selected components.':step==='MIX'?'Mix a uniform solution.':'Acquire the optical signal.');
 txt('detail-caption',step==='FORMULATE'?'A–D volumes form the experimental input.':step==='DISPENSE'?'The pipette transfers the proposed volumes.':step==='MIX'?'Mix first, then measure the solution.':'Read the response before evaluating the result.');
 txt('sample-label',s.evidence?'Measured sample · #'+s.r.id:'Sample in preparation');$('sample-swatch').style.background=s.evidence?s.r.colour:'#ded4e5';
 renderer.render(scene,camera);return{phase:step,measured:s.evidence,exampleSpectrum:true};
}
