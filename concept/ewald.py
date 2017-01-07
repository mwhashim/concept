# This file is part of CO𝘕CEPT, the cosmological 𝘕-body code in Python.
# Copyright © 2015-2017 Jeppe Mosgaard Dakin.
#
# CO𝘕CEPT is free software: You can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# CO𝘕CEPT is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with CO𝘕CEPT. If not, see http://www.gnu.org/licenses/
#
# The auther of CO𝘕CEPT can be contacted at dakin(at)phys.au.dk
# The latest version of CO𝘕CEPT is available at
# https://github.com/jmd-dk/concept/



# Import everything from the commons module.
# In the .pyx file, Cython declared variables will also get cimported.
from commons import *

# Cython imports
cimport('from mesh import CIC_vectorgrid2coordinates, tabulate_vectorfield')



# Cython function for computing Ewald correction
@cython.header(# Argument
               x='double',
               y='double',
               z='double',
               # Locals
               dim='Py_ssize_t',
               dist='double',
               dist_x='double',
               dist_y='double',
               dist_z='double',
               dist2='double',
               force='double*',
               force_x='double',
               force_y='double',
               force_z='double',
               kx='double',
               ky='double',
               kz='double',
               r3='double',
               scalarpart='double',
               sumindex_x='int',
               sumindex_y='int',
               sumindex_z='int',
               returns='double*',
               )
def summation(x, y, z):
    """ This function performs the Ewald summation given the distance
    x, y, z between two particles, normalized so that
    0 <= |x|, |y|, |z| < 1 (corresponding to boxsize = 1). The equation
    being solved corresponds to (8) in Ralf Klessen's 'GRAPESPH with
    Fully Periodic Boundary Conditions: Fragmentation of Molecular
    Clouds', though it is written without the normalization. The actual
    Ewald force is then given by force/boxsize**2. What is returned is
    the Ewald correction, corresponding to (9) in the mentioned paper.
    That is, the return value is not the total force, but the force from
    all particle images except the nearest one. Note that this nearest
    image need not be the actual particle.
    """
    # The Ewald force vector and its components
    force = vector
    force_x = force_y = force_z = 0
    # The image is on top of the particle: No force
    if x == 0 and y == 0 and z == 0:
        force[0] = 0
        force[1] = 0
        force[2] = 0
        return force
    # Remove the direct force, as we
    # are interested in the correction only
    r3 = (x**2 + y**2 + z**2)**1.5
    force_x += x/r3
    force_y += y/r3
    force_z += z/r3
    # The short range (real space) sum
    for sumindex_x in range(n_lower, n_upper):
        for sumindex_y in range(n_lower, n_upper):
            for sumindex_z in range(n_lower, n_upper):
                dist_x = x - sumindex_x
                dist_y = y - sumindex_y
                dist_z = z - sumindex_z
                dist2 = dist_x**2 + dist_y**2 + dist_z**2
                dist = sqrt(dist2)
                if dist > maxdist:
                    continue
                scalarpart = -dist**(-3)*(erfc(dist*ℝ[1/(2*rs)])
                                          + dist*ℝ[1/(sqrt(π)*rs)]*exp(dist2*ℝ[-1/(4*rs**2)]))
                force_x += dist_x*scalarpart
                force_y += dist_y*scalarpart
                force_z += dist_z*scalarpart
    # The long range (Fourier space) sum
    for sumindex_x in range(h_lower, h_upper):
        for sumindex_y in range(h_lower, h_upper):
            for sumindex_z in range(h_lower, h_upper):
                h2 = sumindex_x**2 + sumindex_y**2 + sumindex_z**2
                if h2 > maxh2 or h2 == 0:
                    continue
                kx = ℝ[2*π]*sumindex_x
                ky = ℝ[2*π]*sumindex_y
                kz = ℝ[2*π]*sumindex_z
                k2 = kx**2 + ky**2 + kz**2
                scalarpart = ℝ[-4*π]/k2*exp(-k2*ℝ[rs**2])*sin(kx*x + ky*y + kz*z)
                force_x += kx*scalarpart
                force_y += ky*scalarpart
                force_z += kz*scalarpart
    # Pack and return Ewald force
    force[0] = force_x
    force[1] = force_y
    force[2] = force_z
    return force

