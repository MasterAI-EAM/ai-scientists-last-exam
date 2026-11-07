import * as T from 'three';

// Rasterize vector marks at display resolution, instead of their intrinsic 1em size.
async function vectorImage(name){
 const response=await fetch('icons/'+name+'.svg');
 if(!response.ok)throw Error('Missing brand icon: '+name);
 const original=await response.text();
 const svg=original.replace(/width="1em"/g,'width="512"').replace(/height="1em"/g,'height="512"').replace(/currentColor/g,'#292132');
 const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));
 try{const image=new Image();image.src=url;await image.decode();return image;}finally{URL.revokeObjectURL(url);}
}
function canvas(w,h){const el=document.createElement('canvas');el.width=w;el.height=h;return{el,c:el.getContext('2d')};}
function rounded(c,x,y,w,h,r,fill,stroke){c.beginPath();c.roundRect(x,y,w,h,r);c.fillStyle=fill;c.fill();if(stroke){c.strokeStyle=stroke;c.lineWidth=2;c.stroke();}}
function text(c,value,x,y,size,color,weight='500'){c.font=weight+' '+size+'px DM';c.fillStyle=color;c.textAlign='center';c.textBaseline='middle';c.fillText(value,x,y);}

export async function createAgentDisplay(agent,texturePlane,box,mats){
 const names=['openai','codex','claude','gemini','deepseek'];
 const images=await Promise.all(names.map(vectorImage));
 const width=3.5,height=1.70,board=canvas(1750,850),c=board.c;
 const labels=['GPT','Codex','Claude','Gemini','DeepSeek'];
 rounded(c,0,0,1750,850,48,'#fdfbff','#d3c3df');
 text(c,'AGENTS / MODELS',875,96,78,'#51365f','600');
 text(c,'Examples · evaluated separately',875,190,48,'#8b7598');
 const tiles=labels.map((name,i)=>{
  const x=40+i*336;
  rounded(c,x,265,326,465,34,'#ffffff','#e5dcea');
  c.drawImage(images[i],x+33,307,260,260);
  text(c,name,x+163,650,62,'#4b365b','600');
  return {name,x,y:265,width:326,height:465,iconSize:260,labelSize:62};
 });
 // One shared enclosure and one output, with no privileged model or active highlight.
 const back=box(agent,width+.16,.18,height+.16,mats.deep,0,1.42,-.37,.13);back.rotation.x=Math.PI/2;
 box(agent,.22,.64,.22,mats.chrome,0,.53,-.37,.04);
 const panelMesh=texturePlane(agent,new T.CanvasTexture(board.el),width,height,0,1.42,-.265);
 return{panelMesh,width,height,info:{title:'Agents / Models',layout:'equal peers',labels,tiles,iconRasterSize:512,panelTexture:[1750,850],evaluatedSeparately:true,collectiveReplay:false}};
}
