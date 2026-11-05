import time, json, argparse
import numpy as np
from fp1d2 import FP1D2

ap = argparse.ArgumentParser()
ap.add_argument('--mL', type=float, default=1e-5)
ap.add_argument('--mH', type=float, default=1e-4)
ap.add_argument('--FH', type=float, default=0.02)
ap.add_argument('--rtH', type=float, default=1e-5)
ap.add_argument('--NE', type=int, default=120)
ap.add_argument('--NR', type=int, default=48)
ap.add_argument('--dtmax', type=float, default=10.0)
ap.add_argument('--tend', type=float, default=20000.0)
ap.add_argument('--out', default='runs/d1')
a = ap.parse_args()
m = FP1D2(mL=a.mL, mH=a.mH, FH=a.FH, rtH=a.rtH, NE=a.NE, NR=a.NR)
m.init1d()
M0 = m.masses()
T, NL, NH, ML, MH = [0.0], [np.nan], [np.nan], [M0[0]], [M0[1]]
dt = 1e-3; t0 = time.time(); k = 0
while m.t < a.tend - 1e-12:
    dtt = min(dt, a.tend - m.t)
    md = m.step(dtt); k += 1
    Ms = m.masses()
    T.append(m.t); NL.append(md[0] / a.mL); NH.append(md[1] / a.mH); ML.append(Ms[0]); MH.append(Ms[1])
    if k % 100 == 0:
        print('k %d t %.5g NdL %.5g NdH %.5g wall %.1f' % (k, m.t, NL[-1], NH[-1], time.time() - t0), flush=True)
    dt = min(dt * 1.05, a.dtmax)
np.savez(a.out + '.npz', T=np.array(T), NL=np.array(NL), NH=np.array(NH), ML=np.array(ML), MH=np.array(MH))
json.dump(vars(a), open(a.out + '.json', 'w'))
print('done', k, time.time() - t0)
