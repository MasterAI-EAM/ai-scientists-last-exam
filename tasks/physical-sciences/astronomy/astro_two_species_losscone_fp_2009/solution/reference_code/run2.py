import time, json, math, argparse
import numpy as np
from fp2 import TwoSp

ap = argparse.ArgumentParser()
ap.add_argument('--mL', type=float, default=1e-5)
ap.add_argument('--mH', type=float, default=1e-4)
ap.add_argument('--FH', type=float, default=0.02)
ap.add_argument('--rtL', type=float, default=3e-5)
ap.add_argument('--rtH', type=float, default=1e-5)
ap.add_argument('--RcutL', type=float, default=0.1)
ap.add_argument('--RcutH', type=float, default=0.1)
ap.add_argument('--NE', type=int, default=120)
ap.add_argument('--NR', type=int, default=48)
ap.add_argument('--amap', type=float, default=0.5)
ap.add_argument('--nth', type=int, default=48)
ap.add_argument('--dlam', type=float, default=0.025)
ap.add_argument('--bc', default='ck')
ap.add_argument('--nocoup', action='store_true')
ap.add_argument('--variant', default='ok')
ap.add_argument('--dt0', type=float, default=1e-3)
ap.add_argument('--grow', type=float, default=1.05)
ap.add_argument('--dtmax', type=float, default=10.0)
ap.add_argument('--tend', type=float, default=3000.0)
ap.add_argument('--order', type=int, default=2)
ap.add_argument('--beta', type=float, default=0.0)
ap.add_argument('--radii', default='0.001,0.002,0.003,0.005,0.01,0.02,0.03')
ap.add_argument('--snap', default='')
ap.add_argument('--out', default='runs/test')
a = ap.parse_args()

m = TwoSp(mL=a.mL, mH=a.mH, FH=a.FH, rtL=a.rtL, rtH=a.rtH, RcutL=a.RcutL, RcutH=a.RcutH, NE=a.NE, NR=a.NR,
          amap=a.amap, nth=a.nth, dlam=a.dlam, bc=a.bc, coupling=not a.nocoup, variant=a.variant)
m.init(beta=a.beta)
radii = [float(r) for r in a.radii.split(',')]
snaps = [float(s) for s in a.snap.split(',')] if a.snap else []
M0 = m.masses()
T, NL, NH, ML, MH = [0.0], [np.nan], [np.nan], [M0[0]], [M0[1]]
IN = [[x for r in radii for x in m.mass_inside(r)]]
EN = [[float(np.sum(sp_.V * sp_.f * sp_.Ec[:, None])) for sp_ in m.S] + [0.0, 0.0]]
SN = {}
dt = a.dt0
t0 = time.time(); k = 0
while m.t < a.tend - 1e-12:
    dtt = min(dt, a.tend - m.t)
    for s in snaps:
        if m.t < s - 1e-12 and m.t + dtt > s + 1e-12:
            dtt = s - m.t
    md = m.step(dtt, order=a.order)
    k += 1
    Ms = m.masses()
    T.append(m.t); NL.append(md[0] / a.mL); NH.append(md[1] / a.mH); ML.append(Ms[0]); MH.append(Ms[1])
    IN.append([x for r in radii for x in m.mass_inside(r)])
    EN.append([float(np.sum(sp_.V * sp_.f * sp_.Ec[:, None])) for sp_ in m.S] + [float(np.sum(sp_.Fq * sp_.Ec)) for sp_ in m.S])
    for s in snaps:
        if abs(m.t - s) < 1e-9 * max(1, s):
            SN['%g' % s] = dict(fL=m.S[0].f.copy(), fH=m.S[1].f.copy(), qL=m.S[0].q.copy(), qH=m.S[1].q.copy(),
                                FqL=m.S[0].Fq.copy(), FqH=m.S[1].Fq.copy())
    if k % 50 == 0:
        print('k %d t %.5g dt %.3g NdL %.5g NdH %.5g ML %.6f MH %.6f nneg %d/%d wall %.1f' % (
            k, m.t, dtt, NL[-1], NH[-1], Ms[0], Ms[1], m.S[0].nneg, m.S[1].nneg, time.time() - t0), flush=True)
    dt = min(dt * a.grow, a.dtmax)
T = np.array(T); NL = np.array(NL); NH = np.array(NH)
ML = np.array(ML); MH = np.array(MH)
iL = np.sum(0.5 * (NL[2:] + NL[1:-1]) * np.diff(T[1:])) * a.mL
iH = np.sum(0.5 * (NH[2:] + NH[1:-1]) * np.diff(T[1:])) * a.mH
print('done steps', k, 'wall %.1f' % (time.time() - t0), 'lossL', ML[0] - ML[-1], iL, 'lossH', MH[0] - MH[-1], iH)
np.savez(a.out + '.npz', T=T, NL=NL, NH=NH, ML=ML, MH=MH, IN=np.array(IN), EN=np.array(EN), radii=np.array(radii),
         EcL=m.S[0].Ec, EcH=m.S[1].Ec, rcL=m.S[0].rcc, rcH=m.S[1].rcc, VL=m.S[0].V, VH=m.S[1].V,
         fL=m.S[0].f, fH=m.S[1].f, qL=m.S[0].q, qH=m.S[1].q, FqL=m.S[0].Fq, FqH=m.S[1].Fq,
         **{('snap_' + k2 + '_' + kk): vv for k2, d in SN.items() for kk, vv in d.items()})
json.dump(vars(a), open(a.out + '.json', 'w'))
