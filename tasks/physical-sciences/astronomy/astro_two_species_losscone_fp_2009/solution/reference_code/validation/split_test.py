"""Single-species limit of the two-species code (needs the run histories runs/t_ident.npz and runs/t_single.npz).
t_ident: run2.py with m_H = m_L = 1e-5, r_H = r_L = 3e-5, F_H = 0.3 (one population split 70/30 into two labelled
species), NE 60 x NR 24, dt <= 10, t <= 1000.  t_single: run1.py, the accepted single-species code, same grid and steps.
If the coupling is right, Ndot_L/0.7 and Ndot_H/0.3 both equal the single-species Ndot at every step."""
import numpy as np
a, b = np.load('runs/t_ident.npz'), np.load('runs/t_single.npz')
print('steps: t_ident %d, t_single %d, max |dT| = %.1e' % (a['T'].size - 1, b['T'].size - 1, np.max(abs(a['T'] - b['T']))))
NL, NH, ND = a['NL'][1:], a['NH'][1:], b['ND'][1:]
print('max_t |Ndot_L/0.7 / Ndot_single - 1| = %.2e' % np.max(abs(NL / 0.7 / ND - 1)))
print('max_t |Ndot_H/0.3 / Ndot_single - 1| = %.2e' % np.max(abs(NH / 0.3 / ND - 1)))
print('masses at t = 0+: M_L/0.7 = %.15f, M_H/0.3 = %.15f, single = %.15f' % (a['ML'][0] / 0.7, a['MH'][0] / 0.3, b['MM'][0]))
print('Ndot_single(100) = %.6f, Ndot_single(1000) = %.6f' % (np.interp(100, b['T'][1:], ND), ND[-1]))
