import sys, time, json, math, argparse
import numpy as np
from fpsolve import LCFP

ap = argparse.ArgumentParser()
ap.add_argument('--mu', type=float, default=0.01)
ap.add_argument('--rt', type=float, default=3e-5)
ap.add_argument('--N', type=float, default=1e5)
ap.add_argument('--lnL', type=float, default=10.0)
ap.add_argument('--Eb', type=float, default=-0.1)
ap.add_argument('--Rcut', type=float, default=0.1)
ap.add_argument('--NE', type=int, default=120)
ap.add_argument('--NR', type=int, default=48)
ap.add_argument('--amap', type=float, default=0.5)
ap.add_argument('--pmap', type=float, default=1.0)
ap.add_argument('--nth', type=int, default=48)
ap.add_argument('--dlam', type=float, default=0.025)
ap.add_argument('--bc', default='ck')
ap.add_argument('--dt0', type=float, default=1e-3)
ap.add_argument('--grow', type=float, default=1.05)
ap.add_argument('--dtmax', type=float, default=5.0)
ap.add_argument('--tend', type=float, default=3000.0)
ap.add_argument('--order', type=int, default=2)
ap.add_argument('--snap', default='')
ap.add_argument('--out', default='runs/test')
ap.add_argument('--beta', type=float, default=0.0)
a = ap.parse_args()

m = LCFP(mu=a.mu, rt=a.rt, N=a.N, lnL=a.lnL, Eb=a.Eb, Rcut=a.Rcut, NE=a.NE, NR=a.NR, amap=a.amap,
         pmap=a.pmap, nth=a.nth, dlam=a.dlam, bc=a.bc)
m.init_adiabatic()
if a.beta > 0:
    m.f = m.f * (1 - a.beta) * m.Rcen ** (-a.beta)
M0 = m.mass()
snaps = [float(s) for s in a.snap.split(',')] if a.snap else []
T, ND, MM, NN = [0.0], [float('nan')], [M0], [0]
SN = {}
dt = a.dt0
t0 = time.time()
k = 0
while m.t < a.tend - 1e-12:
    dtt = min(dt, a.tend - m.t)
    # land exactly on snapshot times
    for s in snaps:
        if m.t < s - 1e-12 and m.t + dtt > s + 1e-12:
            dtt = s - m.t
    m.step(dtt, order=a.order)
    k += 1
    T.append(m.t); ND.append(m.Mdot * a.N); MM.append(m.mass()); NN.append(m.nneg)
    for s in snaps:
        if abs(m.t - s) < 1e-9 * max(1, s):
            SN['%g' % s] = dict(f=m.f.copy(), Fq=m.Fq.copy(), q=m.q.copy(), fb=m.res['fb'].copy())
    if k % 50 == 0:
        print('k %d t %.4g dt %.3g Ndot %.5g M %.6f nneg %d wall %.1f' % (k, m.t, dtt, m.Mdot * a.N, MM[-1], m.nneg, time.time() - t0), flush=True)
    dt = min(dt * a.grow, a.dtmax)
T = np.array(T); ND = np.array(ND); MM = np.array(MM)
print('done steps', k, 'wall', time.time() - t0, 'mass lost', M0 - MM[-1], 'integrated', np.sum(0.5 * (ND[2:] + ND[1:-1]) * np.diff(T[1:])) / a.N)
np.savez(a.out + '.npz', T=T, ND=ND, MM=MM, NN=np.array(NN), Ec=m.Ec, Ef=m.Ef, rcc=m.rcc, Rlc=m.Rlc_c,
         wc=m.wc, V=m.V, f=m.f, Fq=m.Fq, q=m.q, fb=m.res['fb'], dE=m.dE,
         **{('snap_' + k2 + '_' + kk): vv for k2, d in SN.items() for kk, vv in d.items()})
json.dump(vars(a), open(a.out + '.json', 'w'))
