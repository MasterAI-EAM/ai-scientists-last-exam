#!/usr/bin/env python3
"""Two-dimensional (energy, angular momentum) numpy FP approximation.

It retains orbit-dependent diffusion and an explicit logarithmic loss-cone
coordinate.  Mixed E-R diffusion is omitted; the diagonal orbit-averaged
terms and the exact Cohn-Kulsrud boundary relation are retained.
"""

import argparse
import json
import os
import time
import numpy as np

from solver import (MU, ML, MH, RL, RH, PI, EB, XG, WG, XT, WT, circ,
                    phi, rmax_radial, rloss, find_e0, final_turns,
                    action_period_final, mapped_plummer_energy, fplum,
                    radial_integrals, local_velocity_kernels, xi_of_q,
                    thomas)


def interp_local(sgrid, arr, s):
    """Linear interpolate (nr,nkernel) data to vector s."""
    ii = np.searchsorted(sgrid, s) - 1
    ii = np.clip(ii, 0, len(sgrid) - 2)
    a = (s - sgrid[ii]) / (sgrid[ii + 1] - sgrid[ii])
    return arr[ii] * (1.0 - a[:, None]) + arr[ii + 1] * a[:, None]


def build_one_energy(E, rt, xgrid, yf, verbose=False):
    nx, nf = len(xgrid), len(yf)
    rc, h = circ(E)
    lc = rloss(E, rt, h)
    L = np.log(1.0 / lc)
    Rv = lc * np.exp(L * xgrid)
    rm, gg, p0, rr0, wr0, vv0, den = radial_integrals(E)

    # Local velocity kernels on a radius grid, shared by all orbits at E.
    nr = 64
    tt = np.linspace(1e-5, 1.0 - 1e-5, nr)
    sg = np.sin(0.5 * PI * tt) ** 2
    rg = rm * sg
    nloc = 5
    loc = np.zeros((nr, nloc, nf))  # av, bp, bt and combinations formed later
    C1 = 16.0 * PI * PI * 10.0
    C2 = 32.0 * PI * PI * 10.0 / 3.0
    for k, r in enumerate(rg):
        v = np.sqrt(max(2.0 * (E - phi(r)), 1e-300))
        i0, i4, ih = local_velocity_kernels(phi(r), v, yf)
        av = -C1 * i0 / (v * v)
        bp = C2 * (i4 / v ** 3 + ih)
        bt = C2 * (3.0 * i0 / v - i4 / v ** 3 + 2.0 * ih)
        loc[k, 0], loc[k, 1], loc[k, 2] = av, bp, bt

    keys = ["aef", "aed", "bee", "auf", "aud", "buu", "beu"]
    out = {k: np.zeros((nx, nf)) for k in keys}
    periods = np.zeros(nx)
    weights = np.zeros(nx)
    pins = np.zeros(nx)
    fis = np.zeros(nx)
    for j, R in enumerate(Rv):
        J2 = R * h
        rp, ra = final_turns(E, J2, rc)
        mid, half = 0.5 * (rp + ra), 0.5 * (ra - rp)
        rr = mid - half * np.cos(XT)
        dr = half * np.sin(XT) * WT
        vr2 = np.maximum(2.0 * (E - phi(rr)) - J2 / (rr * rr), 1e-300)
        vr = np.sqrt(vr2)
        vv2 = np.maximum(2.0 * (E - phi(rr)), 1e-300)
        vv = np.sqrt(vv2)
        ww = dr / vr
        norm = np.sum(ww)
        per = 2.0 * norm
        periods[j] = per
        lv = interp_local(sg, loc.reshape(nr, nloc * nf), rr / rm)
        lv = lv.reshape(len(rr), nloc, nf)
        av, bp, bt = lv[:, 0], lv[:, 1], lv[:, 2]
        w = ww[:, None] / norm
        out["aef"][j] = np.sum(w * (vv[:, None] * av), axis=0)
        out["aed"][j] = np.sum(w * (0.5 * (bp + bt)), axis=0)
        out["bee"][j] = np.sum(w * (vv2[:, None] * bp), axis=0)
        out["auf"][j] = np.sum(w * (2.0 * J2 * av / vv[:, None]), axis=0)
        brr = 0.5 * bt + (bp - 0.5 * bt) * (vr2 / vv2)[:, None]
        out["aud"][j] = np.sum(w * (rr * rr)[:, None] * (bp + bt - brr), axis=0)
        out["buu"][j] = np.sum(w * (2.0 * bt * (rr * rr * J2)[:, None] +
                                      4.0 * (bp - 0.5 * bt) *
                                      (J2 * J2 / vv2)[:, None]), axis=0)
        out["beu"][j] = np.sum(w * (2.0 * J2 * bp), axis=0)
        weights[j] = 4.0 * PI * PI * h * per * L * R
        if rp >= 0.01:
            pins[j] = 0.0
        elif ra <= 0.01:
            pins[j] = 1.0
        else:
            # Integrate the time fraction on the truncated interval rather
            # than selecting nodes from the full-orbit quadrature.
            mi, ha = 0.5 * (rp + 0.01), 0.5 * (0.01 - rp)
            ri = mi - ha * np.cos(XT)
            dri = ha * np.sin(XT) * WT
            vri = np.sqrt(np.maximum(2.0 * (E - phi(ri)) - J2 / (ri * ri), 1e-300))
            pins[j] = np.sum(dri / vri) / norm
        ir = np.sum(dr * vr) / PI
        ep = mapped_plummer_energy(E, J2, ir)
        fis[j] = fplum(ep)

    # Radial-orbit angular diffusion kernel, using interpolation above.
    lvr = interp_local(sg, loc.reshape(nr, nloc * nf), rr0 / rm)
    lvr = lvr.reshape(len(rr0), nloc, nf)
    bt0 = lvr[:, 2]
    kmu = 2.0 * np.sum((wr0 * rr0 * rr0 / np.maximum(vv0, 1e-300))[:, None]
                       * bt0, axis=0) / (p0 * h)
    # Boundary orbit period.
    _, plc = action_period_final(E, lc * h, rc)
    return dict(**out, g=gg, p0=p0, h=h, lc=lc, L=L, R=Rv,
                period=periods, weight=weights, pin=pins, fi=fis,
                kmu=kmu, plc=plc)


