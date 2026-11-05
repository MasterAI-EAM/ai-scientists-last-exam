"""Extract every per-run number that solve_reference.py, validation/traps.py and validation/probe.py read from the
run histories into runs/run_keys.json (the histories runs/*.npz, about 13 MB, are not shipped).

For each run tag:
  script    = the driver that wrote it: run2.py (2-D two-species), run1d2.py (1-D trap: d1_def, D1_*) or run1.py
              (the accepted single-species driver: t_single, the split test);
  args      = its argument set (runs/<tag>.json);
  keys      = keys2.keys('runs/<tag>.npz') for run2.py runs, i.e. exactly what solve_reference.py uses (NaN -> null);
              for the 1-D runs the k1d() of validation/probe.py (no N(<r) diagnostic, seg_max = null);
  gmin      = keys2.gmin(T[1:], NL[1:]) = min over 300 <= t <= 1e4 of dNdot_L/dt, the quantity whose root in F_H is
              F_H_star (solve_reference.g_of reads exactly this);
  t_end, nsteps, M0 / M_end per species (after the t = 0 removal / at the end), Ndot_L and Ndot_H at t = 100, 1000,
  5000, 10000, and the 'done' line of logs/<tag>.log (steps, wall, mass lost vs time-integrated Ndot m, per species).

usage (in the reference build directory, with runs/ and logs/ present): python validation/extract_run_keys.py [out]
"""
import glob, json, math, os, sys
import numpy as np
sys.path.insert(0, '.')
from keys2 import keys, gmin, _ext, cross


def clean(x):
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def k1d(d):  # identical to validation/probe.py: k1d
    T, NL, NH = d['T'][1:], d['NL'][1:], d['NH'][1:]
    o = {}
    o['NLmax'], o['tLmax'] = _ext(T, NL, 100, 5000, +1)
    o['NHmax'], o['tHmax'] = _ext(T, NH, 100, 1e9, +1)
    o['thalf'] = cross(d['T'], d['MH'], 0.5 * d['MH'][0])
    o['rr1e4'] = float(np.interp(1e4, T, NH) / np.interp(1e4, T, NL)) if T[-1] >= 1e4 else float('nan')
    o['rat0.01'] = float('nan')
    return o


out_fn = sys.argv[1] if len(sys.argv) > 1 else 'runs/run_keys.json'
runs = {}
for fn in sorted(glob.glob('runs/*.npz')):
    tag = os.path.basename(fn)[:-4]
    d = np.load(fn)
    rec = {'args': json.load(open('runs/%s.json' % tag))}
    if 'ND' in d.files:                          # run1.py (single species, accepted code)
        rec['script'] = 'run1.py'
        T, ND = d['T'][1:], d['ND'][1:]
        rec['t_end'] = float(d['T'][-1]); rec['nsteps'] = int(d['T'].size - 1)
        rec['M0'] = float(d['MM'][0]); rec['M_end'] = float(d['MM'][-1])
        rec['Ndot_at'] = {('%g' % t): (float(np.interp(t, T, ND)) if T[-1] >= t else None) for t in (100, 1000)}
    else:
        one_d = 'IN' not in d.files
        rec['script'] = 'run1d2.py' if one_d else 'run2.py'
        rec['keys'] = clean(k1d(d) if one_d else keys(fn))
        T, NL, NH = d['T'][1:], d['NL'][1:], d['NH'][1:]
        rec['gmin'] = gmin(T, NL)
        rec['t_end'] = float(d['T'][-1]); rec['nsteps'] = int(d['T'].size - 1)
        rec['M0'] = [float(d['ML'][0]), float(d['MH'][0])]; rec['M_end'] = [float(d['ML'][-1]), float(d['MH'][-1])]
        rec['NdotL_at'] = {('%g' % t): (float(np.interp(t, T, NL)) if T[-1] >= t else None) for t in (100, 1000, 5000, 10000)}
        rec['NdotH_at'] = {('%g' % t): (float(np.interp(t, T, NH)) if T[-1] >= t else None) for t in (100, 1000, 5000, 10000)}
    lg = 'logs/%s.log' % tag
    if os.path.exists(lg):
        done = [ln.strip() for ln in open(lg) if ln.startswith('done')]
        rec['log_done'] = done[-1] if done else None
    runs[tag] = clean(rec)

note = ("Per-run numbers extracted from runs/<tag>.npz (run histories, not shipped) by validation/extract_run_keys.py. "
        "keys = keys2.keys(history) for 2-D runs: NLmax, tLmax = maximum of Ndot_L over 100 <= t <= 5000 (quartic fit "
        "within +-15 % of the discrete maximum); NHmax, tHmax = maximum of Ndot_H over t >= 100; thalf = first time "
        "M_H = M_H(0+)/2 (cubic interpolation); rat0.003 / rat0.01 (and their times) = maximum of N_H(<r)/N_L(<r); rr1e4 "
        "= Ndot_H/Ndot_L at t = 1e4 (only for runs reaching 1e4); gmin = min over 300 <= t <= 1e4 of dNdot_L/dt. "
        "Ndot in objects per unit time. For the 1-D runs (run1d2.py) the keys are validation/probe.py k1d(). "
        "args = the driver's argument set (runs/<tag>.json). M0 / M_end = [M_L, M_H] after the t = 0 removal / at the "
        "end. log_done = last 'done' line of logs/<tag>.log. validation/recompute_from_keys.py rebuilds results.json "
        "and results_details.json from this file; validation/traps.py rebuilds the trap and F_H_star-per-grid tables.")
json.dump({'_note': note, 'runs': runs}, open(out_fn, 'w'), indent=1)
print('wrote', out_fn, 'with', len(runs), 'runs:', ' '.join(runs))
