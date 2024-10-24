#!/usr/bin/env python

import numpy as np
import ufl
from scipy.special import zeta
from scipy.optimize import fsolve
from dolfinx import fem, geometry
from petsc4py import PETSc
from Generate_Mesh import *

'''
This code is made for DOLFINx version 0.5.1.
'''

freq = 2*10**9
kwargs_data = {"freq" : freq, "h" : 0.5*np.sqrt((1/2**3)**2 * (10**9/(2*10**9))**3), "quad" : True, "char_len" : True, "s" : 0.2, "K" : 100, "data" : True}
kwargs_inv = {"freq" : freq, "h" : np.sqrt((1/2**3)**2 * (10**9/freq)**3), "char_len" : True, "s" : 0.2, "K" : 100, "M" : 1000, "data" : False}

def u_i(kappa_0, n_out, alpha_out, dir, x): # Amplitude of incoming wave
    return np.e**(complex(0,1)*kappa_0*np.sqrt(n_out/alpha_out)*(dir[0]*x[0] + dir[1]*x[1]))


def u_in(kappa_0, n_out, alpha_out, dir, x): # Radial normal derivative of u_i
        return complex(0,1)*kappa_0*np.sqrt(n_out/alpha_out)*(x[0]*dir[0] + x[1]*dir[1])*np.e**(complex(0,1)*kappa_0*np.sqrt(n_out/alpha_out)*(dir[0]*x[0] + dir[1]*x[1]))/np.sqrt(x[0]**2+x[1]**2)


def sigma(sigma_PML, R_tilde, R_PML, rho):
    return sigma_PML*np.minimum(np.maximum((rho - R_tilde)/(R_PML - R_tilde), 0), 1)


def sigma_bar(sigma_PML, R_tilde, R_PML, rho):
    return sigma_PML*(rho - R_tilde)**2/(2*rho*(R_PML - R_tilde))*(R_tilde <= rho)*(rho <= R_PML) + sigma_PML*(-(R_PML + R_tilde)/(2*rho) + 1)*(R_PML < rho)


def d(sigma_PML, R_tilde, R_PML, freq, rho):
    return 1 + complex(0,1)*sigma(sigma_PML, R_tilde, R_PML, rho)/(2*np.pi*freq)


def d_bar(sigma_PML, R_tilde, R_PML, freq, rho):
    return 1 + complex(0,1)*sigma_bar(sigma_PML, R_tilde, R_PML, rho)/(2*np.pi*freq)


def Axx(sigma_PML, R_tilde, R_PML, freq, x):
    rho, phi = np.sqrt(x[0]**2 + x[1]**2), np.arctan2(x[1], x[0])
    d_rho, d_bar_rho = d(sigma_PML, R_tilde, R_PML, freq, rho), d_bar(sigma_PML, R_tilde, R_PML, freq, rho)
    return d_bar_rho/d_rho*np.cos(phi)**2 + d_rho/d_bar_rho*np.sin(phi)**2


def Axy(sigma_PML, R_tilde, R_PML, freq, x):
    rho, phi = np.sqrt(x[0]**2 + x[1]**2), np.arctan2(x[1], x[0])
    d_rho, d_bar_rho = d(sigma_PML, R_tilde, R_PML, freq, rho), d_bar(sigma_PML, R_tilde, R_PML, freq, rho)
    return (d_bar_rho/d_rho - d_rho/d_bar_rho)*np.cos(phi)*np.sin(phi)


def Ayy(sigma_PML, R_tilde, R_PML, freq, x):
    rho, phi = np.sqrt(x[0]**2 + x[1]**2), np.arctan2(x[1], x[0])
    d_rho, d_bar_rho = d(sigma_PML, R_tilde, R_PML, freq, rho), d_bar(sigma_PML, R_tilde, R_PML, freq, rho)
    return d_rho/d_bar_rho*np.cos(phi)**2 + d_bar_rho/d_rho*np.sin(phi)**2
    

