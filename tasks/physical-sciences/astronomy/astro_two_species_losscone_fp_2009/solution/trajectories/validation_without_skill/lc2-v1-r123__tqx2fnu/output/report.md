# Method

I used a numpy-only orbit-averaged Fokker--Planck calculation.  The static
orbit library contains circular angular momenta, turning points, periods,
phase volumes, and the adiabatically mapped initial DF.  The mapping was done
by matching both `J` and the radial action to an orbit in the original
Plummer potential.

The velocity integrals in the supplied local diffusion coefficients were
stored as linear kernels acting on the current isotropised fields
`N_i(E)/g(E)`.  They were then orbit-averaged for each energy and angular
momentum cell.  The evolved grid used logarithmic binding energy and
`x = ln(R/R_lc)/ln(1/R_lc)`.  The code includes the Ito coordinate terms and
the mixed energy--angular-momentum covariance.  The loss-cone flux uses the
given `q`, Bessel-zero expression for `xi(q)`, and Robin boundary condition;
`q` and all diffusion coefficients are recomputed from the evolving DFs.

The conservative diagonal operators were advanced implicitly with
Chang--Cooper face fluxes.  The mixed term was applied as a conservative
centred flux before the two implicit sweeps.  Reflecting energy and `R=1`
boundaries were imposed as zero numerical fluxes.  Capture was the only term
allowed to change total mass.

# Checks

- The post-cut initial masses approach the independently integrated 1-D
  values as the angular grid is refined.
- With capture disabled, the finite-volume operator conserves mass to roundoff.
- Re-integrating `4 pi^2 J_c^2 P` over angular momentum agrees with the direct
  `g(E)` quadrature.
- Spatial counts use a separate, endpoint-regularised orbital time integral
  below `r=0.01`, rather than selecting nodes from the full-orbit quadrature.
- Runs with 28, 40, and 64 angular cells and several timesteps were used for
  Richardson-style extrapolation of the baseline diagnostics.  The peak time
  was stable near 140; the finite-grid baseline maxima bracketed the reported
  extrapolated values.

The main implementation is `output/code/solver2d.py`.  `solver.py` is the
initial isotropic reduction used as a cross-check, and `solver_qs.py` is a
quasi-steady loss-cone comparison.
