#!/usr/bin/env python3
"""Two-dimensional orbit-averaged FP solver on (E,y), y=ln(R/Rlc)/ln(1/Rlc)."""
import os, sys, json
import numpy as np
from solver import (MU,LNLA,ML,MH,EB,RL,RH,OUT,GX,GW,TH,THW,S2,DS2,
                    phi,dphi,radial_integrals,circ_geom,rloss,find_e0,
                    orbit_jr_period,old_energy,fp_plummer,xi_alpha,save_answer)

class Grid2D:
    def __init__(self,name,mass,rt,nE=34,nY=22,adaptive=False):
        self.name,self.mass,self.rt=name,mass,rt
        self.e0=find_e0(rt)
        if adaptive:
            # The loss flux has a narrow energy dependence around E~-1,
            # where the black-hole and stellar potentials exchange dominance.
            # Concentrate most cells there while retaining both long tails.
            n1=max(8,int(round(nE*20/72)));n2=max(12,int(round(nE*36/72)));n3=nE-n1-n2
            if n3<8:n3=8;n2=nE-n1-n3
            bed=np.r_[np.geomspace(-self.e0,1.5,n1+1)[:-1],
                      np.geomspace(1.5,.65,n2+1)[:-1],
                      np.geomspace(.65,-EB,n3+1)]
        else:
            bed=np.geomspace(-self.e0,-EB,nE+1)
        self.ee=-bed; self.E=-np.sqrt(bed[:-1]*bed[1:]);self.dE=np.diff(self.ee)
        self.nE=nE;self.nY=nY
        self.ye=np.linspace(0,1,nY+1);self.y=.5*(self.ye[:-1]+self.ye[1:]);self.dy=1/nY
        self.ra=np.empty(nE);self.rc=np.empty(nE);self.jc2=np.empty(nE)
        self.p0=np.empty(nE);self.g=np.empty(nE);self.Rlc=np.empty(nE)
        for i,E in enumerate(self.E):
            ra,p0,g,*_=radial_integrals(E);rc,j2=circ_geom(E)
            self.ra[i]=ra;self.p0[i]=p0;self.g[i]=g;self.rc[i]=rc;self.jc2[i]=j2
            self.Rlc[i]=rloss(E,rt,j2)
        self.loglc=np.log(self.Rlc); self.L=-self.loglc
        self.R=np.exp(self.loglc[:,None]*(1-self.y[None,:]))
        # Derivatives used in transformations Q -> R -> y.
        self.ah=np.gradient(np.log(self.jc2),self.E,edge_order=2)
        self.ahp=np.gradient(self.ah,self.E,edge_order=2)
        self.lp=np.gradient(self.loglc,self.E,edge_order=2)
        self.lpp=np.gradient(self.lp,self.E,edge_order=2)
        self.P=np.empty((nE,nY));self.frac01=np.empty((nE,nY));self.C=np.empty((nE,nY))
        self.orbits=[[None]*nY for _ in range(nE)]
        fshape=np.empty((nE,nY))
        for i,E in enumerate(self.E):
            for j,R in enumerate(self.R[i]):
                jr,per,fr=orbit_jr_period(E,R*self.jc2[i],self.rc[i],self.ra[i],.01)
                Ep=old_energy(jr,np.sqrt(R*self.jc2[i]))
                self.P[i,j]=per;self.frac01[i,j]=fr
                self.C[i,j]=4*np.pi**2*self.jc2[i]*per*self.L[i]*R
                fshape[i,j]=fp_plummer(Ep)
                # Store quadrature along this orbit.
                q2=R*self.jc2[i]
                # Repeat turning point work once; orbit_jr_period is intentionally simple.
                from solver import turning
                rp,ra=turning(E,q2,self.rc[i],self.ra[i])
                rr=rp+(ra-rp)*S2;dr=(ra-rp)*DS2
                vr=np.sqrt(np.maximum(2*(E-phi(rr))-q2/(rr*rr),1e-300))
                self.orbits[i][j]=(rr,dr,vr,q2)
        self.fshape=fshape
        self.p=None;self.p0dist=None

    def energy_mass_density(self):
        return np.sum(self.p,axis=1)*self.dy

    def number(self):
        return np.sum(self.p*self.dE[:,None])*self.dy/self.mass

    def inner_number(self):
        return np.sum(self.p*self.frac01*self.dE[:,None])*self.dy/self.mass