def build_PML(sigma_PML, R_tilde, R_PML, freq, Q, V): # Perfectly Matching Layer
    a11    = fem.Function(Q)
    a12    = fem.Function(Q)
    a22    = fem.Function(Q)
    dd_bar = fem.Function(V)
    a11.interpolate(lambda x: Axx(sigma_PML, R_tilde, R_PML, freq, x))
    a12.interpolate(lambda x: Axy(sigma_PML, R_tilde, R_PML, freq, x))
    a22.interpolate(lambda x: Ayy(sigma_PML, R_tilde, R_PML, freq, x))
    dd_bar.interpolate(lambda x: d(sigma_PML, R_tilde, R_PML, freq, np.sqrt(x[0]**2 + x[1]**2))*d_bar(sigma_PML, R_tilde, R_PML, freq, np.sqrt(x[0]**2 + x[1]**2)))
    return ufl.as_matrix([[a11,a12], [a12,a22]]), dd_bar
    

def radial(r0, char_len, s, epsilon, J, sum, Y, phi):
    if char_len == True:
        return np.sum(np.array([(Y[2*j-2]*np.cos(j*phi) + Y[2*j-1]*np.sin(j*phi))/(1 + s*j**(2 + epsilon)) for j in range(1, J+1)]), axis=0)*r0/(4*sum)
    else:
        return np.sum(np.array([(Y[2*j-2]*np.cos(j*phi) + Y[2*j-1]*np.sin(j*phi))/(j**(2 + epsilon)) for j in range(1, J+1)]), axis=0)*r0/(4*sum)


def der_radial_x(r0, char_len, s, epsilon, J, sum, Y, x, rho, phi):
    if char_len == True:
        return np.sum(np.array([(Y[2*j-2]*np.sin(j*phi) - Y[2*j-1]*np.cos(j*phi))*j/(1 + s*j**(2 + epsilon)) for j in range(1, J+1)]), axis=0)*x[1]/rho**2*r0/(4*sum)
    else:
        return np.sum(np.array([(Y[2*j-2]*np.sin(j*phi) - Y[2*j-1]*np.cos(j*phi))*j/(j**(2 + epsilon)) for j in range(1, J+1)]), axis=0)*x[1]/rho**2*r0/(4*sum)


def der_radial_y(r0, char_len, s, epsilon, J, sum, Y, x, rho, phi):
    if char_len == True:
        return np.sum(np.array([(Y[2*j-2]*np.sin(j*phi) - Y[2*j-1]*np.cos(j*phi))*j/(1 + s*j**(2 + epsilon)) for j in range(1, J+1)]), axis=0)*-x[0]/rho**2*r0/(4*sum)
    else:
        return np.sum(np.array([(Y[2*j-2]*np.sin(j*phi) - Y[2*j-1]*np.cos(j*phi))*j/(j**(2 + epsilon)) for j in range(1, J+1)]), axis=0)*-x[0]/rho**2*r0/(4*sum)


def mollifier_1(r0, rho): # Mollifier for r0/4 \leq \rho \leq r0
    return (4*rho - r0)/(3*r0)


def mollifier_2(R, r0, rho): # Mollifier for r0 \leq \rho \leq R
    return (R - rho)/(R - r0)


def Jacxx(R, r0, x, rho, radial_Y, der_radial_x_Y):
    return 1 + (4*x[0]/(3*r0*rho)*x[0]/rho*radial_Y + mollifier_1(r0, rho)*x[1]**2/rho**3*radial_Y + mollifier_1(r0, rho)*x[0]/rho*der_radial_x_Y)*(r0/4 < rho)*(rho <= r0) + (-x[0]/((R - r0)*rho)*x[0]/rho*radial_Y + mollifier_2(R, r0, rho)*x[1]**2/rho**3*radial_Y + mollifier_2(R, r0, rho)*x[0]/rho*der_radial_x_Y)*(r0 < rho)*(rho <= R)


