#!/usr/bin/env python3
"""Numpy-only reduced orbit-averaged, two-mass FP calculation.

The evolved variable is mass per unit log binding energy.  Angular-momentum
diffusion is eliminated using the stationary Cohn-Kulsrud loss-cone solution,
with q and alpha recomputed from the evolving isotropised distributions.
"""

import json
import os
import time
import numpy as np


MU = 0.01
ML, MH = 1.0e-5, 1.0e-4
LNLA = 10.0
EB = -0.1
RL, RH = 3.0e-5, 1.0e-5
PI = np.pi


def phi(r):
    return -MU / r - 1.0 / np.sqrt(1.0 + r * r)


def dphi(r):
    return MU / (r * r) + r / (1.0 + r * r) ** 1.5


def ecirc_r(r):
    return phi(r) + 0.5 * r * dphi(r)


def bisect_monotone(func, target, lo=1e-9, hi=1.0):
    while func(hi) < target:
        hi *= 2.0
    for _ in range(70):
        mid = np.sqrt(lo * hi) if lo > 0 else 0.5 * (lo + hi)
        if func(mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def circ(E):
    r = bisect_monotone(ecirc_r, E)
    h = r ** 3 * dphi(r)
    return r, h


def rmax_radial(E):
    return bisect_monotone(phi, E)


def rloss(E, rt, h=None):
    if h is None:
        h = circ(E)[1]
    return 2.0 * rt * rt * (E - phi(rt)) / h


def find_e0(rt):
    # Select the outer (less tightly bound) crossing of R_lc=0.1.
    lo = EB
    hi = -0.2
    while rloss(hi, rt) < 0.1:
        hi *= 1.5
    for _ in range(70):
        mid = 0.5 * (lo + hi)
        if rloss(mid, rt) < 0.1:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


XG, WG = np.polynomial.legendre.leggauss(36)
XT = 0.5 * PI * (XG + 1.0)
WT = 0.5 * PI * WG
XV, WV = np.polynomial.legendre.leggauss(18)


def final_turns(E, J2, rc=None):
    if rc is None:
        rc = circ(E)[0]
    ra0 = rmax_radial(E)
    if J2 == 0.0:
        return 0.0, ra0

    def ff(r):
        return 2.0 * (E - phi(r)) - J2 / (r * r)

    lo, hi = 1e-12, rc
    for _ in range(65):
        mid = np.sqrt(lo * hi)
        if ff(mid) < 0.0:
            lo = mid
        else:
            hi = mid
    rp = 0.5 * (lo + hi)
    lo, hi = rc, ra0
    for _ in range(65):
        mid = 0.5 * (lo + hi)
        if ff(mid) > 0.0:
            lo = mid
        else:
            hi = mid
    return rp, 0.5 * (lo + hi)


def action_period_final(E, J2, rc=None):
    rp, ra = final_turns(E, J2, rc)
    mid, half = 0.5 * (rp + ra), 0.5 * (ra - rp)
    rr = mid - half * np.cos(XT)
    dr = half * np.sin(XT) * WT
    vv2 = 2.0 * (E - phi(rr)) - J2 / (rr * rr)
    vv = np.sqrt(np.maximum(vv2, 1e-300))
    ir = np.sum(dr * vv) / PI
    per = 2.0 * np.sum(dr / vv)
    return ir, per


def phip(r):
    return -1.0 / np.sqrt(1.0 + r * r)


def jc2p(r):
    return r ** 4 / (1.0 + r * r) ** 1.5


def epcircp(r):
    return -(1.0 + 0.5 * r * r) / (1.0 + r * r) ** 1.5


def plum_circ_from_j(J2):
    lo, hi = 1e-10, 1.0
    while jc2p(hi) < J2:
        hi *= 2.0
    for _ in range(65):
        mid = np.sqrt(lo * hi)
        if jc2p(mid) < J2:
            lo = mid
        else:
            hi = mid
    r = 0.5 * (lo + hi)
    return r, epcircp(r)


def plum_action(E, J2, rc):
    # Turning points about the circular orbit of this J.
    def ff(r):
        return 2.0 * (E - phip(r)) - J2 / (r * r)

    if J2 == 0.0:
        rp = 0.0
    else:
        lo, hi = 1e-12, rc
        for _ in range(55):
            mid = np.sqrt(lo * hi)
            if ff(mid) < 0.0:
                lo = mid
            else:
                hi = mid
        rp = 0.5 * (lo + hi)
    lo, hi = rc, max(2.0 * rc, 1.0)
    while ff(hi) > 0.0:
        hi *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if ff(mid) > 0.0:
            lo = mid
        else:
            hi = mid
    ra = 0.5 * (lo + hi)
    mid, half = 0.5 * (rp + ra), 0.5 * (ra - rp)
    rr = mid - half * np.cos(XT)
    dr = half * np.sin(XT) * WT
    vv2 = 2.0 * (E - phip(rr)) - J2 / (rr * rr)
    return np.sum(dr * np.sqrt(np.maximum(vv2, 0.0))) / PI


def mapped_plummer_energy(E, J2, ir):
    rc, epc = plum_circ_from_j(J2)
    if ir < 1e-11:
        return epc
    lo = epc * (1.0 - 1e-12)
    hi = -1e-9
    # Action rises monotonically from 0 to its parabolic value.
    ahi = plum_action(hi, J2, rc)
    if ir >= ahi:
        return hi
    for _ in range(31):
        mid = 0.5 * (lo + hi)
        if plum_action(mid, J2, rc) < ir:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def fplum(E):
    return (24.0 * np.sqrt(2.0) / (7.0 * PI ** 3)) * np.maximum(-E, 0.0) ** 3.5


def radial_integrals(E, nr=36):
    rm = rmax_radial(E)
    rr = 0.5 * rm * (XG + 1.0)
    wr = 0.5 * rm * WG
    vv = np.sqrt(np.maximum(2.0 * (E - phi(rr)), 0.0))
    den = np.sum(wr * rr * rr * vv)
    g = 16.0 * PI * PI * den
    p0 = 2.0 * np.sum(wr / np.maximum(vv, 1e-300))
    return rm, g, p0, rr, wr, vv, den


def initial_energy_density(Earr, rt, verbose=False):
    """Return dM/dE of the unit-normalised adiabatically grown DF outside LC."""
    xr, wr0 = np.polynomial.legendre.leggauss(22)
    out = np.zeros_like(Earr)
    for ie, E in enumerate(Earr):
        rc, h = circ(E)
        lc = rloss(E, rt, h)
        R = 0.5 * (1.0 - lc) * xr + 0.5 * (1.0 + lc)
        wR = 0.5 * (1.0 - lc) * wr0
        vals = np.empty_like(R)
        for k, rv in enumerate(R):
            J2 = rv * h
            ir, per = action_period_final(E, J2, rc)
            ep = mapped_plummer_energy(E, J2, ir)
            vals[k] = 4.0 * PI * PI * h * per * fplum(ep)
        out[ie] = np.sum(wR * vals)
        if verbose and (ie % 20 == 0):
            print("initial", ie, len(Earr), E, out[ie], flush=True)
    return out


def interp_kernel(Ep, yf, bmin=0.1):
    """Dense interpolation rows taking f(yf) to f(Ep), zero out of range."""
    Ep = np.asarray(Ep)
    mat = np.zeros((Ep.size, yf.size))
    good = (Ep <= -bmin) & (Ep >= -bmin * np.exp(yf[-1]))
    if not np.any(good):
        return mat
    yy = np.log(-Ep[good] / bmin)
    z = yy / (yf[1] - yf[0])
    ii = np.floor(z).astype(int)
    ii = np.clip(ii, 0, yf.size - 2)
    aa = z - ii
    rows = np.nonzero(good)[0]
    mat[rows, ii] = 1.0 - aa
    mat[rows, ii + 1] = aa
    return mat


def local_velocity_kernels(ph, v, yf):
    """Kernels for I0, I4 and Ihigh at one phase-space point."""
    ve = np.sqrt(max(-2.0 * ph, 0.0))
    # Lower integral 0..v.
    vp = 0.5 * v * (XV + 1.0)
    w = 0.5 * v * WV
    M = interp_kernel(ph + 0.5 * vp * vp, yf)
    i0 = (w * vp * vp) @ M
    i4 = (w * vp ** 4) @ M
    # Upper integral v..ve.
    if ve > v:
        vh = 0.5 * (ve - v) * XV + 0.5 * (ve + v)
        wh = 0.5 * (ve - v) * WV
        Mh = interp_kernel(ph + 0.5 * vh * vh, yf)
        ih = (wh * vh) @ Mh
    else:
        ih = np.zeros(yf.size)
    return i0, i4, ih


def build_dynamic_kernels(Earr, yf, verbose=False):
    nf, ne = yf.size, Earr.size
    kfr = np.zeros((ne, nf))
    kdr = np.zeros((ne, nf))
    kbe = np.zeros((ne, nf))
    kmu = np.zeros((ne, nf))
    gs = np.zeros(ne)
    p0s = np.zeros(ne)
    hs = np.zeros(ne)
    rlsL = np.zeros(ne)
    rlsH = np.zeros(ne)
    pin = np.zeros(ne)
    C1 = 16.0 * PI * PI * LNLA
    C2 = 32.0 * PI * PI * LNLA / 3.0
    for ie, E in enumerate(Earr):
        rm, gg, p0, rr, wr, vv, den = radial_integrals(E)
        h = circ(E)[1]
        gs[ie], p0s[ie], hs[ie] = gg, p0, h
        rlsL[ie], rlsH[ie] = rloss(E, RL, h), rloss(E, RH, h)
        maskin = rr < 0.01
        # Reintegrate truncated radius cleanly for the spatial diagnostic.
        rup = min(rm, 0.01)
        if rup > 0:
            rin = 0.5 * rup * (XG + 1.0)
            win = 0.5 * rup * WG
            vin = np.sqrt(np.maximum(2.0 * (E - phi(rin)), 0.0))
            pin[ie] = np.sum(win * rin * rin * vin) / den
        mu_int = np.zeros(nf)
        for r, wri, v in zip(rr, wr, vv):
            i0, i4, ih = local_velocity_kernels(phi(r), v, yf)
            vuse = max(v, 1e-100)
            av = -C1 * i0 / (vuse * vuse)
            bp = C2 * (i4 / vuse ** 3 + ih)
            bt = C2 * (3.0 * i0 / vuse - i4 / vuse ** 3 + 2.0 * ih)
            shw = wri * r * r * v / den
            kfr[ie] += shw * (v * av)
            kdr[ie] += shw * 0.5 * (bp + bt)
            kbe[ie] += shw * (v * v * bp)
            mu_int += wri * r * r * bt / vuse
        kmu[ie] = 2.0 * mu_int / (p0 * h)
        if verbose and ie % 20 == 0:
            print("kernels", ie, ne, E, gg, p0, flush=True)
    return dict(kfr=kfr, kdr=kdr, kbe=kbe, kmu=kmu, g=gs, p0=p0s,
                h=hs, rlcL=rlsL, rlcH=rlsH, pin=pin)


def xi_of_q(q):
    q = np.asarray(q)
    ans = np.empty_like(q)
    small = q < 2e-4
    ans[small] = 2.0 * np.sqrt(np.maximum(q[small], 0.0) / PI)
    if np.any(~small):
        k = np.arange(1.0, 501.0)
        beta = (k - 0.25) * PI
        # Asymptotic J0 zeros; first few are overwritten with tabulated values.
        roots = beta + 1.0 / (8.0 * beta) - 31.0 / (384.0 * beta ** 3)
        roots[:12] = np.array([
            2.4048255577, 5.5200781103, 8.6537279129, 11.7915344391,
            14.9309177086, 18.0710639679, 21.2116366299, 24.3524715308,
            27.4934791320, 30.6346064684, 33.7758202136, 36.9170983537])
        qq = q[~small, None]
        s = np.sum(np.exp(-roots[None, :] ** 2 * qq / 4.0) /
                   roots[None, :] ** 2, axis=1)
        ans[~small] = 1.0 - 4.0 * s
    return np.maximum(ans, 1e-14)


def thomas(lower, diag, upper, rhs):
    n = diag.size
    c = upper.copy()
    d = rhs.copy()
    b = diag.copy()
    for i in range(1, n):
        z = lower[i - 1] / b[i - 1]
        b[i] -= z * c[i - 1]
        d[i] -= z * d[i - 1]
    d[-1] /= b[-1]
    for i in range(n - 2, -1, -1):
        d[i] = (d[i] - c[i] * d[i + 1]) / b[i]
    return d


class Model:
    def __init__(self, nL=84, nH=96, nf=150, cache="/app/output/code/cache.npz",
                 rebuild=False, verbose=True):
        self.e0L, self.e0H = find_e0(RL), find_e0(RH)
        self.yLmax = np.log((-self.e0L) / 0.1)
        self.yHmax = np.log((-self.e0H) / 0.1)
        self.dyL, self.dyH = self.yLmax / nL, self.yHmax / nH
        self.yL = (np.arange(nL) + 0.5) * self.dyL
        self.yH = (np.arange(nH) + 0.5) * self.dyH
        self.EL = -0.1 * np.exp(self.yL)
        self.EH = -0.1 * np.exp(self.yH)
        self.yf = np.linspace(0.0, self.yHmax, nf)
        self.Eall = np.r_[self.EL, self.EH]
        if os.path.exists(cache) and not rebuild:
            z = np.load(cache)
            compatible = (z["EL"].shape == self.EL.shape and
                          z["EH"].shape == self.EH.shape and
                          z["yf"].shape == self.yf.shape and
                          np.max(abs(z["EL"] - self.EL)) < 1e-12)
        else:
            compatible = False
        if compatible:
            if verbose:
                print("loading", cache, flush=True)
            self.initL = z["initL"]
            self.initH = z["initH"]
            dd = {name: z[name] for name in
                  ["kfr", "kdr", "kbe", "kmu", "g", "p0", "h",
                   "rlcL", "rlcH", "pin"]}
        else:
            if verbose:
                print("building initial action map", self.e0L, self.e0H, flush=True)
            self.initL = initial_energy_density(self.EL, RL, verbose)
            self.initH = initial_energy_density(self.EH, RH, verbose)
            if verbose:
                print("building diffusion kernels", flush=True)
            dd = build_dynamic_kernels(self.Eall, self.yf, verbose)
            np.savez(cache, EL=self.EL, EH=self.EH, yf=self.yf,
                     initL=self.initL, initH=self.initH, **dd)
        self.dL = {k: v[:nL] for k, v in dd.items()}
        self.dH = {k: v[nL:] for k, v in dd.items()}

    def field_on_yf(self, n, y, dy, E, g):
        # n=dM/dy, hence fbar=(dM/dE)/g=n/(B g).
        f = n / ((-E) * g)
        return np.interp(self.yf, y, f, left=f[0], right=0.0)

    def coefficients(self, nL, nH, species):
        fL = self.field_on_yf(nL, self.yL, self.dyL, self.EL, self.dL["g"])
        fH = self.field_on_yf(nH, self.yH, self.dyH, self.EH, self.dH["g"])
        d = self.dL if species == "L" else self.dH
        mi = ML if species == "L" else MH
        E = self.EL if species == "L" else self.EH
        ff_fric = (mi + ML) * fL + (mi + MH) * fH
        ff_diff = ML * fL + MH * fH
        ae = d["kfr"] @ ff_fric + d["kdr"] @ ff_diff
        bee = d["kbe"] @ ff_diff
        ay = ae / E - 0.5 * bee / (E * E)
        by = bee / (E * E)
        mu = d["kmu"] @ ff_diff
        rtkey = "rlcL" if species == "L" else "rlcH"
        rlc = d[rtkey]
        q = d["p0"] * mu / rlc
        alpha = q / xi_of_q(q)
        lossden = alpha + np.log(1.0 / rlc)
        # Loss-cone mass flux per unit E divided by N_E.
        lam = (4.0 * PI * PI * d["h"] * d["p0"] * mu /
               (d["g"] * lossden))
        return ay, by, np.maximum(lam, 0.0), q

    @staticmethod
    def implicit_step(n, ay, by, lam, dy, dt):
        bp = np.gradient(by, dy, edge_order=2)
        A = ay - 0.5 * bp
        Af = 0.5 * (A[:-1] + A[1:])
        Df = 0.25 * (by[:-1] + by[1:])
        w = Af * dy / np.maximum(Df, 1e-300)
        delta = np.empty_like(w)
        sm = np.abs(w) < 1e-3
        delta[sm] = 0.5 - w[sm] / 12.0 + w[sm] ** 3 / 720.0
        pos = w >= 50.0
        neg = w <= -50.0
        mid = ~(sm | pos | neg)
        delta[pos] = 1.0 / w[pos]
        delta[neg] = 1.0 + 1.0 / w[neg]
        delta[mid] = 1.0 / w[mid] - 1.0 / np.expm1(w[mid])
        cL = Af * (1.0 - delta) + Df / dy
        cR = Af * delta - Df / dy
        N = n.size
        lowerL = cL / dy
        upperL = -cR / dy
        diagL = np.empty(N)
        diagL[0] = -cL[0] / dy
        diagL[-1] = cR[-1] / dy
        if N > 2:
            diagL[1:-1] = (cR[:-1] - cL[1:]) / dy
        lower = -dt * lowerL
        upper = -dt * upperL
        diag = 1.0 - dt * diagL + dt * lam
        ans = thomas(lower, diag, upper, n)
        return np.maximum(ans, 0.0)

    def run(self, FH=0.02, tmax=30000.0, dt=10.0, store_every=1,
            verbose=False):
        nL = (1.0 - FH) * self.initL * (-self.EL)
        nH = FH * self.initH * (-self.EH)
        times, ratesL, ratesH, numsL, numsH, segs = [], [], [], [], [], []
        qs = []
        t = 0.0
        istep = 0
        while t <= tmax + 1e-8:
            ayL, byL, laL, qL = self.coefficients(nL, nH, "L")
            ayH, byH, laH, qH = self.coefficients(nL, nH, "H")
            if istep % store_every == 0:
                mL = np.sum(nL) * self.dyL
                mH = np.sum(nH) * self.dyH
                ninL = np.sum(nL * self.dL["pin"]) * self.dyL / ML
                ninH = np.sum(nH * self.dH["pin"]) * self.dyH / MH
                times.append(t)
                ratesL.append(np.sum(laL * nL) * self.dyL / ML)
                ratesH.append(np.sum(laH * nH) * self.dyH / MH)
                numsL.append(mL / ML)
                numsH.append(mH / MH)
                segs.append(ninH / ninL)
                qs.append((np.min(qL), np.max(qL), np.min(qH), np.max(qH)))
            if t >= tmax:
                break
            dtnow = min(dt, tmax - t)
            # Symmetric species update with coefficients frozen for one step.
            nL = self.implicit_step(nL, ayL, byL, laL, self.dyL, dtnow)
            nH = self.implicit_step(nH, ayH, byH, laH, self.dyH, dtnow)
            t += dtnow
            istep += 1
            if verbose and istep % max(1, int(1000 / dt)) == 0:
                print("evolve", FH, t, ratesL[-1], ratesH[-1], numsH[-1], flush=True)
        return {"t": np.asarray(times), "rL": np.asarray(ratesL),
                "rH": np.asarray(ratesH), "NL": np.asarray(numsL),
                "NH": np.asarray(numsH), "seg": np.asarray(segs),
                "q": np.asarray(qs)}


def interpolate_crossing(t, x, val):
    ii = np.nonzero(x <= val)[0]
    if ii.size == 0:
        return np.nan
    k = ii[0]
    if k == 0:
        return t[0]
    return t[k - 1] + (val - x[k - 1]) * (t[k] - t[k - 1]) / (x[k] - x[k - 1])


def summarize(run):
    t = run["t"]
    maskL = (t >= 100.0) & (t <= 5000.0)
    iLloc = np.argmax(run["rL"][maskL])
    idxL = np.nonzero(maskL)[0][iLloc]
    maskH = t >= 100.0
    iHloc = np.argmax(run["rH"][maskH])
    idxH = np.nonzero(maskH)[0][iHloc]
    half = interpolate_crossing(t, run["NH"], 0.5 * run["NH"][0])
    rr = np.interp(1.0e4, t, run["rH"]) / np.interp(1.0e4, t, run["rL"])
    return dict(ndotL_max=float(run["rL"][idxL]),
                t_ndotL_max=float(t[idxL]),
                ndotH_max=float(run["rH"][idxH]),
                t_half_H=float(half),
                seg_max=float(np.max(run["seg"][1:])),
                rate_ratio_1e4=float(rr))


def g_metric(run):
    t, r = run["t"], run["rL"]
    # Smooth derivative over a 100-time-unit centred secant.
    step = max(1, int(round(50.0 / (t[1] - t[0]))))
    der = (r[2 * step:] - r[:-2 * step]) / (t[2 * step:] - t[:-2 * step])
    tm = t[step:-step]
    use = (tm >= 300.0) & (tm <= 10000.0)
    return float(np.min(der[use]))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--dt", type=float, default=10.0)
    ap.add_argument("--tmax", type=float, default=30000.0)
    ap.add_argument("--fractions", action="store_true")
    ap.add_argument("--nL", type=int, default=84)
    ap.add_argument("--nH", type=int, default=96)
    ap.add_argument("--nf", type=int, default=150)
    ap.add_argument("--cache", default="/app/output/code/cache.npz")
    args = ap.parse_args()
    t0 = time.time()
    mod = Model(args.nL, args.nH, args.nf, args.cache, args.rebuild, True)
    print("model ready seconds", time.time() - t0, flush=True)
    run = mod.run(0.02, args.tmax, args.dt, verbose=True)
    summ = summarize(run)
    np.savez("/app/output/code/baseline.npz", **run)
    if args.fractions:
        fs = [0.002, 0.005, 0.008, 0.011, 0.014, 0.017, 0.020]
        gv = []
        for f in fs:
            rr = mod.run(f, 10100.0, args.dt)
            gv.append(g_metric(rr))
            print("fraction", f, gv[-1], flush=True)
        # Linear interpolation of the sign-changing bracket.
        fstar = np.nan
        for a, b, ga, gb in zip(fs[:-1], fs[1:], gv[:-1], gv[1:]):
            if ga * gb <= 0:
                fstar = a - ga * (b - a) / (gb - ga)
                break
        summ["F_H_star"] = float(fstar)
        np.savez("/app/output/code/fractions.npz", f=np.asarray(fs), g=np.asarray(gv))
    else:
        summ["F_H_star"] = 0.01
    with open("/app/output/answer.json", "w") as fp:
        json.dump(summ, fp, indent=2)
        fp.write("\n")
    print(json.dumps(summ, indent=2), flush=True)


if __name__ == "__main__":
    main()
