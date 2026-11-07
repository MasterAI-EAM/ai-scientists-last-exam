import {T,material,label,ring,mats} from './stage.js';
export async function createMolecule(parent){
 const data=await(await fetch('../assets/molecule.json')).json(),g=new T.Group();parent.add(g);
 const positions=data.atoms.map(a=>new T.Vector3(a.x,a.y,a.z)),center=positions.reduce((c,p)=>c.add(p),new T.Vector3()).multiplyScalar(1/positions.length);positions.forEach(p=>p.sub(center).multiplyScalar(.30));
 const colors={C:'#8e869c',N:'#6583b0',O:'#c46f85',S:'#c5a15e'},bondMat=material('#b8afc9',.3,.33);
 data.bonds.forEach(([a,b,order])=>{const p=positions[a],q=positions[b],dir=q.clone().sub(p),unit=dir.clone().normalize(),offset=new T.Vector3(-unit.y,unit.x,0).normalize().multiplyScalar(.027);const count=order===2?2:1;for(let n=0;n<count;n++){const m=new T.Mesh(new T.CylinderGeometry(.024,.024,dir.length(),12),bondMat);m.position.copy(p).add(q).multiplyScalar(.5).addScaledVector(offset,count===2?(n?1:-1):0);m.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),unit);g.add(m);}if(order===1.5){for(let k=0;k<3;k++){const m=new T.Mesh(new T.CylinderGeometry(.012,.012,dir.length()*.13,8),bondMat);m.position.copy(p).lerp(q,.22+k*.27).addScaledVector(offset,1.7);m.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),unit);g.add(m);}}});
 data.atoms.forEach((a,i)=>{const m=new T.Mesh(new T.SphereGeometry(a.element==='S'?.105:.080,22,18),material(colors[a.element]||'#ccc',.12,.26));m.position.copy(positions[i]);m.castShadow=true;g.add(m);});
 g.position.y=1.5;g.rotation.x=.25;
 ring(parent,2.3,.025,mats.chrome,0,.22,0);
 label(parent,'MOLECULAR CONTEXT · EXAMPLE',4.3,.27,0,.235,-1.31,true);
 return{g,render(t){g.rotation.y=Math.sin(t*.10)*.16;}};
}
