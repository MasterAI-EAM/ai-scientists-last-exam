"""Candidate keys from a run2.py output (npz)."""
import numpy as np, sys


def _ext(T, Y, lo, hi, sign, logt=False, wfrac=0.15):
    s = (T >= lo) & (T <= min(hi, T[-1]))
    Ts, Ys = T[s], Y[s]
    i = np.argmax(sign * Ys)
    if i == 0 or i == len(Ts) - 1:
        return float('nan'), float('nan')
    w = (Ts > Ts[i] * (1 - wfrac)) & (Ts < Ts[i] * (1 + wfrac))
    X = np.log(Ts[w]) if logt else Ts[w] / Ts[i]
    c = np.polyfit(X, Ys[w], 4)
    xx = np.linspace(X[0], X[-1], 40001)
    yy = np.polyval(c, xx)
    k = np.argmax(sign * yy)
    tt = np.exp(xx[k]) if logt else xx[k] * Ts[i]
    return float(yy[k]), float(tt)


def cross(T, Y, level, lo=0.0):
    """first time after lo at which Y crosses level (cubic interpolation in the bracketing 4 points)"""
    s = np.where((T >= lo))[0]
    for j in s[:-1]:
        if (Y[j] - level) * (Y[j + 1] - level) <= 0 and Y[j] != Y[j + 1]:
            jj = np.arange(max(j - 1, 0), min(j + 3, len(T)))
            c = np.polyfit(T[jj] - T[j], Y[jj] - level, min(3, len(jj) - 1))
            tt = np.linspace(0, T[j + 1] - T[j], 20001)
            yy = np.polyval(c, tt)
            k = np.where(np.sign(yy[1:]) != np.sign(yy[:-1]))[0]
            return float(T[j] + (tt[k[0]] if len(k) else (level - Y[j]) / (Y[j + 1] - Y[j]) * (T[j + 1] - T[j])))
    return float('nan')


def gmin(T, NL, lo=300.0, hi=10000.0):
    """min of dNL/dt over [lo, hi]: centred differences, refined by a quadratic through the 3 smallest"""
    g = np.gradient(NL, T)
    s = np.where((T >= lo) & (T <= hi))[0]
    i = s[np.argmin(g[s])]
    if i - 1 in s and i + 1 in s:
        c = np.polyfit(T[i - 1:i + 2] - T[i], g[i - 1:i + 2], 2)
        if c[0] > 0:
            return float(np.polyval(c, -c[1] / (2 * c[0])))
    return float(g[i])


def keys(fn, mL=1e-5, mH=1e-4):
    d = np.load(fn)
    T, NL, NH = d['T'][1:], d['NL'][1:], d['NH'][1:]
    out = {}
    out['NLmax'], out['tLmax'] = _ext(T, NL, 100, 5000, +1)
    out['NHmax'], out['tHmax'] = _ext(T, NH, 100, 1e9, +1)
    MH = d['MH']
    out['thalf'] = cross(d['T'], MH, 0.5 * MH[0])
    rad = list(d['radii']); IN = d['IN']
    for r0 in (0.003, 0.01):
        if r0 in rad:
            k = rad.index(r0)
            rat = (IN[1:, 2 * k + 1] / mH) / (IN[1:, 2 * k] / mL)
            out['rat%g' % r0], out['trat%g' % r0] = _ext(T, rat, 100, 1e9, +1, wfrac=0.3)
    if T[-1] >= 1e4:
        out['rr1e4'] = float(np.interp(1e4, T, NH) / np.interp(1e4, T, NL))
    # threshold diagnostic: min dNL/dt over 300 <= t <= 12000
    out['gmin'] = gmin(T, NL)
    return out


if __name__ == '__main__':
    for fn in sys.argv[1:]:
        o = keys(fn)
        print(fn.split('/')[-1][:-4].ljust(14), ' '.join('%s=%.6g' % kv for kv in o.items()))