def field_data(species):
    out=[]
    for s in species:
        N=s.energy_mass_density();f=N/s.g
        out.append((s,N,f))
    return out

def local_vcoeff(E, pharr, varr, target_mass, fields):
    """Local velocity coefficients along one test orbit."""
    shp=len(varr);fr=np.zeros(shp);bp=np.zeros(shp);bt=np.zeros(shp)
    C0=32*np.pi**2*LNLA/3
    for sj,Nj,fj in fields:
        # Upper integral int_E^Eb f dE is independent of radius.
        widths=np.maximum(0,np.minimum(sj.ee[1:],EB)-np.maximum(sj.ee[:-1],E))
        U=np.sum(fj*widths)
        I0=np.zeros(shp);I4=np.zeros(shp)
        for z,ph in enumerate(pharr):
            elo=np.maximum(sj.ee[:-1],ph);ehi=np.minimum(sj.ee[1:],E);ok=ehi>elo
            if np.any(ok):
                aa=np.maximum(elo[ok]-ph,0);zz=np.maximum(ehi[ok]-ph,0)
                I0[z]=np.sum(fj[ok]*(2*np.sqrt(2)/3)*(zz**1.5-aa**1.5))
                I4[z]=np.sum(fj[ok]*(2**2.5/5)*(zz**2.5-aa**2.5))
        fr+=(target_mass+sj.mass)*I0
        bp+=sj.mass*(I4/varr**3+U)
        bt+=sj.mass*(3*I0/varr-I4/varr**3+2*U)
    return -16*np.pi**2*LNLA*fr/(varr*varr),C0*bp,C0*bt

def coeff2d(s,fields):
    ne,ny=s.nE,s.nY
    AE=np.empty((ne,ny));AY=np.empty((ne,ny));DEE=np.empty((ne,ny));DEY=np.empty((ne,ny));DYY=np.empty((ne,ny))
    # Radial-orbit mu for the loss boundary.
    mu=np.empty(ne)
    for i,E in enumerate(s.E):
        ra,p0,g,den,rr,dr,v=radial_integrals(E)
        av,bp,bt=local_vcoeff(E,phi(rr),v,s.mass,fields)
        mu[i]=2*np.sum(THW*dr*rr*rr*bt/v)/(p0*s.jc2[i])
        for j,R in enumerate(s.R[i]):
            r,drr,vr,Q=s.orbits[i][j]
            vt2=Q/(r*r);v=np.sqrt(vr*vr+vt2)
            av,bp,bt=local_vcoeff(E,phi(r),v,s.mass,fields)
            ae=v*av+.5*(bp+bt);dee=v*v*bp
            aq=2*Q*av/v+r*r*(bt+(bp-.5*bt)*vt2/(v*v))
            dqq=4*r*r*Q*(.5*bt+(bp-.5*bt)*vt2/(v*v))
            deq=2*Q*bp
            h=s.jc2[i];a=s.ah[i];ap=s.ahp[i]
            ar=aq/h-R*a*ae+.5*R*(a*a-ap)*dee-a*deq/h
            drrc=dqq/(h*h)+R*R*a*a*dee-2*R*a*deq/h
            der=deq/h-R*a*dee
            # Orbit average, normalized by one-branch period integral.
            w=THW*drr/vr; norm=np.sum(w)
            ae0=np.sum(w*ae)/norm; de0=np.sum(w*dee)/norm
            ar0=np.sum(w*ar)/norm; dr0=np.sum(w*drrc)/norm; der0=np.sum(w*der)/norm
            l=s.loglc[i]; lp=s.lp[i];lpp=s.lpp[i]; yy=s.y[j]
            yE=(1-yy)*lp/l
            yR=-1/(R*l)
            yEE=(1-yy)*(lpp/l-2*(lp/l)**2)
            yER=lp/(R*l*l)
            yRR=1/(R*R*l)
            AE[i,j]=ae0;DEE[i,j]=max(de0,1e-300)
            AY[i,j]=yE*ae0+yR*ar0+.5*(yEE*de0+2*yER*der0+yRR*dr0)
            DEY[i,j]=yE*de0+yR*der0
            DYY[i,j]=max(yE*yE*de0+2*yE*yR*der0+yR*yR*dr0,1e-300)
    return AE,AY,DEE,DEY,DYY,mu