def Jacxy(R, r0, x, rho, radial_Y, der_radial_y_Y):
    return (4*x[1]/(3*r0*rho)*x[0]/rho*radial_Y - mollifier_1(r0, rho)*x[0]*x[1]/rho**3*radial_Y + mollifier_1(r0, rho)*x[0]/rho*der_radial_y_Y)*(r0/4 < rho)*(rho <= r0) + (-x[1]/((R - r0)*rho)*x[0]/rho*radial_Y - mollifier_2(R, r0, rho)*x[0]*x[1]/rho**3*radial_Y + mollifier_2(R, r0, rho)*x[0]/rho*der_radial_y_Y)*(r0 < rho)*(rho <= R)


def Jacyx(R, r0, x, rho, radial_Y, der_radial_x_Y):
    return (4*x[0]/(3*r0*rho)*x[1]/rho*radial_Y - mollifier_1(r0, rho)*x[0]*x[1]/rho**3*radial_Y + mollifier_1(r0, rho)*x[1]/rho*der_radial_x_Y)*(r0/4 < rho)*(rho <= r0) + (-x[0]/((R - r0)*rho)*x[1]/rho*radial_Y - mollifier_2(R, r0, rho)*x[0]*x[1]/rho**3*radial_Y + mollifier_2(R, r0, rho)*x[1]/rho*der_radial_x_Y)*(r0 < rho)*(rho <= R)


def Jacyy(R, r0, x, rho, radial_Y, der_radial_y_Y):
    return 1 + (4*x[1]/(3*r0*rho)*x[1]/rho*radial_Y + mollifier_1(r0, rho)*x[0]**2/rho**3*radial_Y + mollifier_1(r0, rho)*x[1]/rho*der_radial_y_Y)*(r0/4 < rho)*(rho <= r0) + (-x[1]/((R - r0)*rho)*x[1]/rho*radial_Y + mollifier_2(R, r0, rho)*x[0]**2/rho**3*radial_Y + mollifier_2(R, r0, rho)*x[1]/rho*der_radial_y_Y)*(r0 < rho)*(rho <= R)


def alpha_hatxx(R, r0, char_len, s, epsilon, J, sum, Y, x):
    rho, phi = np.sqrt(x[0]**2 + x[1]**2), np.arctan2(x[1], x[0])
    radial_Y, der_radial_x_Y, der_radial_y_Y = radial(r0, char_len, s, epsilon, J, sum, Y, phi), der_radial_x(r0, char_len, s, epsilon, J, sum, Y, x, rho, phi), der_radial_y(r0, char_len, s, epsilon, J, sum, Y, x, rho, phi)
    Jac00, Jac01, Jac10, Jac11 = Jacxx(R, r0, x, rho, radial_Y,der_radial_x_Y), Jacxy(R, r0, x, rho, radial_Y, der_radial_y_Y), Jacyx(R, r0, x, rho, radial_Y, der_radial_x_Y), Jacyy(R, r0, x, rho, radial_Y, der_radial_y_Y)
    return (Jac01**2 + Jac11**2)/(Jac00*Jac11 - Jac01*Jac10)


def alpha_hatxy(R, r0, char_len, s, epsilon, J, sum, Y, x):
    rho, phi = np.sqrt(x[0]**2 + x[1]**2), np.arctan2(x[1], x[0])
    radial_Y, der_radial_x_Y, der_radial_y_Y = radial(r0, char_len, s, epsilon, J, sum, Y, phi), der_radial_x(r0, char_len, s, epsilon, J, sum, Y, x, rho, phi), der_radial_y(r0, char_len, s, epsilon, J, sum, Y, x, rho, phi)
    Jac00, Jac01, Jac10, Jac11 = Jacxx(R, r0, x, rho, radial_Y,der_radial_x_Y), Jacxy(R, r0, x, rho, radial_Y, der_radial_y_Y), Jacyx(R, r0, x, rho, radial_Y, der_radial_x_Y), Jacyy(R, r0, x, rho, radial_Y, der_radial_y_Y)
    return (-(Jac00*Jac01 + Jac10*Jac11))/(Jac00*Jac11 - Jac01*Jac10)


