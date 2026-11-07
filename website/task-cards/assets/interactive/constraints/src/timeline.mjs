import {ROUNDS as SOURCE,BAND,TARGET} from './story-model.mjs';
export {BAND,TARGET};
export const DURATION=36;
// Later executions are abbreviated; the acquired safety decisions get longer holds.
export const ROUNDS=SOURCE.map((r,i)=>({...r,start:[2.5,8.5,12,19,26][i],end:[8.5,12,19,26,32][i],
 timing:i===0?{dispense:.65,mix:2.50,align:2.82,scan:3.10,observed:3.60}:{dispense:.35,mix:1.48,align:1.72,scan:2.00,observed:2.40}}));
export function stateAt(seconds){
 const t=Math.max(0,Math.min(DURATION-.001,seconds)),intro=t<2.5,summary=t>=32;
 const index=intro?0:summary?4:ROUNDS.findIndex(r=>t>=r.start&&t<r.end),r=ROUNDS[index],u=intro?0:summary?6:t-r.start;
 const timing=r.timing;
 const evidence=!intro&&u>=timing.observed,returned=!intro&&u>=timing.observed+.85;
 const phase=intro?'brief':summary?'verdict':u<timing.dispense?'decide':u<timing.mix?'execute':u<timing.align?'mix':u<timing.scan?'align':u<timing.observed?'measure':u<timing.observed+.35?'result':u<timing.observed+.85?'feedback':'judge';
 const points=intro?[]:ROUNDS.slice(0,index+(evidence?1:0));
 let motion=0;
 if(u>=timing.dispense&&u<timing.mix)motion=2.9+(u-timing.dispense)/(timing.mix-timing.dispense)*6.2;
 else if(u>=timing.mix&&u<timing.align)motion=9.1+(u-timing.mix)/(timing.align-timing.mix)*.98;
 else if(u>=timing.align&&u<timing.scan)motion=10.08+(u-timing.align)/(timing.scan-timing.align)*.6;
 else if(u>=timing.scan&&u<timing.observed)motion=10.68+(u-timing.scan)/(timing.observed-timing.scan)*.67;
 else if(u>=timing.observed)motion=11.65;
 const violations=points.filter(r=>r.status==='unsafe').length,targetReached=points.some(r=>r.status==='target');
 const spectrumVisible=!intro&&!summary&&u>=timing.mix&&u<timing.observed+.35;
 const detailVisible=!intro&&!summary&&u>=timing.dispense&&u<timing.mix;
 const judging=summary||(!intro&&u>=timing.observed+.35);
 return{t,index,r,u,timing,intro,summary,phase,evidence,returned,points,motion,spectrumVisible,detailVisible,judging,violations,targetReached,stopped:violations>=2,started:intro?0:index+(u>=timing.dispense?1:0)};
}