# Master function of this module. Returns the Ewald force correction.
@cython.header(# Arguments
               x='double',
               y='double',
               z='double',
               # Locals
               dim='Py_ssize_t',
               force='double*',
               isnegative_x='bint',
               isnegative_y='bint',
               isnegative_z='bint',
               r3='double',
               returns='double*',
               )
def ewald(x, y, z):
    """This function performs a look up of the Ewald correction to the
    fully periodic gravitational force (corresponding to 1/r²) on a
    particle due to some other particle at a position (x, y, z) relative
    to the first particle. It is important that the parsed coordinates
    are of the nearest periodic image of the other particle, and not
    necessarily of the particle itself. This means that
    0 <= |x|, |y|, |z| < boxsize/2. The returned value is thus the force
    arising on the first particle due to all periodic images of the
    second particle, except for the nearest one.
    """
    # Only the positive octant of the box is tabulated. Flip the sign of
    # the coordinates so that they reside inside this octant.
    if x > 0:
        isnegative_x = False
    else:
        x *= -1
        isnegative_x = True
    if y > 0:
        isnegative_y = False
    else:
        y *= -1
        isnegative_y = True
    if z > 0:
        isnegative_z = False
    else:
        z *= -1
        isnegative_z = True
    # Look up Ewald force and do a CIC interpolation. Since the
    # coordinates are to the nearest image, they must be scaled by
    # 2/boxsize to reside in the range 0 <= x, y, z < 1.
    force = CIC_vectorgrid2coordinates(grid, x*ℝ[2/boxsize],
                                             y*ℝ[2/boxsize],
                                             z*ℝ[2/boxsize],
                                       )
    # Put the sign back in for negative input
    if isnegative_x:
        force[0] *= -1
    if isnegative_y:
        force[1] *= -1
    if isnegative_z:
        force[2] *= -1
    # The tabulated force is for a unit box. Do rescaling
    for dim in range(3):
        force[dim] *= ℝ[1/boxsize**2]
    return force



# Set parameters for the Ewald summation at import time
cython.declare(h_lower='int',
               h_upper='int',
               maxdist='double',
               maxh2='double',
               n_lower='int',
               n_upper='int',
               rs='double',
               )
# The values chosen match those listed in the article mentioned in the
# docstring of the summation function. These are also those used
# (in effect) in GADGET2.
rs = 0.25  # Corresponds to alpha = 2
maxdist = 3.6
maxh2 = 10
# Derived constants
h_lower = int(-sqrt(maxh2))      # GADGET: -4 (same here for maxh2=10)
h_upper = int(+sqrt(maxh2)) + 1  # GADGET:  5 (same here for maxh2=10)
n_lower = int(-(maxdist + 1))    # GADGET: -4 (same here for maxdist=3.6)
n_upper = int(maxdist + 1) + 1   # GADGET:  5 (same here for maxdist=3.6) 

# Initialize the wald grid at import time,
# if Ewald summation is to be used.
cython.declare(i='int',
               p='str',
               filepath='str',
               grid='double[:, :, :, ::1]',
               )
if enable_Ewald:
    filepath = paths['concept_dir'] + '/' + ewald_file
    if os.path.isfile(filepath):
        # Ewald grid already tabulated. Load it
        with h5py.File(filepath,
                       mode='r',
                       driver='mpio',
                       comm=comm) as hdf5_file:
            grid = hdf5_file['data'][...].reshape([ewald_gridsize]*3 + [3])
    else:
        # No tabulated Ewald grid found. Compute it. The factor 0.5
        # ensures that only the first octant of the box is tabulated.
        masterprint('Tabulating Ewald grid of linear size',
                    ewald_gridsize, '...')
        grid = tabulate_vectorfield(ewald_gridsize,
                                    summation,
                                    0.5/(ewald_gridsize - 1),
                                    filepath)
        masterprint('done')