def alpha_hatyy(R, r0, char_len, s, epsilon, J, sum, Y, x):
    rho, phi = np.sqrt(x[0]**2 + x[1]**2), np.arctan2(x[1], x[0])
    radial_Y, der_radial_x_Y, der_radial_y_Y = radial(r0, char_len, s, epsilon, J, sum, Y, phi), der_radial_x(r0, char_len, s, epsilon, J, sum, Y, x, rho, phi), der_radial_y(r0, char_len, s, epsilon, J, sum, Y, x, rho, phi)
    Jac00, Jac01, Jac10, Jac11 = Jacxx(R, r0, x, rho, radial_Y,der_radial_x_Y), Jacxy(R, r0, x, rho, radial_Y, der_radial_y_Y), Jacyx(R, r0, x, rho, radial_Y, der_radial_x_Y), Jacyy(R, r0, x, rho, radial_Y, der_radial_y_Y)
    return (Jac00**2 + Jac10**2)/(Jac00*Jac11 - Jac01*Jac10)


def kappa_sqrd_trans(R, r0, char_len, s, epsilon, J, sum, Y, x):
    rho, phi = np.sqrt(x[0]**2 + x[1]**2), np.arctan2(x[1], x[0])
    radial_Y, der_radial_x_Y, der_radial_y_Y = radial(r0, char_len, s, epsilon, J, sum, Y, phi), der_radial_x(r0, char_len, s, epsilon, J, sum, Y, x, rho, phi), der_radial_y(r0, char_len, s, epsilon, J, sum, Y, x, rho, phi)
    Jac00, Jac01, Jac10, Jac11 = Jacxx(R, r0, x, rho, radial_Y,der_radial_x_Y), Jacxy(R, r0, x, rho, radial_Y, der_radial_y_Y), Jacyx(R, r0, x, rho, radial_Y, der_radial_x_Y), Jacyy(R, r0, x, rho, radial_Y, der_radial_y_Y)
    return Jac00*Jac11 - Jac01*Jac10


def build_mapping(R, r0, char_len, s, epsilon, J, sum, Q, Y): # Coordinate mapping
    alpha_hat00    = fem.Function(Q)
    alpha_hat01    = fem.Function(Q)
    alpha_hat11    = fem.Function(Q)
    kappa_sqrd_hat = fem.Function(Q)
    alpha_hat00.interpolate(lambda x: alpha_hatxx(R, r0, char_len, s, epsilon, J, sum, Y, x))
    alpha_hat01.interpolate(lambda x: alpha_hatxy(R, r0, char_len, s, epsilon, J, sum, Y, x))
    alpha_hat11.interpolate(lambda x: alpha_hatyy(R, r0, char_len, s, epsilon, J, sum, Y, x))
    kappa_sqrd_hat.interpolate(lambda x: kappa_sqrd_trans(R, r0, char_len, s, epsilon, J, sum, Y, x))
    return ufl.as_matrix([[alpha_hat00,alpha_hat01], [alpha_hat01, alpha_hat11]]), kappa_sqrd_hat


def Phi_inv(R, r0, char_len, s, epsilon, J, sum, Y, x):
    rho, phi = np.sqrt(x[0]**2 + x[1]**2), np.arctan2(x[1], x[0])
    rad_phys = r0 + radial(r0, char_len, s, epsilon, J, sum, Y, phi)
        
    rho_hat  = np.zeros(rho.shape)
    rho_hat += (rho <= r0/4) * rho
    rho_hat += (r0/4 < rho)  * (rho <= rad_phys) * r0*(3*rho + rad_phys - r0)/(4*rad_phys - r0)
    rho_hat += (rad_phys  < rho)  * (rho <= R)   * (rho*(R - r0) - R*(rad_phys - r0))/(R - rad_phys)
    rho_hat += (R < rho)     * rho
    return np.array([rho_hat*np.cos(phi), rho_hat*np.sin(phi)])


