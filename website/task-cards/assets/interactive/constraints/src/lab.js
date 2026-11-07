import * as T from 'three';
import {box,cylinder,ring,mesh,tube,shadow,label3d,material,glassMaterial,glow,dark,steel,edge,gold,blue} from './geometry.js';
export function createLab(parent){
 const lab=new T.Group();parent.add(lab);lab.position.y=.14;
 const glass=glassMaterial(),white=material(0xc3d0d7,.4,.26);
 box(lab,3.55,.18,2.35,dark,0,.16,0,.16);
 box(lab,3.46,.025,2.27,edge,0,.27,0,.13);
 for(const x of [-1.48,1.48])for(const z of [-.94,.94])cylinder(lab,.055,.014,steel,x,.294,z);
 for(const z of [-.83,.83]){box(lab,3.06,.07,.09,steel,0,.35,z);box(lab,2.85,.04,.028,dark,0,.401,z)}
 box(lab,.34,.22,1.6,edge,-1.12,.42,.055,.08);
 const stocks=[];const colors=[0xc1748c,0xc5a16e,0x6b9da0,0x8c7eac];
 for(let i=0;i<4;i++){
  const z=-.515+i*.38,g=new T.Group();g.position.set(-1.12,.52,z);lab.add(g);
  cylinder(g,.116,.045,dark,0,.017,0);tube(g,.105,.39,glass,0,.035,0);
  cylinder(g,.077,.25,new T.MeshPhysicalMaterial({color:colors[i],roughness:.2,metalness:0,transmission:.18,transparent:true,opacity:.93}),0,.23,0);
  ring(g,.105,.012,steel,0,.424,0);label3d(g,'ABCD'[i],.085,.041,0,.15,.108,'#edf0ef');stocks.push(g);
 }
 // Raised plate with a sample well and neighbouring, empty wells.
 box(lab,1.24,.11,1.05,white,.22,.38,.08,.1);
 box(lab,1.15,.02,.96,edge,.22,.443,.08,.07);
 for(const x of [-.16,.22,.6])for(const z of [-.23,.13,.49]){
  cylinder(lab,.137,.024,dark,x,.46,z);ring(lab,.127,.013,steel,x,.483,z);
 }
 const sampleX=.22,sampleZ=.13;
 tube(lab,.126,.155,glass,sampleX,.476,sampleZ);
 const sample=cylinder(lab,.097,.06,new T.MeshPhysicalMaterial({color:0xa782b4,roughness:.19,metalness:.08,transmission:.08,transparent:true,opacity:.95}),sampleX,.577,sampleZ);
 const meniscus=ring(lab,.089,.004,new T.MeshBasicMaterial({color:0xe1bbdb,transparent:true,opacity:.5}),sampleX,.607,sampleZ);
 // A compact, abstract gantry liquid handler.
 for(const x of [-1.56,1.56]){
  box(lab,.16,1.65,.2,steel,x,1.21,-.89,.035);
  box(lab,.2,.09,.29,dark,x,.405,-.89,.04);
  box(lab,.2,.09,.29,dark,x,2.052,-.89,.04);
 }
 box(lab,3.32,.19,.25,white,0,2.04,-.89,.05);
 box(lab,3.13,.04,.033,dark,0,2.044,-.744,.015);
 const carriage=new T.Group();carriage.position.set(-1.12,1.95,-.89);lab.add(carriage);
 box(carriage,.42,.41,.32,dark,0,0,.03,.065);
 box(carriage,.24,.22,.024,steel,0,.012,.205,.035);
 const statusLight=mesh(new T.SphereGeometry(.025,16,12),glow(0xb7cbdc,.5),carriage,.084,.06,.228);
 const arm=new T.Group();carriage.add(arm);
 box(arm,.15,.15,1.24,steel,0,-.035,.63,.04);
 box(arm,.1,.02,1.14,edge,0,.052,.64,.012);
 const zGuide=box(arm,.082,.92,.065,steel,0,-.02,1.02,.015);
 const head=new T.Group();head.position.set(0,-.1,1.02);arm.add(head);
 box(head,.29,.42,.29,white,0,-.08,0,.07);
 cylinder(head,.094,.23,steel,0,-.403,0);
 cylinder(head,.068,.12,dark,0,-.578,0);
 cylinder(head,.016,.35,glass,0,-.813,0,.055);
 ring(head,.057,.009,gold,0,-.64,0);
 const drop=mesh(new T.SphereGeometry(.025,24,20),new T.MeshPhysicalMaterial({color:0xb894c0,roughness:.1,transmission:.15,transparent:true,opacity:.9}),lab,sampleX,.8,sampleZ);drop.scale.set(.7,1.15,.7);drop.visible=false;
 // A camera/reader beside the sample, visually distinct from liquid handling.
 box(lab,.2,.18,.26,dark,1.17,.38,.35,.035);
 box(lab,.06,.74,.06,steel,1.17,.78,.35,.015);
 const camera=new T.Group();camera.position.set(.43,1.15,.13);lab.add(camera);
 box(camera,1.58,.17,.27,white,.45,0,0,.055);
 cylinder(camera,.072,.11,dark,-.21,-.105,0);
 ring(camera,.054,.009,blue,-.21,-.167,0);
 const beam=mesh(new T.ConeGeometry(.16,.35,48,1,true),new T.MeshBasicMaterial({color:0x9bbedd,transparent:true,opacity:0,depthWrite:false,side:T.DoubleSide}),lab,sampleX,.79,sampleZ);
 const scan=ring(lab,.16,.008,new T.MeshBasicMaterial({color:0xb7d7ed,transparent:true,opacity:0}),sampleX,.63,sampleZ);
 shadow(lab,0,0,4,2.8,.7);
 return {lab,stocks,carriage,head,arm,zGuide,sample,meniscus,drop,beam,scan,camera,statusLight,sampleX,sampleZ};
}
