export const DURATION=40,starts=[2,10,18,26],pHs=[2.4,4.8,3.5,3.8],buffers=[2.4,2.8,3.2,3.5,3.8,4.2,4.8];
const clamp=x=>Math.max(0,Math.min(1,x));
export function stateAt(t){t=Math.max(0,Math.min(DURATION-.001,t));const intro=t<2,summary=t>=34,index=Math.min(3,Math.max(0,Math.floor((t-2)/8))),u=Math.max(0,t-starts[index]),observed=!intro&&u>=5.3;
 const phase=intro?'intro':summary?'summary':u<.7?'select':u<3.8?'transfer':u<4.2?'mix':u<4.8?'align':u<5.3?'scan':u<6.2?'feedback':'interpret';
 return{t,intro,summary,index,u,pH:pHs[index],phase,observed,count:intro?0:index+Number(observed),scanning:phase==='scan',scanProgress:clamp((u-4.8)/.5),fill:intro?0:clamp((u-1.65)/2.15),feedback:phase==='feedback'?clamp((u-5.3)/.9):-1};
}
