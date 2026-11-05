"""Energy-exchange check of the species coupling.
For isotropic DFs the local two-body coefficients conserve kinetic energy summed over species, so the
orbit-averaged relaxation energy rates must satisfy dE_L/dt + dE_H/dt = 0 (fixed potential, no loss).
We take the segregated state of a production run (t = end), isotropise it, and evaluate
Edot_i = sum_cells E_c (L_i f_i) + (loss-cone outflow x E_c) for each species (loss term added back).
Also shown: the same with the WRONG friction (flux-form drift proportional to (m_i + m_j)/2 instead of m_i).
usage: python validation/energy_check.py [run.npz] [NE] [NR] [final|init] [zero]
  final / init: isotropise the state at the end of the run or the unsegregated initial state;
  zero = 0 or 1 (optional, added at packaging): set species L (0) or H (1) to zero, so that the printed sum is the
  discretisation residual of the other species' self-relaxation alone (the single-species part of the code)."""
import sys, numpy as np
sys.path.insert(0, '..'); sys.path.insert(0, '.')
from fp2 import TwoSp
import lc2, lcfp
from lcfp import PI

fn = sys.argv[1] if len(sys.argv) > 1 else 'runs/L_120.npz'
NE, NR = int(sys.argv[2]) if len(sys.argv) > 2 else 120, int(sys.argv[3]) if len(sys.argv) > 3 else 48
d = np.load(fn)
m = TwoSp(NE=NE, NR=NR)
m.init()
state = sys.argv[4] if len(sys.argv) > 4 else 'final'
fs = [d['fL'], d['fH']] if state == 'final' else [s.f.copy() for s in m.S]
if len(sys.argv) > 5:
    fs[int(sys.argv[5])] = 0 * fs[int(sys.argv[5])]
for s, f in zip(m.S, fs):
    s.f = s.fbar(f)[:, None] * np.ones((1, s.NR))   # isotropised copy of the chosen state


def rates(m):
    fs = [s.f for s in m.S]
    res = m.coeffs(fs)
    E = []
    for s, r in zip(m.S, res):
        L = s.assemble(r)
        Ldot = (L @ s.f.ravel()).reshape(s.NE, s.NR)
        Ldot[:, 0] += s.clc * s.f[:, 0]           # add back the loss-cone outflow
        E.append(float(np.sum(Ldot * s.Ec[:, None])))
    return E


EL, EH = rates(m)
print('isotropised %s state (%s): Edot_L = %.6e  Edot_H = %.6e  sum = %.3e  (rel %.2e)' % (state, fn, EL, EH, EL + EH, abs(EL + EH) / max(abs(EH), 1e-300)))
# wrong coupling: heavy friction with factor m_L instead of m_H (equal-mass formula applied to heavies)
mH = m.m[1]
orig = m.coeffs
def coeffs_wrong(fs):
    res = orig(fs)
    r = res[1]
    for k in ('x', 'w'):
        r[k][:, 0] *= 0.5 * (1 + m.m[0] / mH)   # drift ~ (m_H + m_L)/2 instead of m_H
        r[k][:, 1] *= 0.5 * (1 + m.m[0] / mH)
    return res
m.coeffs = coeffs_wrong
EL2, EH2 = rates(m)
print('wrong heavy friction ((m_H+m_L)/2):       Edot_L = %.6e  Edot_H = %.6e  sum = %.3e  (rel %.2e)' % (EL2, EH2, EL2 + EH2, abs(EL2 + EH2) / max(abs(EH2), 1e-300)))
