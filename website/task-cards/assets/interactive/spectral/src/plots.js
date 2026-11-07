import {clear,text,rr} from './stage.js';
const colors=['#bd7794','#bc9b62','#9477b0','#6c9d91'];
export function drawSpectra(p,s,data){const c=clear(p),w=p.c.width,h=p.c.height;
 text(c,'ABSORPTION / 380–780 nm',55,65,35,'#738e87');text(c,'Each pH reveals a different mixture.',55,135,44);
 const L=105,R=w-55,T=223,B=h-155;
 c.strokeStyle='#e0d8e8';c.lineWidth=2;for(const a of [0,.5,1]){const y=B-(B-T)*a;c.beginPath();c.moveTo(L,y);c.lineTo(R,y);c.stroke();text(c,a.toFixed(1),L-22,y,27,'#9a87a6','right');}
 const gradient=c.createLinearGradient(L,0,R,0);['#af8aca','#83a6c0','#91b0a3','#c5bb8a','#ce9b9a'].forEach((col,i)=>gradient.addColorStop(i/4,col));c.fillStyle=gradient;c.fillRect(L,B+42,R-L,5);
 for(let i=0;i<4;i++){const visible=i<s.count||(i===s.index&&s.scanning);if(!visible)continue;const progress=i<s.count?1:s.scanProgress,n=Math.floor((data.wavelength_nm.length-1)*progress);c.strokeStyle=colors[i];c.lineWidth=i===s.index?5.5:3.6;c.beginPath();for(let k=0;k<=n;k++){const x=L+k/(data.wavelength_nm.length-1)*(R-L),y=B-(B-T)*data.absorbance[i][k];k?c.lineTo(x,y):c.moveTo(x,y);}c.stroke();text(c,'pH '+data.pH[i].toFixed(1),L+i*(R-L)/4,h-45,29,colors[i]);}
 for(const nm of [380,580,780])text(c,nm+(nm===780?' nm':''),L+(nm-380)/400*(R-L),B+82,27,'#927f9e','center');text(c,'Synthetic absorbance / a.u.',L,T-45,26,'#9782a5');p.tex.needsUpdate=true;}
export function drawInference(p,s,data){const c=clear(p),w=p.c.width,h=p.c.height;
 text(c,'INFER · SUBMIT · VERIFY',56,58,34);text(c,s.count===4?'One transition resolved.':'Locate the hidden transition.',56,128,43);
 const L=90,R=w-58,T=243,B=h-350;
 c.strokeStyle='#ded4e7';c.lineWidth=2;for(const a of [0,.5,1]){const y=B-a*(B-T);c.beginPath();c.moveTo(L,y);c.lineTo(R,y);c.stroke();text(c,a.toFixed(1),L-20,y,25,'#9a87a6','right');}
 if(s.count===4){c.strokeStyle='#9b80b7';c.lineWidth=5;c.beginPath();for(let i=0;i<=140;i++){const ph=2+i*3.2/140,f=1/(1+10**(data.estimated_pKa-ph)),x=L+i*(R-L)/140,y=B-f*(B-T);i?c.lineTo(x,y):c.moveTo(x,y);}c.stroke();}
 const show=s.count===4?4:Math.min(s.count,2);for(let i=0;i<show;i++){const ph=data.pH[i],f=1/(1+10**(data.assumed_true_pKa-ph)),x=L+(ph-2)/3.2*(R-L),y=B-f*(B-T);c.fillStyle=colors[i];c.beginPath();c.arc(x,y,10,0,7);c.fill();}
 text(c,'2.0',L,B+42,26,'#927f9e','center');text(c,'pH',R,B+42,26,'#927f9e','right');text(c,'Base-form fraction · model illustration',L,T-46,26,'#9782a5');
 rr(c,48,h-248,w-96,185,23,s.count===4?'#e8f0ea':'#f0e8f5');
 text(c,s.count===4?'pKa = '+data.estimated_pKa.toFixed(3):'pKa = ?',w/2,h-191,66,'#70548b','center',600);
 text(c,s.count===4?'95% CI  '+data.CI95.map(x=>x.toFixed(3)).join(' – '):s.count+' acquired spectra / 8 actions',w/2,h-116,29,'#6f8878','center');
 text(c,s.count===4?'Conditional synthetic fit · known basis / noise':'New observations determine the next pH.',w/2,h-33,25,'#9a86a7','center');p.tex.needsUpdate=true;}
export function drawSelection(p,s){const c=clear(p);text(c,'NEXT BUFFER',52,70,50);text(c,'pH '+s.pH.toFixed(1),p.c.width-52,208,89,'#77538f','right',600);text(c,'Fixed indicator dose',52,188,43,'#927ba4');text(c,'Illustrative decision',52,p.c.height-52,38,'#a08cad');p.tex.needsUpdate=true;}
