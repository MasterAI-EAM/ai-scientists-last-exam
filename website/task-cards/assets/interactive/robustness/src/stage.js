import * as T from 'three';
import {RoomEnvironment} from './vendor/RoomEnvironment.js';
import {box,cylinder,ring,material,dark,steel,edge,gold,blue} from './geometry.js';
export {T,box,cylinder,ring,material};
export const W=1664,H=654;
export const ease=x=>{x=Math.max(0,Math.min(1,x));return x*x*(3-2*x)};
export const mix=(a,b,x)=>a+(b-a)*ease(x);
export const mats={ceramic:material('#eee7f4',.13,.4),deep:material('#594467',.32,.3),lilac:material('#b39acb',.28,.35),chrome:material('#a89bb7',.64,.28),sage:material('#c4d8ce',.12,.45),rose:material('#c891a7',.22,.4),purple:material('#9b85bc',.25,.25)};
dark.color.set('#635371');steel.color.set('#b6aebf');edge.color.set('#9f8fae');gold.color.set('#bc9dc9');blue.color.set('#9db7c7');
export function plane(parent,tex,w,h,x,y,z){tex.colorSpace=T.SRGBColorSpace;tex.anisotropy=8;const p=new T.Mesh(new T.PlaneGeometry(w,h),new T.MeshBasicMaterial({map:tex,toneMapped:false,transparent:true}));p.position.set(x,y,z);parent.add(p);return p;}
export function pedestal(parent,w,d){box(parent,w,.25,d,mats.chrome,0,0,0,.22);box(parent,w-.08,.08,d-.08,mats.ceramic,0,.16,0,.20);}
export function label(parent,text,w,h,x,y,z,flat=false){const c=document.createElement('canvas');c.width=1200;c.height=Math.round(1200*h/w);const g=c.getContext('2d');g.textAlign='center';g.textBaseline='middle';g.fillStyle='#705583';g.font='600 '+Math.round(c.height*.54)+'px DM';g.fillText(text,600,c.height/2,1140);const p=plane(parent,new T.CanvasTexture(c),w,h,x,y,z);if(flat)p.rotation.x=-Math.PI/2;return p;}
export function panel(parent,w,h,x,y,z,pixels=1200){const g=new T.Group();g.position.set(x,y,z);parent.add(g);const shell=box(g,w+.18,.16,h+.18,mats.deep,0,0,0,.13);shell.rotation.x=Math.PI/2;const c=document.createElement('canvas');c.width=pixels;c.height=Math.round(pixels*h/w);const tex=new T.CanvasTexture(c),screen=plane(g,tex,w,h,0,0,.095);return{g,c,ctx:c.getContext('2d'),tex,screen,w,h};}
export function clear(p){const c=p.ctx;c.fillStyle='#fcf9fe';c.fillRect(0,0,p.c.width,p.c.height);return c;}
export function text(c,s,x,y,size=36,color='#684d7c',align='left',weight=500){c.font=weight+' '+size+'px DM';c.fillStyle=color;c.textAlign=align;c.textBaseline='middle';c.fillText(s,x,y);}
export function rr(c,x,y,w,h,r,fill){c.fillStyle=fill;c.beginPath();c.roundRect(x,y,w,h,r);c.fill();}
export function vessel(parent,x,z,color,r=.32,h=.95){const g=new T.Group();g.position.set(x,.25,z);parent.add(g);cylinder(g,r+.05,.09,mats.chrome,0,.025,0);const glass=new T.Mesh(new T.CylinderGeometry(r,r,h,48,1,true),new T.MeshPhysicalMaterial({color:'#fbf9ff',transparent:true,opacity:.22,roughness:.12,side:T.DoubleSide,depthWrite:false}));glass.position.y=h/2+.06;g.add(glass);ring(g,r,.019,mats.chrome,0,h+.06,0);const liquid=cylinder(g,r-.04,h*.72,new T.MeshPhysicalMaterial({color,roughness:.15,transparent:true,opacity:.83}),0,.07+h*.36,0);return{g,liquid,h};}
export function setLiquid(v,amount,color){v.liquid.scale.y=Math.max(.005,amount);v.liquid.position.y=.07+v.h*.36*amount;v.liquid.material.color.set(color);}
export function stage(){
 const renderer=new T.WebGLRenderer({canvas:document.getElementById('world'),antialias:true,alpha:true,preserveDrawingBuffer:true});renderer.setSize(2496,981,false);renderer.setPixelRatio(1);renderer.shadowMap.enabled=true;renderer.shadowMap.type=T.PCFSoftShadowMap;renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;
 const world=new T.Scene(),camera=new T.PerspectiveCamera(34,W/H,.1,100),env=new T.PMREMGenerator(renderer);world.environment=env.fromScene(new RoomEnvironment(),.03).texture;world.environmentIntensity=.5;
 world.add(new T.HemisphereLight(0xffffff,0xa497b9,1.65));const sun=new T.DirectionalLight(0xfff7ef,2.7);sun.position.set(-7,13,9);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-14,right:14,top:13,bottom:-13,near:.1,far:40});sun.shadow.normalBias=.03;sun.shadow.bias=-.0001;world.add(sun);const rim=new T.DirectionalLight(0xd8c8f5,1.75);rim.position.set(7,6,-7);world.add(rim);
 const ground=new T.Mesh(new T.PlaneGeometry(70,70),new T.ShadowMaterial({color:0x6d537b,opacity:.22}));ground.rotation.x=-Math.PI/2;ground.position.y=-.4;ground.receiveShadow=true;world.add(ground);
 const group=(x,y,z)=>{const g=new T.Group();g.position.set(x,y,z);world.add(g);return g;};
 const project=pos=>{const v=pos.clone().project(camera);return{x:(v.x*.5+.5)*W,y:(.5-v.y*.5)*H};};
 const labels=[];
 function tag(pos,title,copy){const e=document.createElement('div');e.className='station-tag';const b=document.createElement('b'),s=document.createElement('span');b.textContent=title;s.textContent=copy;e.append(b,s);document.getElementById('labels').append(e);const tag={pos:new T.Vector3(...pos),e,b,s};labels.push(tag);return tag;}
 function route(coords,color='#a889bb'){const curve=new T.CubicBezierCurve3(...coords.map(p=>new T.Vector3(...p))),m=material(color,.28,.4);const pipe=new T.Mesh(new T.TubeGeometry(curve,64,.029,9,false),m);pipe.castShadow=true;world.add(pipe);const arrow=new T.Mesh(new T.ConeGeometry(.07,.18,16),m);arrow.position.copy(curve.getPoint(.985));arrow.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),curve.getTangent(.99));world.add(arrow);const token=new T.Mesh(new T.SphereGeometry(.085,20,16),new T.MeshStandardMaterial({color:'#fff4ff',emissive:color,emissiveIntensity:.45,roughness:.25}));world.add(token);return{curve,token,move(u){token.visible=u>=0&&u<=1;if(token.visible)token.position.copy(curve.getPoint(ease(u)));}};}
 function pose(target,ray){camera.position.set(...target).add(new T.Vector3(...ray));camera.lookAt(new T.Vector3(...target));camera.updateMatrixWorld();}
 function draw(){world.updateMatrixWorld(true);for(const t of labels){const p=project(t.pos);t.e.style.left=p.x+'px';t.e.style.top=p.y+'px';}renderer.render(world,camera);}
 function bounds(mesh,w,h){const ps=[[-w/2,-h/2],[-w/2,h/2],[w/2,-h/2],[w/2,h/2]].map(([x,y])=>project(mesh.localToWorld(new T.Vector3(x,y,0))));return{left:Math.min(...ps.map(p=>p.x)),right:Math.max(...ps.map(p=>p.x)),top:Math.min(...ps.map(p=>p.y)),bottom:Math.max(...ps.map(p=>p.y))};}
 return{renderer,world,camera,group,project,tag,route,pose,draw,bounds};
}
