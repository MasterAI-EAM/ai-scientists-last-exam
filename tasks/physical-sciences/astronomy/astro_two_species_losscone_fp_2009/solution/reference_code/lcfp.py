"""lcfp.py -- 2-D orbit-averaged Fokker-Planck evolution in (E, R=J^2/Jc^2) of stars around a
central black hole with a loss cone (Cohn & Kulsrud boundary condition at R = R_lc(E)).

Fixed potential Phi(r) = -mu/r - 1/sqrt(1+r^2) (G = 1, frozen Plummer M=1, a=1, plus BH mu).
Field stars: isotropised DF fbar(E) = N(E)/g(E) (N = mass per unit E of stars outside the loss cone).
Coordinates: x = ln r_c(E) (cell grid), w in [0,1] with ln R = (1-w) ln R_lc(E): loss-cone boundary
at w = 0, circular orbits at w = 1.  Flux form, Chang-Cooper weighting in the principal direction,
centred cross terms (physical + mapping), variable-step BDF2 with extrapolated coefficients.
"""
import math
import numpy as np
from numba import njit
import scipy.sparse as sp
from scipy.sparse.linalg import splu
from scipy.special import jn_zeros

PI = math.pi


# ------------------------------------------------------------------ potential
@njit(cache=True)
def phi(r, mu, pl):
    return -mu / r - pl / math.sqrt(1.0 + r * r)


@njit(cache=True)
def dphi(r, mu, pl):
    return mu / (r * r) + pl * r / (1.0 + r * r) ** 1.5


@njit(cache=True)
def d2phi(r, mu, pl):
    return -2.0 * mu / r ** 3 + pl * (1.0 - 2.0 * r * r) / (1.0 + r * r) ** 2.5


@njit(cache=True)
def Ec_of_r(r, mu, pl):
    return phi(r, mu, pl) + 0.5 * r * dphi(r, mu, pl)


@njit(cache=True)
def rc_of_E(E, mu, pl):
    lo, hi = -60.0, 25.0
    for it in range(200):
        m = 0.5 * (lo + hi)
        if Ec_of_r(math.exp(m), mu, pl) < E:
            lo = m
        else:
            hi = m
        if hi - lo < 1e-15:
            break
    return math.exp(0.5 * (lo + hi))


@njit(cache=True)
def rmax_of_E(E, mu, pl):
    lo, hi = -60.0, 25.0
    for it in range(200):
        m = 0.5 * (lo + hi)
        if phi(math.exp(m), mu, pl) < E:
            lo = m
        else:
            hi = m
        if hi - lo < 1e-15:
            break
    return math.exp(0.5 * (lo + hi))


@njit(cache=True)
def circ(E, mu, pl):
    """rc, Jc^2, kappa = dlnJc^2/dE, dE/dlnrc"""
    r = rc_of_E(E, mu, pl)
    p1 = dphi(r, mu, pl)
    p2 = d2phi(r, mu, pl)
    Jc2 = r ** 3 * p1
    dEdr = 1.5 * p1 + 0.5 * r * p2
    dJ2dr = 3 * r * r * p1 + r ** 3 * p2
    return r, Jc2, dJ2dr / (Jc2 * dEdr), r * dEdr


@njit(cache=True)
def turning(E, J2, rc, mu, pl):
    # pericentre in (0, rc), apocentre in (rc, rmax)
    lo, hi = -80.0, math.log(rc)
    for it in range(200):
        m = 0.5 * (lo + hi)
        r = math.exp(m)
        h = 2 * r * r * (E - phi(r, mu, pl)) - J2
        if h < 0:
            lo = m
        else:
            hi = m
        if hi - lo < 1e-15:
            break
    rp = math.exp(0.5 * (lo + hi))
    lo, hi = math.log(rc), math.log(rmax_of_E(E, mu, pl))
    for it in range(200):
        m = 0.5 * (lo + hi)
        r = math.exp(m)
        h = 2 * r * r * (E - phi(r, mu, pl)) - J2
        if h > 0:
            lo = m
        else:
            hi = m
        if hi - lo < 1e-15:
            break
    ra = math.exp(0.5 * (lo + hi))
    return rp, ra


@njit(cache=True)
def orbit_nodes(E, R, mu, pl, nth, r_out, W_out, v_out, vr2_out):
    """quadrature over half a radial period: sum W g = int_{rp}^{ra} g dr/|v_r|"""
    rc, Jc2, kap, dEdx = circ(E, mu, pl)
    J2 = R * Jc2
    if R <= 0.0:
        rp = 0.0
        ra = rmax_of_E(E, mu, pl)
    else:
        rp, ra = turning(E, J2, rc, mu, pl)
    d = ra - rp
    for k in range(nth):
        th = (k + 0.5) * PI / nth
        r = rp + 0.5 * d * (1.0 - math.cos(th))
        v2 = 2.0 * (E - phi(r, mu, pl))
        vr2 = v2 - J2 / (r * r)
        if vr2 < 1e-300:
            vr2 = 1e-300
        r_out[k] = r
        W_out[k] = 0.5 * d * math.sin(th) * (PI / nth) / math.sqrt(vr2)
        v_out[k] = math.sqrt(v2)
        vr2_out[k] = vr2
    return Jc2, kap