def build_species(Earr, rt, xgrid, yf, verbose=False):
    rows = []
    for i, E in enumerate(Earr):
        rows.append(build_one_energy(E, rt, xgrid, yf))
        if verbose and i % 10 == 0:
            print("2d kernels", rt, i, len(Earr), E, flush=True)
    dd = {}
    for key in rows[0]:
        dd[key] = np.asarray([r[key] for r in rows])
    # Energy derivatives of h needed for R=J2/h(E).
    logh = np.log(dd["h"])
    kval = np.gradient(logh, Earr, edge_order=2)
    kp = np.gradient(kval, Earr, edge_order=2)
    dd["hk"], dd["hkp"] = kval, kp
    return dd


def save_dict(path, meta, L, H):
    vals = dict(meta)
    vals.update({"L_" + k: v for k, v in L.items()})
    vals.update({"H_" + k: v for k, v in H.items()})
    np.savez(path, **vals)


def load_prefixed(z, p):
    return {k[len(p):]: z[k] for k in z.files if k.startswith(p)}


class Model2D:
    def __init__(self, nL=58, nH=68, nx=16, nf=120,
                 cache="/app/output/code/cache2d.npz", rebuild=False,
                 verbose=True):
        self.e0L, self.e0H = find_e0(RL), find_e0(RH)
        self.dyL = np.log(-self.e0L / 0.1) / nL
        self.dyH = np.log(-self.e0H / 0.1) / nH
        self.yL = (np.arange(nL) + 0.5) * self.dyL
        self.yH = (np.arange(nH) + 0.5) * self.dyH
        self.EL = -0.1 * np.exp(self.yL)
        self.EH = -0.1 * np.exp(self.yH)
        self.dx = 1.0 / nx
        self.x = (np.arange(nx) + 0.5) * self.dx
        self.yf = np.linspace(0.0, np.log(-self.e0H / 0.1), nf)
        ok = False
        if os.path.exists(cache) and not rebuild:
            z = np.load(cache)
            ok = (z["EL"].shape == self.EL.shape and z["EH"].shape == self.EH.shape
                  and z["x"].shape == self.x.shape and z["yf"].shape == self.yf.shape
                  and np.max(abs(z["EL"] - self.EL)) < 1e-12)
        if ok:
            if verbose:
                print("loading", cache, flush=True)
            self.dL, self.dH = load_prefixed(z, "L_"), load_prefixed(z, "H_")
        else:
            if verbose:
                print("building 2d L", flush=True)
            self.dL = build_species(self.EL, RL, self.x, self.yf, verbose)
            if verbose:
                print("building 2d H", flush=True)
            self.dH = build_species(self.EH, RH, self.x, self.yf, verbose)
            save_dict(cache, dict(EL=self.EL, EH=self.EH, x=self.x, yf=self.yf),
                      self.dL, self.dH)

    def initial(self, FH):
        # weight=dGamma/dR times dR/dx; multiply by dE/dy=B.
        nL = (1.0 - FH) * (-self.EL[:, None]) * self.dL["weight"] * self.dL["fi"]
        nH = FH * (-self.EH[:, None]) * self.dH["weight"] * self.dH["fi"]
        return nL, nH

    def fields(self, nL, nH):
        NyL = np.sum(nL, axis=1) * self.dx
        NyH = np.sum(nH, axis=1) * self.dx
        fL = NyL / ((-self.EL) * self.dL["g"])
        fH = NyH / ((-self.EH) * self.dH["g"])
        fLf = np.interp(self.yf, self.yL, fL, left=fL[0], right=0.0)
        fHf = np.interp(self.yf, self.yH, fH, left=fH[0], right=0.0)
        return fLf, fHf

    def coefficients(self, fL, fH, species):
        d = self.dL if species == "L" else self.dH
        E = self.EL if species == "L" else self.EH
        mi = ML if species == "L" else MH
        ff = (mi + ML) * fL + (mi + MH) * fH
        fd = ML * fL + MH * fH
        aE = np.einsum("ixk,k->ix", d["aef"], ff) + np.einsum("ixk,k->ix", d["aed"], fd)
        bEE = np.einsum("ixk,k->ix", d["bee"], fd)
        au = np.einsum("ixk,k->ix", d["auf"], ff) + np.einsum("ixk,k->ix", d["aud"], fd)
        buu = np.einsum("ixk,k->ix", d["buu"], fd)
        beu = np.einsum("ixk,k->ix", d["beu"], fd)
        R = d["R"]
        h = d["h"][:, None]
        k = d["hk"][:, None]
        kp = d["hkp"][:, None]
        aR = (au / h - R * k * aE + 0.5 * R * (k * k - kp) * bEE
              - k * beu / h)
        bRR = buu / (h * h) + R * R * k * k * bEE - 2.0 * R * k * beu / h
        bER = beu / h - R * k * bEE
        ay = aE / E[:, None] - 0.5 * bEE / (E[:, None] ** 2)
        by = bEE / (E[:, None] ** 2)
        L = d["L"][:, None]
        # Exact Ito transformation x=ln(R/Rlc)/ln(1/Rlc).  The mixed
        # derivative is not advanced explicitly, but its contributions to
        # both diagonal moments and to the coordinate drift are retained.
        sy = np.gradient(np.log(d["L"]), np.log(-E), edge_order=2)[:, None]
        spy = np.gradient(sy[:, 0], np.log(-E), edge_order=2)[:, None]
        p = (1.0 - self.x[None, :]) * sy
        xR = 1.0 / (L * R)
        xyy = (1.0 - self.x[None, :]) * (spy - sy * sy)
        xyR = -sy / (L * R)
        xRR = -1.0 / (L * R * R)
        byR = bER / E[:, None]
        ax = (p * ay + xR * aR + 0.5 * xyy * by + xyR * byR
              + 0.5 * xRR * bRR)
        bx = p * p * by + xR * xR * bRR + 2.0 * p * xR * byR
        byx = p * by + xR * byR
        mu = d["kmu"] @ fd
        q = d["p0"] * mu / d["lc"]
        alpha = q / xi_of_q(q)
        # Flux through x=0 divided by n-density in the first cell.
        R0 = R[:, 0]
        A0 = 4.0 * PI * PI * d["h"] * d["plc"]
        W0 = d["weight"][:, 0]
        boundary_ratio = ((-E) * A0 * mu /
                          (alpha + d["L"] * self.dx * 0.5)) / ((-E) * W0)
        lam0 = boundary_ratio / self.dx
        return (ay, np.maximum(by, 0.0), ax, np.maximum(bx, 0.0), byx,
                np.maximum(lam0, 0.0), q)

    @staticmethod
    def cc_matrix_coeff(a, b, step):
        bp = np.gradient(b, step, edge_order=2)
        A = a - 0.5 * bp
        Af = 0.5 * (A[:-1] + A[1:])
        Df = 0.25 * (b[:-1] + b[1:])
        w = Af * step / np.maximum(Df, 1e-300)
        delta = np.empty_like(w)
        sm = np.abs(w) < 1e-3
        delta[sm] = 0.5 - w[sm] / 12.0 + w[sm] ** 3 / 720.0
        pos, neg = w >= 50.0, w <= -50.0
        mid = ~(sm | pos | neg)
        delta[pos] = 1.0 / w[pos]
        delta[neg] = 1.0 + 1.0 / w[neg]
        delta[mid] = 1.0 / w[mid] - 1.0 / np.expm1(w[mid])
        cL = Af * (1.0 - delta) + Df / step
        cR = Af * delta - Df / step
        N = len(a)
        lo = cL / step
        up = -cR / step
        dg = np.empty(N)
        dg[0], dg[-1] = -cL[0] / step, cR[-1] / step
        dg[1:-1] = (cR[:-1] - cL[1:]) / step
        return lo, dg, up

    def sweep_energy(self, n, ay, by, dy, dt):
        out = np.empty_like(n)
        for j in range(n.shape[1]):
            lo, dg, up = self.cc_matrix_coeff(ay[:, j], by[:, j], dy)
            out[:, j] = thomas(-dt * lo, 1.0 - dt * dg, -dt * up, n[:, j])
        return np.maximum(out, 0.0)

    def sweep_angular(self, n, ax, bx, lam0, dt):
        out = np.empty_like(n)
        for i in range(n.shape[0]):
            lo, dg, up = self.cc_matrix_coeff(ax[i], bx[i], self.dx)
            diag = 1.0 - dt * dg
            diag[0] += dt * lam0[i]
            out[i] = thomas(-dt * lo, diag, -dt * up, n[i])
        return np.maximum(out, 0.0)

    def cross_term(self, n, byx, dy):
        """Conservative centred approximation to d_y d_x(byx*n)."""
        q = byx * n
        # d/dx at energy faces; use zero mixed flux on the x boundaries.
        qf = 0.5 * (q[:-1] + q[1:])
        gx = np.zeros_like(qf)
        gx[:, 1:-1] = (qf[:, 2:] - qf[:, :-2]) / (2.0 * self.dx)
        gx[:, 0] = (qf[:, 1] - qf[:, 0]) / self.dx
        gx[:, -1] = (qf[:, -1] - qf[:, -2]) / self.dx
        fy = np.zeros((n.shape[0] + 1, n.shape[1]))
        fy[1:-1] = gx
        return (fy[1:] - fy[:-1]) / dy

    def diagnostics(self, nL, nH, coeffL, coeffH):
        laL, laH = coeffL[5], coeffH[5]
        mL = np.sum(nL) * self.dyL * self.dx
        mH = np.sum(nH) * self.dyH * self.dx
        capL = np.sum(laL * nL[:, 0]) * self.dyL * self.dx / ML
        capH = np.sum(laH * nH[:, 0]) * self.dyH * self.dx / MH
        inL = np.sum(nL * self.dL["pin"]) * self.dyL * self.dx / ML
        inH = np.sum(nH * self.dH["pin"]) * self.dyH * self.dx / MH
        return capL, capH, mL / ML, mH / MH, inH / inL

    def run(self, FH=0.02, tmax=30000.0, dt=10.0, verbose=False):
        nL, nH = self.initial(FH)
        rec = [[] for _ in range(7)]
        t, it = 0.0, 0
        while t <= tmax + 1e-8:
            fL, fH = self.fields(nL, nH)
            cL = self.coefficients(fL, fH, "L")
            cH = self.coefficients(fL, fH, "H")
            diag = self.diagnostics(nL, nH, cL, cH)
            vals = (t,) + diag + ((cL[6].min(), cL[6].max(), cH[6].min(), cH[6].max()),)
            for a, v in zip(rec, vals):
                a.append(v)
            if t >= tmax:
                break
            dtn = min(dt, tmax - t)
            # Energy and angular ADI sweeps, coefficients frozen over dt.
            # The mixed derivative is retained in the transformed diagonal
            # moments; an explicit mixed-flux update is too diffusive at the
            # loss-cone corner and is therefore omitted in this ADI solve.
            nL0 = nL + dtn * self.cross_term(nL, cL[4], self.dyL)
            nH0 = nH + dtn * self.cross_term(nH, cH[4], self.dyH)
            nL = self.sweep_energy(nL0, cL[0], cL[1], self.dyL, dtn)
            nH = self.sweep_energy(nH0, cH[0], cH[1], self.dyH, dtn)
            nL = self.sweep_angular(nL, cL[2], cL[3], cL[5], dtn)
            nH = self.sweep_angular(nH, cH[2], cH[3], cH[5], dtn)
            t += dtn
            it += 1
            if verbose and it % max(1, int(1000 / dt)) == 0:
                print("2d evolve", FH, t, diag, flush=True)
        names = ["t", "rL", "rH", "NL", "NH", "seg", "q"]
        return {k: np.asarray(v) for k, v in zip(names, rec)}