def get_J(**kwargs):
    epsilon  = kwargs["epsilon"]  if "epsilon"  in kwargs else 0.001 # Small number greater than zero for convergence of radius expansion
    char_len = kwargs["char_len"] if "char_len" in kwargs else False # Determines type of expansion
    s        = kwargs["s"]        if "s"        in kwargs else 0.001 # Scaled version of correlation length
    
    if char_len == True:
        sum = np.sum(np.array([1/(1 + s*k**(2 + epsilon)) for k in range(1, 1000000)]))

        var_sum = np.sum(np.array([1/((1 + s*k**(2 + epsilon))**2) for k in range(1, 1000000)]))
        sum_j, j = 0, 0
        while sum_j < 0.95*var_sum:
            j += 1
            sum_j += 1/((1 + s*j**(2 + epsilon))**2)
        J = j
        
    else:
        sum = zeta(2 + epsilon)
        var_sum = zeta(2*(2 + epsilon))
        sum_j, j = 0, 0
        while sum_j < 0.95*var_sum:
            j += 1
            sum_j += 1/(j**(2*(2 + epsilon)))
        J = j
    return J
    



alpha_in  = kwargs_data["alpha_in"]  if "alpha_in"  in kwargs_data else 1   # Material constant inside scatterer
alpha_out = kwargs_data["alpha_out"] if "alpha_out" in kwargs_data else 1   # Material constant outside scatterer
n_in      = kwargs_data["n_in"]      if "n_in"      in kwargs_data else 0.9 # Refractive index inside scatterer
n_out     = kwargs_data["n_out"]     if "n_out"     in kwargs_data else 1   # Refractive index ouside scatterer

dir  = kwargs_data["dir"]  if "dir"  in kwargs_data else np.array([1.0,0.0]) # Direction of propagation, norm should be 1
c    = kwargs_data["c"]    if "c"    in kwargs_data else 3*10**10            # Lightspeed in cm
freq = kwargs_data["freq"] if "freq" in kwargs_data else 10**9               # Frequency of incoming wave in dm
kappa_0 = 2*np.pi*freq/c

R_tilde   = kwargs_data["R_tilde"]   if "R_tilde"   in kwargs_data else 7.5          # Outer radius PML in cm
R_PML     = kwargs_data["R_PML"]     if "R_PML"     in kwargs_data else 11           # Outer radius PML in cm
sigma_PML = kwargs_data["sigma_PML"] if "sigma_PML" in kwargs_data else 10000        # Global demping parameter of PML layer
gdim      = kwargs_data["gdim"]      if "gdim"      in kwargs_data else 2            # Geometric dimension of the mesh

epsilon  = kwargs_data["epsilon"]  if "epsilon"  in kwargs_data else 0.001 # Small number greater than zero for convergence of radius expansion
char_len = kwargs_data["char_len"] if "char_len" in kwargs_data else False # Determines type of expansion
s        = kwargs_data["s"]        if "s"        in kwargs_data else 0.001 # Scaled version of correlation length

K            = kwargs_data["K"]            if "K"            in kwargs_data else 15  # Number of measured points
sigma_smooth = kwargs_data["sigma_smooth"] if "sigma_smooth" in kwargs_data else fsolve(lambda sigma: 1/(2*np.pi*sigma**2)*np.e**(-(0.5*np.sqrt((1/2**3)**2 * (10**9/(4*10**9))**3))**2/(2*sigma**2))-0.1, x0=0.1)[0]# the exponential is still 10% one characterstic length further


create_domain_data = Generate_Mesh(**kwargs_data)
domain_data, ct_data, ft_data = create_domain_data()

V_data = fem.FunctionSpace(domain_data, ("CG", 1)) # Solution space
Q_data = fem.FunctionSpace(domain_data, ("DG", 0)) # For discontinuous expressions

alpha_data      = fem.Function(Q_data)
kappa_sqrd_data = fem.Function(Q_data)

material_tags_data = np.unique(ct_data.values)
for tag in material_tags_data:
    cells = ct_data.find(tag)
    if tag == 1 or tag == 2 or tag == 3:
        alpha_data_ = alpha_out
        kappa_sqrd_data_ = kappa_0**2*n_out
    elif tag == 4 or tag == 5:
        alpha_data_ = alpha_in
        kappa_sqrd_data_ = kappa_0**2*n_in
    alpha_data.x.array[cells] = np.full_like(cells, alpha_data_, dtype=PETSc.ScalarType)
    kappa_sqrd_data.x.array[cells] = np.full_like(cells, kappa_sqrd_data_, dtype=PETSc.ScalarType)