@njit(cache=True)
def build_orbits(Es, Rs, mu, pl, nth, rr, WW, vv, vr2, Jc2a, kapa):
    n = Es.shape[0]
    for i in range(n):
        Jc2, kap = orbit_nodes(Es[i], Rs[i], mu, pl, nth, rr[i], WW[i], vv[i], vr2[i])
        Jc2a[i] = Jc2
        kapa[i] = kap


@njit(cache=True)
def radial_action(E, J2, mu, pl, nth):
    rc, Jc2, kap, dEdx = circ(E, mu, pl)
    if J2 >= Jc2:
        return 0.0
    rp, ra = turning(E, J2, rc, mu, pl)
    d = ra - rp
    s = 0.0
    for k in range(nth):
        th = (k + 0.5) * PI / nth
        r = rp + 0.5 * d * (1.0 - math.cos(th))
        vr2 = 2.0 * (E - phi(r, mu, pl)) - J2 / (r * r)
        if vr2 > 0:
            s += 0.5 * d * math.sin(th) * (PI / nth) * math.sqrt(vr2)
    return s / PI


@njit(cache=True)
def plummer_E_of_action(Ir, J2, nth):
    # invert I_r(E_P, J) = Ir in the pure Plummer potential (mu=0)
    J = math.sqrt(J2)
    # circular energy for this J: solve r^3 Phi' = J^2
    lo, hi = -40.0, 25.0
    for it in range(200):
        m = 0.5 * (lo + hi)
        r = math.exp(m)
        if r ** 3 * dphi(r, 0.0, 1.0) < J2:
            lo = m
        else:
            hi = m
        if hi - lo < 1e-15:
            break
    r = math.exp(0.5 * (lo + hi))
    Elo = Ec_of_r(r, 0.0, 1.0)
    if Ir <= 0.0:
        return Elo
    Ehi = -1e-14
    for it in range(100):
        Em = 0.5 * (Elo + Ehi)
        if radial_action(Em, J2, 0.0, 1.0, nth) < Ir:
            Elo = Em
        else:
            Ehi = Em
        if Ehi - Elo < 1e-14 * abs(Em):
            break
    return 0.5 * (Elo + Ehi)


@njit(cache=True)
def init_df(Es, Rs, mu, nth, out, EPout):
    for i in range(Es.shape[0]):
        rc, Jc2, kap, dEdx = circ(Es[i], mu, 1.0)
        J2 = Rs[i] * Jc2
        Ir = radial_action(Es[i], J2, mu, 1.0, nth)
        EP = plummer_E_of_action(Ir, J2, nth)
        EPout[i] = EP
        out[i] = 24.0 * math.sqrt(2.0) / (7.0 * PI ** 3) * (-EP) ** 3.5 if EP < 0 else 0.0


# ------------------------------------------------------------------ field tables
@njit(cache=True)
def field_tables(Elev, Ef, fb, lam0, dlam, nlam, jt, I0):
    """jt[L,k,0/1] = J_{1/2}/(E-Phi), J_{3/2}/(E-Phi) at E=Elev[L], E-Phi = exp(lam_k);
    I0[L] = int_E^0 fbar dE'.  fbar piecewise constant on cells [Ef[i], Ef[i+1]]."""
    NE = fb.shape[0]
    for L in range(Elev.shape[0]):
        E = Elev[L]
        s = 0.0
        for i in range(NE):
            a = max(Ef[i], E)
            b = Ef[i + 1]
            if b > a:
                s += fb[i] * (b - a)
        I0[L] = s
        for k in range(nlam):
            x = math.exp(lam0 + k * dlam)
            P = E - x
            s1 = 0.0
            s3 = 0.0
            # first cell with Ef[i+1] > P
            lo = 0
            hi = NE
            if Ef[1] > P:
                i0 = 0
            else:
                while hi - lo > 1:
                    md = (lo + hi) // 2
                    if Ef[md] > P:
                        hi = md
                    else:
                        lo = md
                i0 = lo
            for i in range(i0, NE):
                if Ef[i] >= E:
                    break
                b = min(Ef[i + 1], E)
                if b <= P:
                    continue
                a = max(Ef[i], P)
                ub = (b - P) / x
                ua = (a - P) / x
                sb = math.sqrt(ub)
                sa = math.sqrt(ua)
                s1 += fb[i] * (ub * sb - ua * sa)
                s3 += fb[i] * (ub * ub * sb - ua * ua * sa)
            jt[L, k, 0] = s1 / 1.5
            jt[L, k, 1] = s3 / 2.5


