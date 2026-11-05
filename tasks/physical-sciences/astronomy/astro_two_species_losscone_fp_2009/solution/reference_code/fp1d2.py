"""fp1d2.py -- TRAP / cross-check only: 1-D isotropic two-species FP in E with the steady-state
Cohn-Kulsrud loss-cone sink per species (PhaseFlow form nu = mubar/(alpha - ln R_lc)), same field
coefficients as the 2-D code (R-integrated), same energy grids."""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu
import lcfp
from fp2 import TwoSp


class FP1D2(TwoSp):
    def init1d(self, beta=0.0):
        self.init(beta)
        self.G = [np.sum(s.V, axis=1) + s.Vlc for s in self.S]
        self.fb = [s.fbar(s.f) for s in self.S]
        self.fbp = None

    def step(self, dt, order=2):
        S = self.S
        if order == 2 and self.fbp is not None:
            om = dt / self.dtprev
            fe = [np.maximum(f + om * (f - fp), 0) for f, fp in zip(self.fb, self.fbp)]
            a0 = (1 + 2 * om) / (1 + om); a1 = -(1 + om); a2 = om * om / (1 + om)
        else:
            fe = self.fb; a0, a1, a2 = 1.0, -1.0, 0.0
        resl = self.coeffs([f[:, None] * np.ones((1, s.NR)) for f, s in zip(fe, S)])
        new = []; self.Mdot = []
        for k, (s, res) in enumerate(zip(S, resl)):
            NE, NR = s.NE, s.NR
            DE = res['x'][:, 0].reshape(NE - 1, NR); DEE = res['x'][:, 2].reshape(NE - 1, NR)
            B = np.sum(DE * s.dRx, axis=1); C = np.sum(DEE * s.dRx, axis=1) / (s.Ec[1:] - s.Ec[:-1])
            dl = lcfp.cc_delta(B / C)
            rows, cols, vals = [], [], []
            lo = np.arange(NE - 1); hi = lo + 1
            for cc, v in ((lo, -B * dl + C), (hi, -B * (1 - dl) - C)):
                rows += [lo, hi]; cols += [cc, cc]; vals += [-v, v]
            al = lcfp.alpha_ck(res['q'])
            nu = res['mu'] / (al - np.log(s.Rlc_c))
            sink = nu * self.G[k]
            idx = np.arange(NE)
            rows.append(idx); cols.append(idx); vals.append(-sink)
            L = sp.csc_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(NE, NE))
            M = sp.diags(a0 * self.G[k] / dt, format='csc') - L
            rhs = -(a1 * self.G[k] * self.fb[k] + (a2 * self.G[k] * self.fbp[k] if a2 else 0)) / dt
            fn = splu(M).solve(rhs)
            new.append(fn)
            self.Mdot.append(float(np.sum(sink * fn)))
        self.fbp = self.fb; self.fb = new; self.dtprev = dt
        self.t += dt
        return self.Mdot

    def masses(self):
        return [float(np.sum(G * f)) for G, f in zip(self.G, self.fb)]
