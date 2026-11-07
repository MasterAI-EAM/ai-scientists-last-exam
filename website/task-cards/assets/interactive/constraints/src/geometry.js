import * as T from 'three';
export const palette={gold:0xd2b58b,blue:0xaac6dd,ink:0x101923,steel:0x637686,light:0xd5dee4,target:0xae87ba};
export const material=(color,metalness=.35,roughness=.35)=>new T.MeshStandardMaterial({color,metalness,roughness});
export const dark=material(0x17222c,.7,.29),steel=material(0x90a1ad,.8,.25),edge=material(0x263947,.68,.28);
export const gold=material(palette.gold,.65,.27),blue=material(palette.blue,.5,.25);
export function mesh(geometry,mat,parent,x=0,y=0,z=0){const m=new T.Mesh(geometry,mat);m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m}
export function box(parent,w,h,d,mat,x=0,y=0,z=0,r=.06){
 const shape=new T.Shape(),a=w/2,b=d/2;r=Math.min(r,a,b);
 shape.moveTo(-a+r,-b);shape.lineTo(a-r,-b);shape.quadraticCurveTo(a,-b,a,-b+r);shape.lineTo(a,b-r);shape.quadraticCurveTo(a,b,a-r,b);shape.lineTo(-a+r,b);shape.quadraticCurveTo(-a,b,-a,b-r);shape.lineTo(-a,-b+r);shape.quadraticCurveTo(-a,-b,-a+r,-b);
 const geo=new T.ExtrudeGeometry(shape,{depth:h-.02,bevelEnabled:true,bevelSegments:3,steps:1,bevelSize:.01,bevelThickness:.01,curveSegments:8});
 geo.rotateX(-Math.PI/2);geo.translate(0,-h/2,0);return mesh(geo,mat,parent,x,y,z);
}
export function cylinder(parent,r,h,mat,x=0,y=0,z=0,top=r){return mesh(new T.CylinderGeometry(top,r,h,64),mat,parent,x,y,z)}
export function ring(parent,r,tube,mat,x=0,y=0,z=0,arc=Math.PI*2){const m=mesh(new T.TorusGeometry(r,tube,12,128,arc),mat,parent,x,y,z);m.rotation.x=Math.PI/2;return m}
export function line(parent,points,color=palette.blue,opacity=.35){const geo=new T.BufferGeometry().setFromPoints(points.map(p=>new T.Vector3(...p)));const l=new T.Line(geo,new T.LineBasicMaterial({color,transparent:true,opacity}));parent.add(l);return l}
export function glow(color,intensity=.6){return new T.MeshStandardMaterial({color,emissive:color,emissiveIntensity:intensity,roughness:.45,metalness:.2})}
export function glassMaterial(){return new T.MeshPhysicalMaterial({color:0xc8d8e2,metalness:0,roughness:.08,transmission:.72,thickness:.12,ior:1.45,transparent:true,opacity:.55,side:T.DoubleSide,depthWrite:false})}
export function tube(parent,r,h,mat,x=0,y=0,z=0){
 const profile=[new T.Vector2(r-.035,0),new T.Vector2(r,.03),new T.Vector2(r,h),new T.Vector2(r-.025,h),new T.Vector2(r-.025,.07),new T.Vector2(0,.07)];
 return mesh(new T.LatheGeometry(profile,64),mat,parent,x,y,z);
}
export function shadow(parent,x,z,sx,sz,opacity=.55){
 const c=document.createElement('canvas');c.width=128;c.height=128;const ctx=c.getContext('2d'),gr=ctx.createRadialGradient(64,64,4,64,64,64);gr.addColorStop(0,'rgba(0,0,0,.8)');gr.addColorStop(1,'rgba(0,0,0,0)');ctx.fillStyle=gr;ctx.fillRect(0,0,128,128);
 const m=new T.Mesh(new T.PlaneGeometry(sx,sz),new T.MeshBasicMaterial({map:new T.CanvasTexture(c),transparent:true,opacity,depthWrite:false}));m.rotation.x=-Math.PI/2;m.position.set(x,.008,z);parent.add(m);return m;
}
export function textTexture(text,width=512,height=128,size=40,color='#b7cbdc'){
 const c=document.createElement('canvas');c.width=width;c.height=height;const ctx=c.getContext('2d');ctx.fillStyle=color;ctx.font=size+'px DM';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,width/2,height/2);const tex=new T.CanvasTexture(c);tex.colorSpace=T.SRGBColorSpace;return tex;
}
export function label3d(parent,text,w=.7,h=.17,x=0,y=0,z=0,color='#b7cbdc'){
 const m=mesh(new T.PlaneGeometry(w,h),new T.MeshBasicMaterial({map:textTexture(text,512,128,42,color),transparent:true,depthWrite:false}),parent,x,y,z);return m;
}