@njit(cache=True)
def orbit_coeffs(lev, Elev, Rs, rr, WW, vv, vr2, Jc2a, kapa, jt, I0, lam0, dlam, Gam, out):
    """out[i,:] = D_E, D_R, D_EE, D_ER, D_RR, P (flux coefficients incl. 8 pi^2 Jc^2)"""
    n = Rs.shape[0]
    nlam = jt.shape[1]
    nth = rr.shape[1]
    for i in range(n):
        L = lev[i]
        E = Elev[L]
        R = Rs[i]
        Jc2 = Jc2a[i]
        kap = kapa[i]
        i0 = I0[L]
        sE = 0.0
        sR = 0.0
        sEE = 0.0
        sER = 0.0
        sRR = 0.0
        sP = 0.0
        for k in range(nth):
            v = vv[i, k]
            W = WW[i, k]
            x = 0.5 * v * v
            lam = math.log(x)
            t = (lam - lam0) / dlam
            if t <= 0.0:
                j1 = jt[L, 0, 0]
                j3 = jt[L, 0, 1]
            elif t >= nlam - 1:
                fac = math.exp(-(lam - (lam0 + (nlam - 1) * dlam)))
                j1 = jt[L, nlam - 1, 0] * fac
                j3 = jt[L, nlam - 1, 1] * fac
            else:
                kk = int(t)
                u = t - kk
                j1 = (1 - u) * jt[L, kk, 0] + u * jt[L, kk + 1, 0]
                j3 = (1 - u) * jt[L, kk, 1] + u * jt[L, kk + 1, 1]
            J1 = j1 * x
            J3 = j3 * x
            eta = -Gam * J1 / v
            apar = (2.0 * Gam / 3.0) * (J3 + i0)
            aper = (2.0 * Gam / 3.0) * (3.0 * J1 - J3 + 2.0 * i0)
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
def radial_mu(lev, Elev, rr, WW, vv, Jc2a, jt, I0, lam0, dlam, Gam, out):
    """mubar(E) = lim_{R->0} <dR^2>/(2R) orbit averaged, from the radial orbit quadrature.
    out[i,0] = mubar, out[i,1] = P(E) radial period."""
    n = lev.shape[0]
    nlam = jt.shape[1]
    nth = rr.shape[1]
    for i in range(n):
        L = lev[i]
        i0 = I0[L]
        s = 0.0
        sP = 0.0
        for k in range(nth):
            v = vv[i, k]
            W = WW[i, k]
            x = 0.5 * v * v
            lam = math.log(x)
            t = (lam - lam0) / dlam
            if t <= 0.0:
                j1 = jt[L, 0, 0]
                j3 = jt[L, 0, 1]
            elif t >= nlam - 1:
                fac = math.exp(-(lam - (lam0 + (nlam - 1) * dlam)))
                j1 = jt[L, nlam - 1, 0] * fac
                j3 = jt[L, nlam - 1, 1] * fac
            else:
                kk = int(t)
                u = t - kk
                j1 = (1 - u) * jt[L, kk, 0] + u * jt[L, kk + 1, 0]
                j3 = (1 - u) * jt[L, kk, 1] + u * jt[L, kk + 1, 1]
            J1 = j1 * x
            J3 = j3 * x
            aper = (2.0 * Gam / 3.0) * (3.0 * J1 - J3 + 2.0 * i0)
            r = rr[i, k]
            s += W * aper * r * r
            sP += W
        P = 2.0 * sP
        out[i, 0] = 2.0 * s / (P * Jc2a[i])   # (2/(P Jc^2)) int_0^rmax aper r^2 dr/v
        out[i, 1] = P


# ------------------------------------------------------------------ CK boundary function
_JZ = jn_zeros(0, 4000)


def alpha_ck(q):
    """alpha(q) = q / xi(q),  xi = 1 - 4 sum exp(-j_m^2 q/4)/j_m^2  (Cohn & Kulsrud 1978)"""
    q = np.atleast_1d(np.asarray(q, float))
    out = np.empty_like(q)
    jz2 = _JZ ** 2
    for k, qq in enumerate(q):
        if qq > 1e-5:
            xi = 1.0 - 4.0 * np.sum(np.exp(-jz2 * qq / 4.0) / jz2)
            out[k] = qq / xi
        else:
            out[k] = 0.5 * math.sqrt(math.pi * qq)
    return out


def cc_delta(W):
    W = np.asarray(W, float)
    out = np.full(W.shape, 0.5)
    big = np.abs(W) > 1e-6
    Wb = W[big]
    with np.errstate(over='ignore'):
        out[big] = 1.0 / Wb - 1.0 / np.expm1(Wb)
    small = ~big
    out[small] = 0.5 - W[small] / 12.0
    return out