def crossing(t, x, val):
    ii = np.nonzero(x <= val)[0]
    if len(ii) == 0:
        return np.nan
    k = ii[0]
    if k == 0:
        return t[0]
    return t[k-1] + (val-x[k-1])*(t[k]-t[k-1])/(x[k]-x[k-1])


def summary(z):
    t = z["t"]
    use = (t >= 100) & (t <= 5000)
    il = np.nonzero(use)[0][np.argmax(z["rL"][use])]
    useh = t >= 100
    ih = np.nonzero(useh)[0][np.argmax(z["rH"][useh])]
    return dict(ndotL_max=float(z["rL"][il]), t_ndotL_max=float(t[il]),
                ndotH_max=float(z["rH"][ih]),
                t_half_H=float(crossing(t, z["NH"], .5*z["NH"][0])),
                seg_max=float(np.max(z["seg"][1:])),
                rate_ratio_1e4=float(np.interp(1e4,t,z["rH"])/np.interp(1e4,t,z["rL"])))


def gmetric(z):
    t, r = z["t"], z["rL"]
    k = max(1, int(round(50/(t[1]-t[0]))))
    d = (r[2*k:]-r[:-2*k])/(t[2*k:]-t[:-2*k])
    tm=t[k:-k];use=(tm>=300)&(tm<=10000)
    return float(d[use].min())


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--rebuild',action='store_true');ap.add_argument('--dt',type=float,default=10)
    ap.add_argument('--tmax',type=float,default=30000);ap.add_argument('--fractions',action='store_true')
    ap.add_argument('--nL',type=int,default=58);ap.add_argument('--nH',type=int,default=68)
    ap.add_argument('--nx',type=int,default=16);ap.add_argument('--nf',type=int,default=120)
    ap.add_argument('--cache',default='/app/output/code/cache2d.npz')
    a=ap.parse_args(); t0=time.time()
    m=Model2D(a.nL,a.nH,a.nx,a.nf,a.cache,a.rebuild,True)
    print('2d model ready',time.time()-t0,flush=True)
    z=m.run(.02,a.tmax,a.dt,True);np.savez('/app/output/code/base2d.npz',**z)
    ans=summary(z)
    if a.fractions:
        fs=np.array([.002,.005,.008,.011,.014,.017,.02]);gs=[]
        for f in fs:
            zz=m.run(f,10100,a.dt);gs.append(gmetric(zz));print('2d fraction',f,gs[-1],flush=True)
        star=np.nan
        for x1,x2,y1,y2 in zip(fs[:-1],fs[1:],gs[:-1],gs[1:]):
            if y1*y2<=0:star=x1-y1*(x2-x1)/(y2-y1);break
        ans['F_H_star']=float(star);np.savez('/app/output/code/fracs2d.npz',f=fs,g=gs)
    else:ans['F_H_star']=.01
    with open('/app/output/answer.json','w') as fp:json.dump(ans,fp,indent=2);fp.write('\n')
    print(json.dumps(ans,indent=2),flush=True)


if __name__=='__main__':main()
