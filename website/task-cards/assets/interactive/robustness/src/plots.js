import {clear,text,rr} from './stage.js';
export function drawSignal(p,s){const c=clear(p),w=p.c.width,h=p.c.height;
 text(c,'OPTICAL OBSERVATION',52,54,31,'#79978b');text(c,'A changed spectrum is the clue.',52,112,40);
 const L=75,R=w-48,T=174,B=h-116;
 c.strokeStyle='#e1d8e8';c.lineWidth=2;
 for(const n of [0,.5,1]){const y=B-(B-T)*n;c.beginPath();c.moveTo(L,y);c.lineTo(R,y);c.stroke();text(c,n.toFixed(1),L-18,y,22,'#9a87a6','right');}
 const curve=(ratio,progress,color,dashed)=>{c.strokeStyle=color;c.lineWidth=5;c.setLineDash(dashed?[10,8]:[]);c.beginPath();for(let i=0;i<=120*progress;i++){const wavelength=400+i*2.5,peak=.76*Math.exp(-.5*((wavelength-535)/43)**2)+.15*Math.exp(-.5*((wavelength-620)/28)**2),x=L+i*(R-L)/120,y=B-(B-T)*peak*ratio;i?c.lineTo(x,y):c.moveTo(x,y);}c.stroke();c.setLineDash([]);};
 curve(1,1,'#bda9cd',true);if(s.scanning||s.observed)curve(s.r.ratio,s.observed?1:s.scanProgress,s.index===1?'#b97891':'#648e7b',false);
 for(const nm of [400,550,700])text(c,nm+(nm===700?' nm':''),L+(nm-400)*(R-L)/300,B+38,25,'#927f9e','center');
 text(c,'Relative absorbance · schematic',L,T-30,26,'#927f9e');text(c,s.scanning?'Acquiring…':s.observed?(s.index===1?'Lower signal · unexpected observation':'Baseline-like signal acquired'):'Waiting for the sample',52,h-37,29,'#738c7f');p.tex.needsUpdate=true;}
export function drawRecovery(p,s){const c=clear(p),w=p.c.width,h=p.c.height;
 text(c,'RECOVERY AFTER THE CHANGE',60,65,33);text(c,'Same target. Different outcome.',60,138,50,'#614975');
 const L=130,R=w-90,T=258,B=h-245,values=[1,.8,1],xs=[L+120,(L+R)/2,R-90];
 c.lineWidth=2;c.strokeStyle='#e1d9e7';for(const n of [.6,.8,1]){const y=B-(n-.5)/.6*(B-T);c.beginPath();c.moveTo(L,y);c.lineTo(R,y);c.stroke();text(c,n.toFixed(1),L-24,y,28,'#9b86a8','right');}
 text(c,'Baseline-normalized signal · schematic',L,T-55,28,'#9782a5');
 c.setLineDash([10,9]);c.strokeStyle='#b39ac5';const baseY=B-.5/.6*(B-T);c.beginPath();c.moveTo(L,baseY);c.lineTo(R,baseY);c.stroke();c.setLineDash([]);
 c.strokeStyle='#9c81b2';c.lineWidth=6;c.beginPath();for(let i=0;i<s.count;i++){const x=xs[i],y=B-(values[i]-.5)/.6*(B-T);i?c.lineTo(x,y):c.moveTo(x,y);}c.stroke();
 for(let i=0;i<3;i++){const x=xs[i],y=B-(values[i]-.5)/.6*(B-T);text(c,['Baseline','Drift','Revised'][i],x,B+60,33,'#886d9a','center');if(i<s.count){c.fillStyle=i===1?'#b8758f':'#6c947e';c.beginPath();c.arc(x,y,13,0,7);c.fill();text(c,values[i].toFixed(2),x,y-40,38,c.fillStyle,'center',600);}}
 rr(c,60,h-123,w-120,70,17,s.count===3?'#e7f0e9':'#f0e8f5');text(c,s.count===3?'Recovery must be measured again.':s.count===2?'A repeated command no longer behaves the same.':'Establish a baseline before comparing.',w/2,h-88,30,'#715781','center');p.tex.needsUpdate=true;}
export function drawDose(p,s){const c=clear(p),w=p.c.width,h=p.c.height;
 text(c,'TRANSFER CLOSE-UP',35,44,29);text(c,'Viewer explanation · hidden from agent',35,91,24,'#9781a6');
 const rows=[['Commanded A',s.r.command,'#9b80b7'],['Delivered A',s.r.delivered*s.fill,s.index===1?'#bd8096':'#729c87']];
 rows.forEach(([name,val,col],i)=>{const y=167+i*130;text(c,name,35,y,30);text(c,val.toFixed(val===62.5?1:0)+' µL',w-35,y,37,col,'right',600);rr(c,35,y+35,w-70,28,14,'#eee7f4');rr(c,35,y+35,Math.max(2,(w-70)*val/70),28,14,col);});
 text(c,s.index===1?'Illustrated transfer gain: 0.80':'Illustrative one-channel example',35,h-32,24,'#9781a6');p.tex.needsUpdate=true;}
