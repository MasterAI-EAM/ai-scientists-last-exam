"""fp2.py -- two-species (light stars L, heavy objects H) 2-D (E, R) orbit-averaged FP with a
Cohn-Kulsrud loss cone per species (own capture radius), coupled through the field coefficients.
Each species lives on its own (x = ln r_c, w) grid (fpsolve.LCFP geometry, unchanged); the field
tables of species s are evaluated at s's energy levels from BOTH species' isotropised mass DFs.
Time stepping: variable-step BDF2 (or backward Euler) with coefficients from the extrapolated state;
within a step the species decouple (linear solves per species)."""
import math
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu
import lcfp, lc2
from fpsolve import LCFP, SQ
from lcfp import PI


class TwoSp:
    def __init__(self, mL=1e-5, mH=1e-4, FH=0.02, rtL=3e-5, rtH=1e-5, lnL=10.0, NE=120, NR=48,
                 RcutL=0.1, RcutH=0.1, bc='ck', coupling=True, variant='ok', **kw):
        self.m = [mL, mH]
        self.FH = FH
        self.lnL = lnL
        self.coupling = coupling
        self.variant = variant   # 'ok' | 'testH' (heavies absent from the field) | 'halfsum' (drift ~ (m_i+m_j)/2): TRAPS
        self.S = [LCFP(rt=rtL, N=1.0 / mL, lnL=lnL, NE=NE, NR=NR, Rcut=RcutL, bc=bc, **kw),
                  LCFP(rt=rtH, N=1.0 / mH, lnL=lnL, NE=NE, NR=NR, Rcut=RcutH, bc=bc, **kw)]
        s0 = self.S[0]
        self.lam0, self.dlam, self.nlam = s0.lam0, s0.dlam, s0.nlam
        self.t = 0.0

    def init(self, beta=0.0):
        fr = [1.0 - self.FH, self.FH]
        for k, s in enumerate(self.S):
            s.init_adiabatic()
            if beta > 0:
                s.f = s.f * (1 - beta) * s.Rcen ** (-beta)
            s.f = s.f * fr[k]
            s.fprev = None
        self.t = 0.0

    def masses(self):
        return [s.mass() for s in self.S]

    # ---------------------------------------------------------------- coefficients
    def coeffs(self, fs):
        fbs = [SQ(s.fbar(np.maximum(f, 0.0))) for s, f in zip(self.S, fs)]
        GamD = 16 * PI ** 2 * self.lnL
        out = []
        for i, s in enumerate(self.S):
            nl = s.Elev.shape[0]
            jtA = np.zeros((nl, self.nlam, 2)); jtD = np.zeros((nl, self.nlam, 2)); I0D = np.zeros(nl)
            for j, sj in enumerate(self.S):
                if not self.coupling and j != i:
                    continue
                if self.variant == 'testH' and j == 1:
                    continue
                jt = np.zeros((nl, self.nlam, 2)); I0 = np.zeros(nl)
                lcfp.field_tables(s.Elev, SQ(sj.Ef), fbs[j], self.lam0, self.dlam, self.nlam, jt, I0)
                jtA += jt * (0.5 * (self.m[i] + self.m[j]) / self.m[i] if self.variant == 'halfsum' else 1.0)
                jtD += self.m[j] * jt
                I0D += self.m[j] * I0
            GamA = 16 * PI ** 2 * self.lnL * self.m[i]
            res = {}
            for name, o in (('x', s.ox), ('w', s.ow)):
                o2 = np.zeros((o['E'].shape[0], 6))
                lc2.orbit_coeffs2(o['lev'], o['R'], o['rr'], o['WW'], o['vv'], o['vr2'], o['Jc2'], o['kap'],
                                  jtA, jtD, I0D, self.lam0, self.dlam, GamA, GamD, o2)
                res[name] = o2
            o = s.orad
            o2 = np.zeros((s.NE, 2))
            lcfp.radial_mu(o['lev'], s.Elev, o['rr'], o['WW'], o['vv'], o['Jc2'], jtD, I0D, self.lam0, self.dlam,
                           GamD, o2)
            res['mu'] = o2[:, 0]
            res['q'] = o2[:, 0] * o2[:, 1] / s.Rlc_c
            res['fb'] = fbs[i]
            out.append(res)
        return out

    # ---------------------------------------------------------------- time step
    def step(self, dt, order=2):
        S = self.S
        ext = order == 2 and S[0].fprev is not None
        if ext:
            om = dt / S[0].dtprev
            fe = [s.f + om * (s.f - s.fprev) for s in S]
            a0 = (1 + 2 * om) / (1 + om); a1 = -(1 + om); a2 = om * om / (1 + om)
        else:
            fe = [s.f for s in S]
            a0, a1, a2 = 1.0, -1.0, 0.0
        resl = self.coeffs(fe)
        self.Mdot = []
        for s, res in zip(S, resl):
            L = s.assemble(res)
            V = s.V.ravel()
            M = sp.diags(a0 * V / dt, format='csc') - L
            rhs = -(a1 * V * s.f.ravel() + (a2 * V * s.fprev.ravel() if ext else 0.0)) / dt
            fn = splu(M).solve(rhs)
            s.nneg = int(np.sum(fn < 0))
            s.fprev = s.f.copy(); s.dtprev = dt
            s.f = fn.reshape(s.NE, s.NR)
            s.Mdot = float(np.sum(s.clc * s.f[:, 0]))
            s.Fq = s.clc * s.f[:, 0]
            s.q = res['q']; s.res = res
            self.Mdot.append(s.Mdot)
        self.t += dt
        for s in S:
            s.t = self.t
        return self.Mdot

    # ---------------------------------------------------------------- diagnostics
    def mass_inside(self, r0, nq=160):
        """mass of each species inside radius r0 (cell-centre orbits, time-fraction weights)."""
        out = []
        for s in self.S:
            key = ('frac', r0, nq)
            if not hasattr(s, '_fr'):
                s._fr = {}
            if key not in s._fr:
                E = np.repeat(s.Ec, s.NR); R = s.Rcen.ravel()
                fr = np.zeros(E.shape[0])
                lc2.frac_inside(SQ(E), SQ(R), r0, s.mu, 1.0, nq, fr)
                s._fr[key] = fr.reshape(s.NE, s.NR)
            out.append(float(np.sum(s.V * s.f * s._fr[key])))
        return out
