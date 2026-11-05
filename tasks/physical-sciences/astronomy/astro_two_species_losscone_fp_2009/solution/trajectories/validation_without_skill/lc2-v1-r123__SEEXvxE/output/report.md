# Method and checks

I solved the coupled, orbit-averaged Fokker--Planck problem numerically.  The
potential-dependent quantities (turning points, circular angular momentum,
radial actions, periods, and density of states) were evaluated with
Gauss--Legendre quadrature and bracketed scalar root solves using only NumPy.
The initial distribution was obtained orbit by orbit by matching both `J` and
`I_r` to an orbit in the original Plummer potential.

The production solver uses energy and a loss-cone-fitted angular coordinate

`y = log(R/R_lc) / log(1/R_lc)`.

It evolves the phase-space mass density including the full transformed drift
and diffusion tensor, including the mixed energy--angular-momentum term.  The
field-star distributions are isotropised from the current energy marginals at
every coefficient update.  Velocity integrals with square-root endpoints are
integrated analytically within each energy cell, while the remaining orbit
averages use Gaussian quadrature.  The loss boundary uses the specified
Bessel-zero expression for `xi(q)` and its Robin condition; the outer angular
and both energy boundaries have zero flux.

Checks performed include:

- numerical verification of `integral 4*pi^2*Jc^2*P dR = g(E)` (relative
  errors approximately `1e-11` or smaller at representative energies);
- mass accounting against the integrated loss-boundary flux;
- timestep halving for the mixed-term update (about a one-percent rate change
  on the coarse validation grid);
- uniform-grid and transition-refined energy-grid comparisons;
- explicit calculation of instantaneous-radius occupancy by orbital phase
  averaging, rather than assigning objects by semimajor axis.

For the light-rate peak, transition-refined meshes with 48, 72, and 96 energy
cells gave peak rates 0.14155, about 0.1407, and 0.14063.  The 96-cell peak was
flat over one coefficient-update block around t=625--650.  A refined long run
located the heavy half-mass crossing at about 6030, the central-number-ratio
maximum near 0.579, and the rate ratio at t=10000 near 0.0936.  Fraction runs
at 0.002, 0.0045, 0.006, and 0.012 were used to bracket and resolution-correct
the sign change defining `F_H_star`.

`solver2d.py` is the production calculation.  `solver.py` contains the orbit
library and a reduced one-dimensional comparison solver used during checks.
