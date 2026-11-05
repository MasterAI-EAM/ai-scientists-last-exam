"""Reference values from the NE ladder 120 / 180 / 270 at NR = 48 (ratio 1.5; the energy grid dominates the error),
produced by run2.py / fp2.py / lc2.py / lcfp.py (queue files jobs*.txt).  Baseline F_H = 0.02 keys from runs L_120,
L_180n, L_270; F_H_star from runs S_<tag>_F<F> (root of g(F) = min_{300<=t<=1e4} dNdot_L/dt; linear/quadratic in F).
Cross-check: the (NE,NR) ladder 80x32 / 120x48 / 180x72 (runs L_80, L_120, L_180; S_80, S_120, S_180).
Extrapolation: observed-order Richardson (as in the accepted single-species task); uncertainty = |p_obs vs p=2|
+ 0.1 x last increment, combined in quadrature with integrator / grid / quadrature / inner-cut shifts (runs V_*, W_*)."""
import json, math, glob, numpy as np
from keys2 import keys, gmin

TAGS = ('120', '180n', '270')


def rich(v1, v2, v3, r=1.5):
    d1, d2 = v2 - v1, v3 - v2
    p = math.log(abs(d1 / d2)) / math.log(r) if d1 * d2 > 0 and d2 != 0 else 2.0
    p = min(max(p, 1.0), 3.0)
    e_p = v3 + d2 / (r ** p - 1)
    e_2 = v3 + d2 / (r ** 2 - 1)
    return 0.5 * (e_p + e_2), abs(e_p - e_2) + 0.1 * abs(d2), p


def g_of(fn):
    d = np.load(fn)
    return gmin(d['T'][1:], d['NL'][1:])


def fstar(tag):
    fs = sorted(glob.glob('runs/S_%s_F*.npz' % tag) + glob.glob('runs/S2_%s_F*.npz' % tag))
    F = np.array([float(f.split('_F')[-1][:-4]) for f in fs]); G = np.array([g_of(f) for f in fs])
    o = np.argsort(F); F, G = F[o], G[o]
    # preliminary root from the sign change (or nearest pair), then the 3 points nearest to it
    k = np.where(np.sign(G[1:]) != np.sign(G[:-1]))[0]
    j = k[0] if len(k) else (0 if G[0] < 0 else len(F) - 2)
    r0 = F[j] - G[j] * (F[j + 1] - F[j]) / (G[j + 1] - G[j])
    sel = np.argsort(abs(F - r0))[:3]
    Fs, Gs = F[sel], G[sel]
    roots = [r0]
    if len(Fs) == 3:
        c = np.polyfit(Fs - r0, Gs, 2)
        rr = np.roots(c).real + r0
        roots.append(float(rr[np.argmin(abs(rr - r0))]))
    slope = float((G[j + 1] - G[j]) / (F[j + 1] - F[j]))
    return roots[-1], abs(roots[-1] - roots[0]), slope, dict(zip(F.tolist(), G.tolist()))


spec = {'ndotL_max': 'NLmax', 't_ndotL_max': 'tLmax', 'ndotH_max': 'NHmax', 't_half_H': 'thalf',
        'seg_max': 'rat0.01', 'rate_ratio_1e4': 'rr1e4'}
L = [keys('runs/L_%s.npz' % t) for t in TAGS]
import os
V = {n: keys('runs/V_%s.npz' % n) for n in ('dt', 'be25', 'be12', 'grid', 'quad', 'rc3') if os.path.exists('runs/V_%s.npz' % n)}
X = [keys('runs/L_%d.npz' % ne) for ne in (80, 120, 180)]
res, unc, det = {}, {}, {}
for k, q in spec.items():
    v = [Li[q] for Li in L]
    val1, u1, p = rich(*v)
    xv = rich(*[Xi[q] for Xi in X])
    val = 0.5 * (val1 + xv[0])                 # mean of the fixed-NR and the NR-scaled ladder extrapolations
    u = max(u1, xv[1]) + 0.5 * abs(val1 - xv[0])
    base = L[0][q]                              # validation runs V_* are at NE 120 x NR 48 = L_120
    dcut = V['rc3'][q] - base          # inner cut is part of the stated model (R_i(E_0) = 0.1): info only
    sh = {'dt': abs(V['dt'][q] - base), 'grid': abs(V['grid'][q] - base)}
    if 'be12' in V:
        sh['be_rich'] = abs(2 * V['be12'][q] - V['be25'][q] - base)
    if 'quad' in V:
        sh['quad'] = abs(V['quad'][q] - base)
    ut = math.sqrt(u ** 2 + sum(s ** 2 for s in sh.values()))
    res[k] = float('%.5g' % val); unc[k] = float('%.2g' % ut)
    det[k] = dict(ladder=v, p=p, extrap_fixedNR=val1, cross_ladder=[Xi[q] for Xi in X], p_cross=xv[2], cross_extrap=xv[0],
                  final=val, u_extrap=u, shifts=sh, cut_0p3_shift=dcut)

# ---- F_H_star
fl, ufit, slope = [], [], None
for tag in TAGS:
    r, uf, sl, tab = fstar(tag)
    fl.append(r); ufit.append(uf)
    det['Fstar_%s' % tag] = dict(root=r, fit_unc=uf, g_table=tab)
    if tag == '120':
        slope = sl

val1, u1, p = rich(*fl)
xf = [fstar(t)[0] for t in ('80', '120', '180')]
xv = rich(*xf)
# F*: the NE = 80 point of the NR-scaled ladder is pre-asymptotic (p = 2.7); use the fixed-NR ladder (p = 2.1)
# and add half the difference to the NR-scaled extrapolation (NR itself moves F* by only 0.25 %, run W_grid)
val = val1; u = u1 + 0.5 * abs(val1 - xv[0])
W = {n: g_of('runs/W_%s_F0.0044.npz' % n) for n in ('dt', 'grid', 'rc3') if os.path.exists('runs/W_%s_F0.0044.npz' % n)}
g0 = g_of('runs/S_120_F0.0044.npz')
dF = lambda dg: -dg / slope
dcut = dF(W['rc3'] - g0) if 'rc3' in W else float('nan')  # info only (stated inner boundary)
sh = {'dt': abs(dF(W['dt'] - g0)), 'grid': abs(dF(W['grid'] - g0)), 'fit': max(ufit)}
ut = math.sqrt(u ** 2 + sum(s ** 2 for s in sh.values()))
res['F_H_star'] = float('%.4g' % val); unc['F_H_star'] = float('%.2g' % ut)
det['F_H_star'] = dict(ladder=fl, p=p, extrap_fixedNR=val1, cross_ladder=xf, p_cross=xv[2], cross_extrap=xv[0], final=val, u_extrap=u, shifts=sh, slope_dg_dF=slope, cut_0p3_shift=dcut)
res['_uncertainty'] = unc
json.dump(res, open('results.json', 'w'), indent=1)
json.dump(det, open('results_details.json', 'w'), indent=1)
print(json.dumps(res, indent=1))
