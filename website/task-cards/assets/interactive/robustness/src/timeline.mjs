export const DURATION=38;
export const rounds=[
 {start:2,end:12,command:50,delivered:50,colour:'#9b85bc',name:'Baseline',ratio:1},
 {start:12,end:23,command:50,delivered:40,colour:'#b799ae',name:'Hidden drift',ratio:.8},
 {start:23,end:34,command:62.5,delivered:50,colour:'#9b85bc',name:'Recovery',ratio:1}
];
export const clamp=x=>Math.max(0,Math.min(1,x));
export function stateAt(t){
 t=Math.max(0,Math.min(DURATION-.001,t));const intro=t<2,summary=t>=34;
 const index=t<12?0:t<23?1:2,r=rounds[index],u=Math.max(0,t-r.start);
 const observed=!intro&&u>=6.6,count=intro?0:index+Number(observed);
 const phase=intro?'intro':summary?'summary':u<.9?'decide':u<4?'dispense':u<4.6?'mix':u<5.2?'align':u<6.6?'scan':u<7.4?'feedback':'compare';
 return{t,intro,summary,index,r,u,phase,observed,count,scanning:phase==='scan',scanProgress:clamp((u-5.2)/1.4),fill:intro?0:clamp((u-2.5)/1.5),feedback:phase==='feedback'?clamp((u-6.6)/.8):-1};
}
