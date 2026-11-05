"""fpsolve.py -- driver for the 2-D (E,R) loss-cone FP (see lcfp.py)."""
import math, time, json
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu
import lcfp
from lcfp import PI

SQ = lambda a: np.ascontiguousarray(a, dtype=float)


class LCFP:
    def __init__(self, mu=0.01, rt=3e-5, N=1e5, lnL=10.0, Eb=-0.1, Rcut=0.1, NE=120, NR=48,
                 amap=0.5, pmap=1.0, nth=48, lam0=-18.0, dlam=0.025, lam1=16.0, bc='ck', lcE=True):
        self.mu, self.rt, self.N, self.lnL = mu, rt, N, lnL
        self.Gam = 16 * PI ** 2 * lnL / N
        self.Eb, self.Rcut, self.NE, self.NR, self.nth = Eb, Rcut, NE, NR, nth
        self.bc = bc
        self.lam0, self.dlam = lam0, dlam
        self.nlam = int(round((lam1 - lam0) / dlam)) + 1
        mu_ = mu
        # inner edge: R_lc(E_c(r)) = Rcut
        lo, hi = math.log(rt * 1.0001), math.log(10.0)
        for it in range(200):
            m = 0.5 * (lo + hi)
            if self.Rlc(lcfp.Ec_of_r(math.exp(m), mu_, 1.0)) > Rcut:
                lo = m
            else:
                hi = m
        x_in = 0.5 * (lo + hi)
        x_out = math.log(lcfp.rc_of_E(Eb, mu_, 1.0))
        self.xf = np.linspace(x_in, x_out, NE + 1)
        self.xc = 0.5 * (self.xf[1:] + self.xf[:-1])
        self.Ef = np.array([lcfp.Ec_of_r(math.exp(x), mu_, 1.0) for x in self.xf])
        self.Ef[-1] = Eb
        self.Ec = np.array([lcfp.Ec_of_r(math.exp(x), mu_, 1.0) for x in self.xc])
        self.dE = np.diff(self.Ef)
        # w grid
        s = np.linspace(0, 1, NR + 1)
        sc = 0.5 * (s[1:] + s[:-1])
        W = lambda s: (s - amap * np.sin(2 * PI * s) / (2 * PI)) ** pmap
        self.wf = W(s)
        self.wc = W(sc)
        # energy-dependent quantities
        def eq(E):
            out = np.array([lcfp.circ(e, mu_, 1.0) for e in E])
            rc, Jc2, kap, dEdx = out.T
            Rl = np.array([self.Rlc(e) for e in E])
            ell = np.log(Rl)
            dell = 1.0 / (E - lcfp.phi(rt, mu_, 1.0)) - kap
            return rc, Jc2, kap, Rl, ell, dell
        self.rcf, self.Jc2f, self.kapf, self.Rlf, self.ellf, self.dellf = eq(self.Ef)
        self.rcc, self.Jc2c, self.kapc, self.Rlc_c, self.ellc, self.dellc = eq(self.Ec)
        self.Elev = SQ(np.concatenate([self.Ef, self.Ec]))
        self._orbits()
        self.t = 0.0
        self.Mlost = 0.0

    def Rlc(self, E):
        mu, rt = self.mu, self.rt
        rc, Jc2, kap, dEdx = lcfp.circ(E, mu, 1.0)
        return 2 * rt * rt * (E - lcfp.phi(rt, mu, 1.0)) / Jc2

    def Rmap(self, ell, w):
        return np.exp((1.0 - w) * ell)

    # -------------------------------------------------------------- orbits (fixed potential)
    def _mk(self, E, R, lev):
        n = E.shape[0]
        nth = self.nth
        rr = np.zeros((n, nth)); WW = np.zeros((n, nth)); vv = np.zeros((n, nth)); vr2 = np.zeros((n, nth))
        Jc2 = np.zeros(n); kap = np.zeros(n)
        lcfp.build_orbits(SQ(E), SQ(R), self.mu, 1.0, nth, rr, WW, vv, vr2, Jc2, kap)
        return dict(E=SQ(E), R=SQ(R), lev=np.ascontiguousarray(lev, dtype=np.int64), rr=rr, WW=WW, vv=vv,
                    vr2=vr2, Jc2=Jc2, kap=kap)

    def _orbits(self):
        NE, NR = self.NE, self.NR
        # x faces (interior i=1..NE-1), rows j
        i = np.arange(1, NE)
        Ex = np.repeat(self.Ef[i], NR)
        Rx = self.Rmap(np.repeat(self.ellf[i], NR), np.tile(self.wc, NE - 1))
        self.ox = self._mk(Ex, Rx, np.repeat(i, NR))
        # w faces j=0..NR-1 (j=0 is the loss-cone boundary), columns i
        Ew = np.repeat(self.Ec, NR)
        Rw = self.Rmap(np.repeat(self.ellc, NR), np.tile(self.wf[:NR], NE))
        self.ow = self._mk(Ew, Rw, NE + 1 + np.repeat(np.arange(NE), NR))
        # cell centres
        Rcn = self.Rmap(np.repeat(self.ellc, NR), np.tile(self.wc, NE))
        self.oc = self._mk(Ew, Rcn, NE + 1 + np.repeat(np.arange(NE), NR))
        self.Rcen = Rcn.reshape(NE, NR)
        # radial orbits at cell-centre energies
        self.orad = self._mk(self.Ec, np.zeros(NE), NE + 1 + np.arange(NE))
        # periods / volumes
        Pc = 2 * self.oc['WW'].sum(axis=1).reshape(NE, NR)
        self.Pc = Pc
        self.P0 = 2 * self.orad['WW'].sum(axis=1)
        Rfw = self.Rmap(self.ellc[:, None], self.wf[None, :])  # NE x NR+1
        self.dR = np.diff(Rfw, axis=1)
        self.V = 4 * PI ** 2 * self.Jc2c[:, None] * Pc * self.dE[:, None] * self.dR
        self.Vlc = 4 * PI ** 2 * self.Jc2c * self.P0 * self.Rlc_c * self.dE
        # geometry for x faces
        Rxf = self.Rmap(self.ellf[:, None], self.wf[None, :])   # (NE+1) x (NR+1)
        self.dRx = np.diff(Rxf, axis=1)[1:NE]                   # (NE-1) x NR
        wcg = self.wc[None, :]
        self.wE_x = (1 - wcg) * (self.dellf[1:NE] / self.ellf[1:NE])[:, None]
        self.wR_x = -1.0 / (self.ox['R'].reshape(NE - 1, NR) * self.ellf[1:NE, None])
        # geometry for w faces (j = 0..NR-1)
        wfg = self.wf[None, :NR]
        Rw = self.ow['R'].reshape(NE, NR)
        self.wE_w = (1 - wfg) * (self.dellc / self.ellc)[:, None]
        self.wR_w = -1.0 / (Rw * self.ellc[:, None])
        self.RE_w = Rw * (1 - wfg) * self.dellc[:, None]

    # -------------------------------------------------------------- initial model
    def init_adiabatic(self):
        NE, NR = self.NE, self.NR
        E = np.repeat(self.Ec, NR)
        R = self.Rcen.ravel()
        out = np.zeros(E.shape[0]); EP = np.zeros(E.shape[0])
        lcfp.init_df(SQ(E), SQ(R), self.mu, 2 * self.nth, out, EP)
        self.f = out.reshape(NE, NR)
        self.EP = EP.reshape(NE, NR)
        self.fprev = None
        self.t = 0.0
        self.Mlost = 0.0

    def mass(self, f=None):
        f = self.f if f is None else f
        return float(np.sum(self.V * f))

    def fbar(self, f):
        return np.sum(self.V * f, axis=1) / (np.sum(self.V, axis=1) + self.Vlc)

    # -------------------------------------------------------------- coefficients
    def coeffs(self, f):
        fb = SQ(self.fbar(np.maximum(f, 0.0)))
        nl = self.Elev.shape[0]
        jt = np.zeros((nl, self.nlam, 2)); I0 = np.zeros(nl)
        lcfp.field_tables(self.Elev, SQ(self.Ef), fb, self.lam0, self.dlam, self.nlam, jt, I0)
        res = {}
        for name, o in (('x', self.ox), ('w', self.ow)):
            out = np.zeros((o['E'].shape[0], 6))
            lcfp.orbit_coeffs(o['lev'], self.Elev, o['R'], o['rr'], o['WW'], o['vv'], o['vr2'], o['Jc2'],
                              o['kap'], jt, I0, self.lam0, self.dlam, self.Gam, out)
            res[name] = out
        o = self.orad
        out = np.zeros((self.NE, 2))
        lcfp.radial_mu(o['lev'], self.Elev, o['rr'], o['WW'], o['vv'], o['Jc2'], jt, I0, self.lam0, self.dlam,
                       self.Gam, out)
        res['mu'] = out[:, 0]
        res['q'] = out[:, 0] * out[:, 1] / self.Rlc_c
        res['fb'] = fb
        return res

    def assemble(self, res):
        NE, NR = self.NE, self.NR
        rows, cols, vals = [], [], []

        def add(lo, hi, cc, vv):
            # flux (lo -> hi) = sum vv * f[cc]; dN_lo/dt -= flux, dN_hi/dt += flux
            lo = lo.ravel(); cc = cc.ravel(); vv = vv.ravel()
            rows.append(lo); cols.append(cc); vals.append(-vv)
            if hi is not None:
                rows.append(hi.ravel()); cols.append(cc); vals.append(vv.copy())

        idx = np.arange(NE * NR).reshape(NE, NR)
        # ---------------- x faces
        DE, DR, DEE, DER, DRR, P = [res['x'][:, k].reshape(NE - 1, NR) for k in range(6)]
        h = (self.Ec[1:] - self.Ec[:-1])[:, None]
        dRx = self.dRx
        B = dRx * DE
        C = dRx * DEE / h
        dl = lcfp.cc_delta(B / C)
        X = -dRx * (DEE * self.wE_x + DER * self.wR_x)
        lo = idx[:-1, :]; hi = idx[1:, :]
        add(lo, hi, lo, -B * dl + C)
        add(lo, hi, hi, -B * (1 - dl) - C)
        # cross term: f_w centred, averaged over the two columns
        wc = self.wc
        jp = np.minimum(np.arange(NR) + 1, NR - 1); jm = np.maximum(np.arange(NR) - 1, 0)
        dw = (wc[jp] - wc[jm])[None, :] * np.ones((NE - 1, 1))
        for col in (idx[:-1, :], idx[1:, :]):
            cp = col[:, jp]; cm = col[:, jm]
            add(lo, hi, cp, 0.5 * X / dw)
            add(lo, hi, cm, -0.5 * X / dw)
        # ---------------- w faces j=1..NR-1 (between rows j-1 and j)
        DE, DR, DEE, DER, DRR, P = [res['w'][:, k].reshape(NE, NR) for k in range(6)]
        dEc = self.dE[:, None]
        RE = self.RE_w; wR = self.wR_w; wE = self.wE_w
        Cw = dEc * wR * (DRR - 2 * RE * DER + RE * RE * DEE)
        Bw = dEc * (DR - RE * DE)
        Xw = -dEc * (DER - RE * DEE)
        s = slice(1, NR)
        hw = (wc[1:] - wc[:-1])[None, :]
        Bs, Cs, Xs = Bw[:, s], Cw[:, s] / hw, Xw[:, s]
        dl = lcfp.cc_delta(Bs / Cs)
        lo = idx[:, :-1]; hi = idx[:, 1:]
        add(lo, hi, lo, -Bs * dl + Cs)
        add(lo, hi, hi, -Bs * (1 - dl) - Cs)
        ip = np.minimum(np.arange(NE) + 1, NE - 1); im = np.maximum(np.arange(NE) - 1, 0)
        dEx = (self.Ec[ip] - self.Ec[im])[:, None] * np.ones((1, NR - 1))
        for row in (idx[:, :-1], idx[:, 1:]):
            cp = row[ip, :]; cm = row[im, :]
            add(lo, hi, cp, 0.5 * Xs / dEx)
            add(lo, hi, cm, -0.5 * Xs / dEx)
        # ---------------- loss-cone boundary (w = 0): outflow
        DRRlc = DRR[:, 0] / self.ow['R'].reshape(NE, NR)[:, 0]    # D_RR/R at R_lc
        self.DRRlc = DRRlc
        d0 = -self.wc[0] * self.ellc                               # ln(R_0c / R_lc)
        if self.bc == 'ck':
            al = lcfp.alpha_ck(res['q'])
        elif self.bc == 'empty':
            al = np.zeros(NE)
        else:
            raise ValueError
        self.alpha = al
        clc = self.dE * DRRlc / (d0 + al)
        self.clc = clc
        rows.append(idx[:, 0]); cols.append(idx[:, 0]); vals.append(-clc)
        n = NE * NR
        return sp.csc_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))

    # -------------------------------------------------------------- time step
    def step(self, dt, order=2):
        NE, NR = self.NE, self.NR
        V = self.V.ravel()
        f0 = self.f.ravel()
        if order == 3:   # Crank-Nicolson with one Picard correction of the coefficients
            res0 = self.coeffs(self.f)
            L0 = self.assemble(res0)
            fl = L0 @ f0
            fp = f0.copy()
            for it in range(2):
                res = self.coeffs(np.maximum(fp.reshape(NE, NR), 0) if it else self.f)
                L1 = self.assemble(res) if it else L0
                M = sp.diags(V / dt, format='csc') - 0.5 * L1
                fp = splu(M).solve(V * f0 / dt + 0.5 * fl)
            fn = fp
            self.fprev = self.f.copy(); self.dtprev = dt
            self.f = fn.reshape(NE, NR)
            self.Mdot = float(np.sum(self.clc * self.f[:, 0]))
            self.Fq = self.clc * self.f[:, 0]
            self.q = res['q']; self.t += dt; self.res = res; self.nneg = int(np.sum(fn < 0))
            return self.Mdot
        if order == 2 and self.fprev is not None:
            om = dt / self.dtprev
            fe = self.f + om * (self.f - self.fprev)
            res = self.coeffs(fe)
            L = self.assemble(res)
            a0 = (1 + 2 * om) / (1 + om); a1 = -(1 + om); a2 = om * om / (1 + om)
            M = sp.diags(a0 * V / dt, format='csc') - L
            rhs = -(a1 * V * f0 + a2 * V * self.fprev.ravel()) / dt
        else:
            res = self.coeffs(self.f)
            L = self.assemble(res)
            M = sp.diags(V / dt, format='csc') - L
            rhs = V * f0 / dt
        fn = splu(M).solve(rhs)
        self.nneg = int(np.sum(fn < 0))
        self.fprev = self.f.copy()
        self.dtprev = dt
        self.f = fn.reshape(NE, NR)
        # loss rate (mass/time) at the new level
        self.Mdot = float(np.sum(self.clc * self.f[:, 0]))
        self.Fq = self.clc * self.f[:, 0]
        self.q = res['q']
        self.t += dt
        self.res = res
        return self.Mdot
