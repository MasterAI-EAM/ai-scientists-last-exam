const source=await (await fetch('../assets/absorption-example.json')).json();
const canvas=document.getElementById('spectrum-canvas');canvas.width=1374;canvas.height=753;
const ctx=canvas.getContext('2d');ctx.scale(3,3);
const X=v=>48+(v-380)/400*390,Y=v=>193-v/.8*159;
await document.fonts.load('10px DM');
function draw(){
 ctx.clearRect(0,0,458,251);
 ctx.font='9px DM';ctx.fillStyle='#90729f';ctx.fillText('Absorbance (OD)',48,17);
 for(const y of [0,.2,.4,.6,.8]){ctx.strokeStyle='#e9e0ef';ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(48,Y(y));ctx.lineTo(438,Y(y));ctx.stroke();ctx.textAlign='right';ctx.fillStyle='#aa92b8';ctx.fillText(y.toFixed(1),38,Y(y)+3);}
 ctx.textAlign='center';for(const x of [400,500,600,700,780]){ctx.fillStyle='#9c82ae';ctx.fillText(x,X(x),214);}
 ctx.textAlign='right';ctx.fillStyle='#a08bb0';ctx.fillText('Wavelength (nm)',438,238);
 const fill=ctx.createLinearGradient(0,40,0,193);fill.addColorStop(0,'#b99dc850');fill.addColorStop(1,'#b99dc807');
 ctx.beginPath();ctx.moveTo(X(source.points[0][0]),193);for(const[x,y]of source.points)ctx.lineTo(X(x),Y(y));ctx.lineTo(X(source.points.at(-1)[0]),193);ctx.closePath();ctx.fillStyle=fill;ctx.fill();
 ctx.beginPath();source.points.forEach(([x,y],i)=>i?ctx.lineTo(X(x),Y(y)):ctx.moveTo(X(x),Y(y)));
 ctx.strokeStyle='#9672b227';ctx.lineWidth=5;ctx.lineJoin='round';ctx.lineCap='round';ctx.stroke();
 const grad=ctx.createLinearGradient(48,0,438,0);grad.addColorStop(0,'#9674b8');grad.addColorStop(.45,'#927ba7');grad.addColorStop(1,'#6f9596');ctx.strokeStyle=grad;ctx.lineWidth=1.75;ctx.stroke();
 const band=ctx.createLinearGradient(48,0,438,0);for(const[p,c]of [[0,'#9585b3'],[.18,'#8e9ec2'],[.38,'#8ab4aa'],[.57,'#c6c698'],[.72,'#d1af93'],[1,'#bd8c9e']])band.addColorStop(p,c);ctx.fillStyle=band;ctx.globalAlpha=.5;ctx.fillRect(48,198,390,3);ctx.globalAlpha=1;
 for(const [x,y,label,dx] of [[440.1,.7075,'≈440 nm',20],[587.9,.5837,'≈588 nm',22]]){const px=X(x),py=Y(y);ctx.strokeStyle='#bfa9cd';ctx.lineWidth=.8;ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(px,py+7);ctx.lineTo(px,193);ctx.stroke();ctx.setLineDash([]);ctx.beginPath();ctx.arc(px,py,3,0,Math.PI*2);ctx.fillStyle='#9671ae';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();ctx.font='500 10px DM';ctx.fillStyle='#8d69a5';ctx.textAlign='left';ctx.fillText(label,px+dx,py-10);ctx.strokeStyle='#c6b4d0';ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(px+4,py-4);ctx.quadraticCurveTo(px+10,py-14,px+dx-4,py-14);ctx.stroke();}
}
draw();
export const spectrumProvenance=source.status;
