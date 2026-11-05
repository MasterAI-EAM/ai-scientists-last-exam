"""Rebuild results.json and results_details.json from runs/run_keys.json, without the run histories
(runs/*.npz are not shipped).

It executes solve_reference.py unchanged. Only the two places that read a run history are replaced:
  keys2.keys(fn)                     -> the 'keys' entry of that run in runs/run_keys.json;
  np.load(fn) followed by keys2.gmin -> the 'gmin' entry of that run (solve_reference.g_of computes exactly
                                        keys2.gmin(T[1:], NL[1:]), which validation/extract_run_keys.py stored).
Empty placeholder files runs/<tag>.npz are created in a temporary directory so that the glob / os.path.exists calls
of solve_reference.py see the same run list. The rebuilt files are compared with the shipped ones.

usage: python validation/recompute_from_keys.py        (numpy only)
"""
import contextlib, io, json, os, sys, tempfile, types
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = json.load(open(os.path.join(HERE, 'runs', 'run_keys.json')))['runs']


class _Hist:                      # stands for one run history; slicing keeps the run tag
    def __init__(self, tag):
        self.tag = tag

    def __getitem__(self, k):
        return self


def _load(fn, *a, **kw):
    tag = os.path.basename(fn)[:-4]
    return {'T': _Hist(tag), 'NL': _Hist(tag)}


def keys(fn):
    tag = os.path.basename(fn)[:-4]
    return {k: (float('nan') if v is None else v) for k, v in RUNS[tag]['keys'].items()}


def gmin(T, NL):
    return RUNS[T.tag]['gmin']


sys.modules['keys2'] = types.SimpleNamespace(keys=keys, gmin=gmin)
src = open(os.path.join(HERE, 'solve_reference.py')).read()
cwd = os.getcwd()
same = {}
real_load = np.load
with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    os.mkdir('runs')
    for tag in RUNS:
        open(os.path.join('runs', tag + '.npz'), 'w').close()
    np.load = _load
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(src, 'solve_reference.py', 'exec'), {'__name__': '__main__'})
    finally:
        np.load = real_load
    for fn in ('results.json', 'results_details.json'):
        same[fn] = open(fn, 'rb').read() == open(os.path.join(HERE, fn), 'rb').read()
    new = json.load(open('results.json'))
    os.chdir(cwd)
ref = json.load(open(os.path.join(HERE, 'results.json')))
for k in ['ndotL_max', 't_ndotL_max', 'ndotH_max', 't_half_H', 'seg_max', 'rate_ratio_1e4', 'F_H_star']:
    print('%-15s rebuilt %.10g  shipped %.10g  unc %.3g' % (k, new[k], ref[k], new['_uncertainty'][k]))
print('identical to shipped results.json:', new == ref,
      '(byte for byte: results.json %s, results_details.json %s)' % (same['results.json'], same['results_details.json']))