bc_data = fem.dirichletbc(fem.Constant(domain_data, PETSc.ScalarType(0)), fem.locate_dofs_topological(V_data, gdim-1, ft_data.find(6)), V_data) # Set zero Dirichlet boundary condition at R_PML
u_i_boundary_data  = fem.Function(V_data)
dof_data = V_data.tabulate_dof_coordinates()[:, 0:2]
dofs_boundary_data   = fem.locate_dofs_topological(V_data, gdim-1, ft_data.find(8)) # Degrees of freedom at R
coords_boundary_data = domain_data.geometry.x[dofs_boundary_data]
values_boundary_data = u_i(kappa_0, n_out, alpha_out, dir, dof_data[dofs_boundary_data].transpose())
with u_i_boundary_data.vector.localForm() as loc:
        loc.setValues(dofs_boundary_data, values_boundary_data)
u_i_n_data = fem.Function(V_data)
u_i_n_data.interpolate(lambda x: u_in(kappa_0, n_out, alpha_out, dir, x))

dx_inner_data = ufl.Measure('dx', domain=domain_data, subdomain_data=ct_data, subdomain_id=3) # Integration on medium domain
dS_data       = ufl.Measure('dS', domain=domain_data, subdomain_data=ft_data, subdomain_id=8) # Surface integration at R

A_matrix_data, dd_bar_data = build_PML(sigma_PML, R_tilde, R_PML, freq, Q_data, V_data)

u_data = ufl.TrialFunction(V_data)
v_data = ufl.TestFunction(V_data)

solver_data = PETSc.KSP().create(domain_data.comm)
solver_data.setType(PETSc.KSP.Type.PREONLY)
solver_data.getPC().setType(PETSc.PC.Type.LU)

L_data = alpha_data('+')*ufl.inner(u_i_n_data, v_data)('+')*dS_data - alpha_data*ufl.inner(ufl.grad(u_i_boundary_data), ufl.grad(v_data))*dx_inner_data + kappa_sqrd_data*ufl.inner(u_i_boundary_data, v_data)*dx_inner_data
b_data = fem.petsc.assemble_vector(fem.form(L_data))
b_data.assemble()
fem.petsc.set_bc(b_data, [bc_data])


create_domain_inv = Generate_Mesh(**kwargs_inv)
domain_inv, ct_inv, ft_inv = create_domain_inv()

V_inv = fem.FunctionSpace(domain_inv, ("CG", 1))
Q_inv = fem.FunctionSpace(domain_inv, ("DG", 0))

alpha_inv      = fem.Function(Q_inv)
kappa_sqrd_inv = fem.Function(Q_inv)

material_tags_inv = np.unique(ct_inv.values)
for tag in material_tags_inv:
    cells = ct_inv.find(tag)
    if tag == 1 or tag == 2 or tag == 3:
        alpha_inv_ = alpha_out
        kappa_sqrd_inv_ = kappa_0**2*n_out
    elif tag == 4 or tag == 5:
        alpha_inv_ = alpha_in
        kappa_sqrd_inv_ = kappa_0**2*n_in
    alpha_inv.x.array[cells] = np.full_like(cells, alpha_inv_, dtype=PETSc.ScalarType)
    kappa_sqrd_inv.x.array[cells] = np.full_like(cells, kappa_sqrd_inv_, dtype=PETSc.ScalarType)

bc_inv = fem.dirichletbc(fem.Constant(domain_inv, PETSc.ScalarType(0)), fem.locate_dofs_topological(V_inv, gdim-1, ft_inv.find(6)), V_inv) # Set zero Dirichlet boundary condition at R_PML
u_i_boundary_inv  = fem.Function(V_inv)
dof_inv = V_inv.tabulate_dof_coordinates()[:, 0:2]
dofs_boundary_inv    = fem.locate_dofs_topological(V_inv, gdim-1, ft_inv.find(8)) # Degrees of freedom at R
coords_boundary_inv  = domain_inv.geometry.x[dofs_boundary_inv]
values_boundary_inv  = u_i(kappa_0, n_out, alpha_out, dir, dof_inv[dofs_boundary_inv].transpose())
with u_i_boundary_inv.vector.localForm() as loc:
        loc.setValues(dofs_boundary_inv, values_boundary_inv)