def line_operator(x, widths, A, D, sink_left=0.0):
    """Kramers--Moyal FV operator on a cell-density p(x)."""
    n=len(x);L=np.zeros((n,n))
    for i in range(n-1):
        dx=x[i+1]-x[i];af=.5*(A[i]+A[i+1]);df=max(.5*(D[i]+D[i+1]),1e-300)
        # F=A p - 1/2 d(Dp)/dx.  Set u=Dp and advect u with b=A/D.
        b=af/df; w=2*b*dx
        if abs(w)<1e-6:delta=.5-w/12
        elif w>50:delta=1/w
        elif w<-50:delta=1+1/w
        else:delta=1/w-1/np.expm1(w)
        cL=b*(1-delta)*D[i]+.5*D[i]/dx
        cR=b*delta*D[i+1]-.5*D[i+1]/dx
        L[i,i]-=cL/widths[i];L[i,i+1]-=cR/widths[i]
        L[i+1,i]+=cL/widths[i+1];L[i+1,i+1]+=cR/widths[i+1]
    L[0,0]-=sink_left
    return L

def boundary(s,mu,alpha):
    """Return first-cell removal coefficient and loss per unit E."""
    d=.5*s.dy
    # f_boundary = alpha/(alpha+L*d) f_center.
    fb_factor=alpha/(alpha+s.L*d)
    Cb=4*np.pi**2*s.jc2*s.p0
    losscoef=Cb*mu/(alpha+s.L*d) # loss/E divided by f_center
    sink=losscoef/(s.C[:,0]*s.dy)
    fcenter=s.p[:,0]/s.C[:,0]
    loss=losscoef*fcenter
    return sink,loss

def cross_rhs(s,p,Dxy):
    """Conservative mixed-diffusion term d_E d_y(D_Ey p)."""
    ne,ny=p.shape;z=Dxy*p;rhs=np.zeros_like(p)
    # Half of the mixed term through energy faces.
    zef=.5*(z[:-1]+z[1:])
    dzdy=np.gradient(zef,s.dy,axis=1,edge_order=2)
    fe=-.5*dzdy
    rhs[:-1]-=fe/s.dE[:-1,None];rhs[1:]+=fe/s.dE[1:,None]
    # The other half through angular-coordinate faces.
    zyf=.5*(z[:,:-1]+z[:,1:])
    dzde=np.empty_like(zyf)
    for j in range(ny-1):dzde[:,j]=np.gradient(zyf[:,j],s.E,edge_order=2)
    fy=-.5*dzde
    rhs[:,:-1]-=fy/s.dy;rhs[:,1:]+=fy/s.dy
    return rhs

def implicit_step(s,co,h,sink,use_cross=False):
    AE,AY,DEE,DEY,DYY,mu=co
    p=s.p;ne,ny=p.shape
    if use_cross:
        p=p+.5*h*cross_rhs(s,p,DEY)
    # Energy lines at fixed transformed angular coordinate.
    for j in range(ny):
        L=line_operator(s.E,s.dE,AE[:,j],DEE[:,j])
        p[:,j]=np.linalg.solve(np.eye(ne)-h*L,p[:,j])
    # Angular lines.  The boundary radiation loss is part of this solve.
    yw=np.full(ny,s.dy)
    for i in range(ne):
        L=line_operator(s.y,yw,AY[i],DYY[i],sink[i])
        p[i]=np.linalg.solve(np.eye(ny)-h*L,p[i])
    if use_cross:
        p=p+.5*h*cross_rhs(s,p,DEY)
    s.p=np.maximum(p,0)

