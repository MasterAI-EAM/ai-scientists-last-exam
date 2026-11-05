"""lc2.py -- two-species extension kernels for the 2-D (E,R) loss-cone FP (lcfp.py copied unchanged).

Flux (Landau) form for test species i in the field of species j (mass DFs fbar_j):
  friction    A_par  = -16 pi^2 G^2 lnL  m_i  sum_j J_{1/2}[fbar_j] / v       (prop. to the TEST mass)
  diffusion   D_par  = (32 pi^2 G^2 lnL/3) sum_j m_j (J_{3/2}[fbar_j] + I_0[fbar_j])
              D_perp = (32 pi^2 G^2 lnL/3) sum_j m_j (3J_{1/2} - J_{3/2} + 2 I_0)[fbar_j]
jtA = sum_j table(fbar_j),  jtD = sum_j m_j table(fbar_j);  GamA = 16 pi^2 lnL m_i, GamD = 16 pi^2 lnL.
"""
import math
import numpy as np
from numba import njit
from lcfp import PI, phi, circ, turning, rmax_of_E


@njit(cache=True)
def _interp(jt, L, lam, lam0, dlam, nlam):
    t = (lam - lam0) / dlam
    if t <= 0.0:
        return jt[L, 0, 0], jt[L, 0, 1]
    elif t >= nlam - 1:
        fac = math.exp(-(lam - (lam0 + (nlam - 1) * dlam)))
        return jt[L, nlam - 1, 0] * fac, jt[L, nlam - 1, 1] * fac
    kk = int(t)
    u = t - kk
    return (1 - u) * jt[L, kk, 0] + u * jt[L, kk + 1, 0], (1 - u) * jt[L, kk, 1] + u * jt[L, kk + 1, 1]


@njit(cache=True)
def orbit_coeffs2(lev, Rs, rr, WW, vv, vr2, Jc2a, kapa, jtA, jtD, I0D, lam0, dlam, GamA, GamD, out):
    n = Rs.shape[0]
    nlam = jtD.shape[1]
    nth = rr.shape[1]
    for i in range(n):
        L = lev[i]
        R = Rs[i]
        Jc2 = Jc2a[i]
        kap = kapa[i]
        i0 = I0D[L]
        sE = 0.0; sR = 0.0; sEE = 0.0; sER = 0.0; sRR = 0.0; sP = 0.0
        for k in range(nth):
            v = vv[i, k]
            W = WW[i, k]
            x = 0.5 * v * v
            lam = math.log(x)
            a1, a3 = _interp(jtA, L, lam, lam0, dlam, nlam)
            d1, d3 = _interp(jtD, L, lam, lam0, dlam, nlam)
            eta = -GamA * a1 * x / v
            J1 = d1 * x
            J3 = d3 * x
            apar = (2.0 * GamD / 3.0) * (J3 + i0)
            aper = (2.0 * GamD / 3.0) * (3.0 * J1 - J3 + 2.0 * i0)
            gpar = R * (2.0 / v - kap * v)
            r = rr[i, k]
            gper2 = 4.0 * R * r * r * vr2[i, k] / (Jc2 * v * v)
            sE += W * (-eta * v)
            sR += W * (-eta * gpar)
            sEE += W * 0.5 * apar * v * v
            sER += W * 0.5 * apar * v * gpar
            sRR += W * (0.5 * apar * gpar * gpar + 0.25 * aper * gper2)
            sP += W
        pre = 8.0 * PI * PI * Jc2
        out[i, 0] = pre * sE
        out[i, 1] = pre * sR
        out[i, 2] = pre * sEE
        out[i, 3] = pre * sER
        out[i, 4] = pre * sRR
        out[i, 5] = 2.0 * sP


@njit(cache=True)
def frac_inside(Es, Rs, r0, mu, pl, nq, out):
    """fraction of the radial period spent at r < r0 for orbits (E, R); Gauss-Chebyshev-like
    substitution r = rp + (b-rp)(1-cos th)/2 on [rp, b], b = min(ra, r0) (regular at b < ra)."""
    for i in range(Es.shape[0]):
        E = Es[i]; R = Rs[i]
        rc, Jc2, kap, dEdx = circ(E, mu, pl)
        J2 = R * Jc2
        rp, ra = turning(E, J2, rc, mu, pl)
        if ra <= r0:
            out[i] = 1.0
            continue
        if rp >= r0:
            out[i] = 0.0
            continue
        # full half-period with the standard substitution
        tot = 0.0
        d = ra - rp
        for k in range(nq):
            th = (k + 0.5) * PI / nq
            r = rp + 0.5 * d * (1.0 - math.cos(th))
            vr2 = 2.0 * (E - phi(r, mu, pl)) - J2 / (r * r)
            if vr2 < 1e-300:
                vr2 = 1e-300
            tot += 0.5 * d * math.sin(th) * (PI / nq) / math.sqrt(vr2)
        # inside part: u in [0, 1], r = rp + (r0-rp) * (1 - cos(pi u/2)) ... singular only at rp
        part = 0.0
        d2 = r0 - rp
        for k in range(nq):
            th = (k + 0.5) * 0.5 * PI / nq
            r = rp + d2 * (1.0 - math.cos(th))
            vr2 = 2.0 * (E - phi(r, mu, pl)) - J2 / (r * r)
            if vr2 < 1e-300:
                vr2 = 1e-300
            part += d2 * math.sin(th) * (0.5 * PI / nq) / math.sqrt(vr2)
        out[i] = part / tot