u_i_n_inv = fem.Function(V_inv)
u_i_n_inv.interpolate(lambda x: u_in(kappa_0, n_out, alpha_out, dir, x))

dx_inner_inv = ufl.Measure('dx', domain=domain_inv, subdomain_data=ct_inv, subdomain_id=3) # Integration on medium domain
dS_inv       = ufl.Measure('dS', domain=domain_inv, subdomain_data=ft_inv, subdomain_id=8) # Surface integration at R

A_matrix_inv, dd_bar_inv = build_PML(sigma_PML, R_tilde, R_PML, freq, Q_inv, V_inv)

u_inv = ufl.TrialFunction(V_inv)
v_inv = ufl.TestFunction(V_inv)

solver_inv = PETSc.KSP().create(domain_inv.comm)
solver_inv.setType(PETSc.KSP.Type.PREONLY)
solver_inv.getPC().setType(PETSc.PC.Type.LU)

L_inv = alpha_inv('+')*ufl.inner(u_i_n_inv, v_inv)('+')*dS_inv - alpha_inv*ufl.inner(ufl.grad(u_i_boundary_inv), ufl.grad(v_inv))*dx_inner_inv + kappa_sqrd_inv*ufl.inner(u_i_boundary_inv, v_inv)*dx_inner_inv
b_inv = fem.petsc.assemble_vector(fem.form(L_inv))
b_inv.assemble()
fem.petsc.set_bc(b_inv, [bc_inv])

if char_len == True:
    sum = np.sum(np.array([1/(1 + s*k**(2 + epsilon)) for k in range(1, 1000000)]))

    var_sum = np.sum(np.array([1/((1 + s*k**(2 + epsilon))**2) for k in range(1, 1000000)]))
    sum_j, j = 0, 0
    while sum_j < 0.95*var_sum:
        j += 1
        sum_j += 1/((1 + s*j**(2 + epsilon))**2)
    J = j
    
else:
    sum = zeta(2 + epsilon)
    var_sum = zeta(2*(2 + epsilon))
    sum_j, j = 0, 0
    while sum_j < 0.95*var_sum:
        j += 1
        sum_j += 1/(j**(2*(2 + epsilon)))
    J = j