def run(FH=.02,nE=32,nY=20,tend=12000,dt=5,ce=5,out=None,use_cross=False,adaptive=False):
    L=Grid2D('L',ML,RL,nE,nY,adaptive);H=Grid2D('H',MH,RH,nE,nY,adaptive)
    L.p=(1-FH)*L.C*L.fshape;H.p=FH*H.C*H.fshape
    L.p0dist=L.p.copy();H.p0dist=H.p.copy();species=[L,H]
    t=0.;step=0; rec={k:[] for k in ['t','rL','rH','NH','NL','seg']}
    coL=coH=None
    while t<tend-1e-10:
        if step%ce==0:
            fields=field_data(species)
            coL=coeff2d(L,fields);coH=coeff2d(H,fields)
            qL=L.p0*coL[-1]/L.Rlc;qH=H.p0*coH[-1]/H.Rlc
            aL=xi_alpha(np.maximum(qL,1e-14));aH=xi_alpha(np.maximum(qH,1e-14))
            skL,lsL=boundary(L,coL[-1],aL);skH,lsH=boundary(H,coH[-1],aH)
            rL=np.sum(lsL*L.dE)/ML;rH=np.sum(lsH*H.dE)/MH
        rec['t'].append(t);rec['rL'].append(rL);rec['rH'].append(rH)
        rec['NH'].append(H.number());rec['NL'].append(L.number());rec['seg'].append(H.inner_number()/L.inner_number())
        h=min(dt,tend-t)
        implicit_step(L,coL,h,skL,use_cross);implicit_step(H,coH,h,skH,use_cross)
        t+=h;step+=1
        if step%max(1,int(500/dt))==0:
            print('2D FH',FH,'t',t,'rate',rL,rH,'N',L.number(),H.number(),'seg',rec['seg'][-1],flush=True)
    fields=field_data(species);coL=coeff2d(L,fields);coH=coeff2d(H,fields)
    aL=xi_alpha(np.maximum(L.p0*coL[-1]/L.Rlc,1e-14));aH=xi_alpha(np.maximum(H.p0*coH[-1]/H.Rlc,1e-14))
    _,lsL=boundary(L,coL[-1],aL);_,lsH=boundary(H,coH[-1],aH)
    rec['t'].append(t);rec['rL'].append(np.sum(lsL*L.dE)/ML);rec['rH'].append(np.sum(lsH*H.dE)/MH)
    rec['NH'].append(H.number());rec['NL'].append(L.number());rec['seg'].append(H.inner_number()/L.inner_number())
    for k in rec:rec[k]=np.array(rec[k])
    rec['NH0']=np.sum(H.p0dist*H.dE[:,None])*H.dy/MH
    rec['NL0']=np.sum(L.p0dist*L.dE[:,None])*L.dy/ML
    if out:np.savez(out,**rec)
    return rec

def summary(d):
    t=d['t'];rL=d['rL'];rH=d['rH'];
    z=np.where((t>=100)&(t<=5000))[0];i=z[np.argmax(rL[z])]
    z=np.where(t>=100)[0];j=z[np.argmax(rH[z])]
    ids=np.where(d['NH']<=.5*d['NH0'])[0]
    th=np.nan
    if len(ids):
        k=ids[0];th=np.interp(.5*d['NH0'],[d['NH'][k],d['NH'][k-1]],[t[k],t[k-1]])
    return {'ndotL_max':rL[i],'t_ndotL_max':t[i],'ndotH_max':rH[j],
            't_half_H':th,'seg_max':np.max(d['seg'][t>0]),
            'rate_ratio_1e4':np.interp(1e4,t,rH)/np.interp(1e4,t,rL),'F_H_star':.008}

if __name__=='__main__':
    import argparse
    a=argparse.ArgumentParser();a.add_argument('--fh',type=float,default=.02);a.add_argument('--ne',type=int,default=28)
    a.add_argument('--ny',type=int,default=18);a.add_argument('--tend',type=float,default=12000);a.add_argument('--dt',type=float,default=5)
    a.add_argument('--ce',type=int,default=5);a.add_argument('--out',default=OUT+'/series2d.npz')
    a.add_argument('--cross',action='store_true');a.add_argument('--adaptive',action='store_true');x=a.parse_args()
    d=run(x.fh,x.ne,x.ny,x.tend,x.dt,x.ce,x.out,x.cross,x.adaptive);ans=summary(d);print(json.dumps(ans,indent=2))
    # Only write a complete result; long depletion outputs are filled by later continuation runs.
    if abs(x.fh-.02)<1e-12 and np.isfinite(ans['t_half_H']):save_answer(ans)
