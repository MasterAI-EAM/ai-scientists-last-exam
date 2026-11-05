"""Trap distances and F_H_star per grid, from runs/run_keys.json only (numpy-free; the run histories are not shipped).

Part 1 repeats validation/probe.py (which reads the histories) from the stored keys: every baseline key and F_H_star
of the shortcut / wrong-coupling / unextrapolated routes, in units u of the frozen tolerances.
Part 2 lists the unextrapolated F_H_star of every grid that was scanned in F_H (root of g(F) = min over
300 <= t <= 1e4 of dNdot_L/dt, linear between the two scanned F that bracket the sign change, as in probe.py).
Part 3 converts the numerical-parameter shifts of results_details.json into u.

usage: python validation/traps.py
"""
import json, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = json.load(open(os.path.join(HERE, 'runs', 'run_keys.json')))['runs']
ref = json.load(open(os.path.join(HERE, 'results.json')))
tol = {'ndotL_max': 0.015, 't_ndotL_max': 0.03, 'ndotH_max': 0.02, 't_half_H': 0.02, 'seg_max': 0.02,
       'rate_ratio_1e4': 0.03, 'F_H_star': 0.08}
spec = {'ndotL_max': 'NLmax', 't_ndotL_max': 'tLmax', 'ndotH_max': 'NHmax', 't_half_H': 'thalf', 'seg_max': 'rat0.01',
        'rate_ratio_1e4': 'rr1e4'}


def u(k, v):
    return (v / ref[k] - 1) / tol[k]


def fstar(tags):
    tab = sorted((RUNS[t]['args']['FH'], RUNS[t]['gmin']) for t in tags)
    F = [a for a, _ in tab]; G = [b for _, b in tab]
    k = [i for i in range(len(F) - 1) if (G[i] > 0) != (G[i + 1] > 0)]
    j = k[0] if k else (0 if G[0] < 0 else len(F) - 2)
    return F[j] - G[j] * (F[j + 1] - F[j]) / (G[j + 1] - G[j]), tab, bool(k)


def scan(prefixes):
    return [t for t in RUNS if any(t.startswith(p) for p in prefixes)]


def show(name, tag, ftags=None):
    o = RUNS[tag]['keys']; row = []
    for k, q in spec.items():
        v = o.get(q)
        row.append('%s=%s' % (k, 'n/a' if v is None else '%.4g(%+.1fu)' % (v, u(k, v))))
    if ftags:
        r = fstar(ftags)[0]
        row.append('F_H_star=%.4g(%+.1fu)' % (r, u('F_H_star', r)))
    a = RUNS[tag]['args']
    print('%-9s [%s NE %s NR %s]' % (name, tag, a.get('NE'), a.get('NR')), ' '.join(row))


print('# Part 1: baseline keys (F_H = 0.02) and F_H_star of shortcut / wrong / unextrapolated routes; u = frozen tolerance')
print('# reference:', ' '.join('%s=%g' % (k, ref[k]) for k in tol))
show('coarse', 'P_coarse', scan(['P_coarse_F']))
show('1-D', 'd1_def', scan(['D1_F']))
show('halfsum', 'P_halfsum')
show('testH', 'P_testH')
show('NE60', 'e_def', ['e_f005', 'e_F0.0075', 'e_F0.01'])
show('NE80', 'L_80', scan(['S_80_F', 'S2_80_F']))
show('NE90', 'p_90', scan(['s90_F']))
show('NE120', 'L_120', scan(['S_120_F']))
show('NE180', 'L_180n', scan(['S_180n_F']))
show('NE270', 'L_270', scan(['S_270_F']))
print()
print('# Part 2: unextrapolated F_H_star per grid (g in units of 1e-7 per unit time^2)')
grids = [('1-D isotropic FP + steady CK sink, NE 120', scan(['D1_F'])),
         ('natural coarse 2-D (NE 60, NR 24, uniform w, n_theta 32, dlam 0.1, backward Euler, dt <= 50)', scan(['P_coarse_F'])),
         ('careful 2-D NE 60 x NR 24', scan(['e_f005', 'e_F0'])),
         ('careful 2-D NE 80 x NR 32', scan(['S_80_F', 'S2_80_F'])),
         ('careful 2-D NE 90 x NR 36', scan(['s90_F'])),
         ('careful 2-D NE 120 x NR 48', scan(['S_120_F'])),
         ('careful 2-D NE 180 x NR 72', scan(['S_180_F'])),
         ('careful 2-D NE 180 x NR 48', scan(['S_180n_F'])),
         ('careful 2-D NE 270 x NR 48', scan(['S_270_F']))]
for name, tags in grids:
    r, tab, bracketed = fstar(tags)
    print('%-100s F_H_star %.5f (%+.1fu, %+.0f %%)%s' % (name, r, u('F_H_star', r), 100 * (r / ref['F_H_star'] - 1),
                                                        '' if bracketed else '  [linear extrapolation, no sign change]'))
    print('    g(F):', '  '.join('%g: %+.3f' % (F, 1e7 * g) for F, g in tab))
print('reference (Richardson over NE 120 / 180 / 270 at NR 48): F_H_star = %g' % ref['F_H_star'])
print()
print('# Part 3: numerical-parameter shifts at NE 120 x NR 48 (results_details.json), in u; the inner-cut shift R_i(E_0)')
print('# 0.1 -> 0.3 is information only (the cut is part of the stated model). dt: dt_max 25 -> 10 (BDF2); grid: NR 48 -> 72')
print('# with a uniform w-grid; be_rich: backward-Euler Richardson (dt 25 / 12.5); quad: n_theta 96, dlam 0.0125; fit: F root fit')
det = json.load(open(os.path.join(HERE, 'results_details.json')))
for k in tol:
    s = det[k]['shifts']; sc = tol[k] * ref[k]
    print('%-15s' % k, '  '.join('%s %.3f' % (n, v / sc) for n, v in s.items()),
          '  | extrap %.3f  total %.3f  | cut 0.1->0.3 %+.2f' % (det[k]['u_extrap'] / sc, ref['_uncertainty'][k] / sc,
                                                            det[k]['cut_0p3_shift'] / sc))
b, l = RUNS['V_be25']['keys']['tLmax'], RUNS['L_120']['keys']['tLmax']
print('plain backward Euler at dt 25 (V_be25): t_ndotL_max %.1f vs %.1f (%+.1f %%)' % (b, l, 100 * (b / l - 1)))