angles_meas = np.array([i for i in range(K)])/K*2*np.pi
    
    
def forward_observation(Y, **kwargs):    
    alpha_out = kwargs["alpha_out"] if "alpha_out" in kwargs else 1   # Material constant outside scatterer
    n_out     = kwargs["n_out"]     if "n_out"     in kwargs else 1   # Refractive index ouside scatterer

    dir  = kwargs["dir"]  if "dir"  in kwargs else np.array([1.0,0.0]) # Direction of propagation, norm should be 1
    c    = kwargs["c"]    if "c"    in kwargs else 3*10**10            # Lightspeed in cm
    freq = kwargs["freq"] if "freq" in kwargs else 10**9               # Frequency of incoming wave in dm
    kappa_0 = 2*np.pi*freq/c

    r0        = kwargs["r0"]        if "r0"        in kwargs else 1            # Radius of reference configuration in cm (scaling because of numerical underflow)
    r1        = kwargs["r1"]        if "r1"        in kwargs else 6            # Radius of measured points in physical domain in dm, must be greater than 1.5*r0, smaller than R
    R         = kwargs["R"]         if "R"         in kwargs else 7            # Radius of coordinate transformation domain D_R in cm
    
    epsilon  = kwargs["epsilon"]  if "epsilon"  in kwargs else 0.001 # Small number greater than zero for convergence of radius expansion
    char_len = kwargs["char_len"] if "char_len" in kwargs else False # Determines type of expansion
    s        = kwargs["s"]        if "s"        in kwargs else 0.001 # Scaled version of correlation length
    
    data     = kwargs["data"] if "data" in kwargs else False

    if "data" == True:
      uh_data = fem.Function(V_data)
      alpha_hat_data, kappa_sqrd_hat_data = build_mapping(R, r0, char_len, s, epsilon, J, sum, Q_data, Y)
  
      a_data = ufl.inner(alpha_data*alpha_hat_data*A_matrix_data*ufl.grad(u_data), ufl.grad(v_data))*ufl.dx - ufl.inner(kappa_sqrd_data*kappa_sqrd_hat_data*dd_bar_data*u_data, v_data)*ufl.dx
      bilinear_form_data = fem.form(a_data)
      A_data = fem.petsc.assemble_matrix(bilinear_form_data, bcs=[bc_data])
      A_data.assemble()
          
      solver_data.setOperators(A_data)
      solver_data.solve(b_data, uh_data.vector)
  
      # Observation operator
      measurement_points =  np.array([r1*np.cos(angles_meas), r1*np.sin(angles_meas)])
      ref_measurement_points = Phi_inv(R, r0, char_len, s, epsilon, J, sum, Y, measurement_points)
      measurement_values = []
      
      ui_data = fem.Function(V_data)
      ui_data.interpolate(lambda x: u_i(kappa_0, n_out, alpha_out, dir, x))
      
      for k in range(len(angles_meas)):
          smoothing_data = fem.Function(V_data)
          smoothing_data.interpolate(lambda x: 1/(2*np.pi*sigma_smooth**2)*np.e**(-((x[0] - ref_measurement_points[0,k])**2 + (x[1] - ref_measurement_points[1,k])**2)/(2*sigma_smooth**2)))
          measurement_value = fem.form(ufl.inner((uh_data - ui_data), smoothing_data*kappa_sqrd_hat_data) * ufl.dx)
          measurement_value_local = fem.assemble_scalar(measurement_value)
          measurement_value_global = (domain_data.comm.allreduce(measurement_value_local, op=MPI.SUM))
          measurement_values.append(np.real(measurement_value_global))
  
    else:
      uh_inv = fem.Function(V_inv)
      alpha_hat_inv, kappa_sqrd_hat_inv = build_mapping(R, r0, char_len, s, epsilon, J, sum, Q_inv, Y)
  
      a_inv = ufl.inner(alpha_inv*alpha_hat_inv*A_matrix_inv*ufl.grad(u_inv), ufl.grad(v_inv))*ufl.dx - ufl.inner(kappa_sqrd_inv*kappa_sqrd_hat_inv*dd_bar_inv*u_inv, v_inv)*ufl.dx
      bilinear_form_inv = fem.form(a_inv)
      A_inv = fem.petsc.assemble_matrix(bilinear_form_inv, bcs=[bc_inv])
      A_inv.assemble()
          
      solver_inv.setOperators(A_inv)
      solver_inv.solve(b_inv, uh_inv.vector)
  
      # Observation operator
      measurement_points =  np.array([r1*np.cos(angles_meas), r1*np.sin(angles_meas)])
      ref_measurement_points = Phi_inv(R, r0, char_len, s, epsilon, J, sum, Y, measurement_points)
      measurement_values = []
      
      ui_inv = fem.Function(V_inv)
      ui_inv.interpolate(lambda x: u_i(kappa_0, n_out, alpha_out, dir, x))
      
      for k in range(len(angles_meas)):
          smoothing_inv = fem.Function(V_inv)
          smoothing_inv.interpolate(lambda x: 1/(2*np.pi*sigma_smooth**2)*np.e**(-((x[0] - ref_measurement_points[0,k])**2 + (x[1] - ref_measurement_points[1,k])**2)/(2*sigma_smooth**2)))
          measurement_value = fem.form(ufl.inner((uh_inv - ui_inv), smoothing_inv*kappa_sqrd_hat_inv) * ufl.dx)
          measurement_value_local = fem.assemble_scalar(measurement_value)
          measurement_value_global = (domain_inv.comm.allreduce(measurement_value_local, op=MPI.SUM))
          measurement_values.append(np.real(measurement_value_global))
    return np.array(measurement_values)