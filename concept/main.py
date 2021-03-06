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
# The author of CO𝘕CEPT can be contacted at dakin(at)phys.au.dk
# The latest version of CO𝘕CEPT is available at
# https://github.com/jmd-dk/concept/



# Import everything from the commons module.
# In the .pyx file, Cython declared variables will also get cimported.
from commons import *

# Cython imports
import interactions
cimport('from analysis import debug, measure, powerspec')
cimport('from graphics import render, terminal_render')
cimport('from integration import cosmic_time,          '
        '                        expand,               '
        '                        hubble,               '
        '                        initiate_time,        '
        '                        scalefactor_integral, '
        )
cimport('from interactions import find_interactions')
cimport('from snapshot import load, save')
cimport('from species import Component, get_representation')
cimport('from utilities import delegate')




# Function that computes several time integrals with integrands having
# to do with the scale factor (e.g. ∫dta⁻¹).
# The result is stored in ᔑdt_steps[integrand][index],
# where index == 0 corresponds to step == 'first half' and
# index == 1 corresponds to step == 'second half'. 
@cython.header(# Arguments
               step='str',
               Δt='double',
               # Locals
               a_next='double',
               go2dump='bint',
               index='int',
               integrand='object',  # str or tuple
               t_dump='double',
               t_next='double',
               )
def scalefactor_integrals(step, Δt):
    global ᔑdt_steps
    # Update the scale factor and the cosmic time. This also
    # tabulates a(t), needed for the scalefactor integrals.
    # If the dump time is within reach, go directly to this time
    go2dump = False
    t_dump = next_dump[1]
    if universals.t + 0.5*Δt + 1e-3*Δt > t_dump:
        # Dump time will be rached by a time step of 0.5*Δt
        # (or at least be so close that it is better to include the
        # last little bit). Go exactly to this dump time.
        go2dump = True
        Δt = 2*(t_dump - universals.t)
    # Find a_next = a(t_next) and tabulate a(t)
    t_next = universals.t + 0.5*Δt
    a_next = expand(universals.a, universals.t, 0.5*Δt)
    if go2dump and next_dump[0] == 'a':
        # This will not change a_next by much. We do it to ensure
        # agreement with future floating point comparisons.
        a_next = next_dump[2]
    # Update the universal scale factor and cosmic time
    universals.a, universals.t = a_next, t_next
    # Map the step string to the index integer
    if step == 'first half':
        index = 0
    elif step == 'second half':
        index = 1
    elif master:
        abort('The value "{}" was given for the step'.format(step))
    # Do the scalefactor integrals
    for integrand in ᔑdt_steps:
        ᔑdt_steps[integrand][index] = scalefactor_integral(integrand)

# Function which dump all types of output. The return value signifies
# whether or not something has been dumped.
@cython.pheader(# Arguments
                components='list',
                output_filenames='dict',
                final_render='tuple',
                op='str',
                do_autosave='bint',
                # Locals
                do_dump='bint',
                filename='str',
                future_output_times='dict',
                ot='double',
                output_kind='str',
                output_time='tuple',
                present='double',
                time_param='str',
                time_val='double',
                returns='bint',
                )
def dump(components, output_filenames, final_render, op=None, do_autosave=False):
    global i_dump, dumps, next_dump, autosave_filename
    # Do nothing further if not at dump time
    # and no autosaving should be performed.
    do_dump = (   (next_dump[0] == 'a' and universals.a == next_dump[2])
               or (next_dump[0] == 't' and universals.t == next_dump[1])
               )
    if not do_dump and not do_autosave:
        return False
    # Synchronize drift and kick operations before dumping
    if op == 'drift':
        drift(components, 'first half')
    elif op == 'kick':
        kick(components, 'second half')
    # Do autosaving
    if not autosave_filename:
        autosave_filename = '{}/autosave_{}'.format(paths['ics_dir'], jobid)
    if do_autosave:
        # Save snapshot
        autosave_filename = save(components, autosave_filename)
        # Save parameter file corresponding to the snapshot
        if master:
            with open(autosave_params_filename, 'w', encoding='utf-8') as autosave_params_file:
                # Header
                autosave_params_file.write('# This parameter file is the result '
                                           'of an autosave of job {},\n'
                                           '# using the parameter file "{}".\n'
                                           '# The following is a copy of this '
                                           'original parameter file.\n\n'
                                           .format(jobid, paths['params'])
                                           )
                # Original paramter file
                autosave_params_file.write(params_file_content)
                autosave_params_file.write('\n'*2)
                # IC snapshot
                autosave_params_file.write('# The autosaved snapshot file was saved to\n'
                                           'initial_conditions = "{}"\n'.format(autosave_filename)
                                           )
                # Present time
                autosave_params_file.write('# The autosave happened at\n')
                if enable_Hubble:
                    autosave_params_file.write('a_begin = {:.12g}\n'.format(universals.a))
                else:
                    autosave_params_file.write('t_begin = {:.12g}*{}\n'
                                               .format(universals.t, unit_time))
                # Future output times
                future_output_times = {'a': {}, 't': {}}
                for time_param, present in zip(('a', 't'), (universals.a, universals.t)):
                    for output_kind, output_time in output_times[time_param].items():
                        future_output_times[time_param][output_kind] = [ot for ot in output_time
                                                                        if ot >= present]
                autosave_params_file.write('# Future output times\n')
                autosave_params_file.write('output_times = {}\n'.format(future_output_times))
    # If no output other than autosaves should be dumped,
    # return now.
    if not do_dump:
        return True
    # Dump terminal render
    for time_val, time_param in zip((universals.a, universals.t), ('a', 't')):
        if time_val in terminal_render_times[time_param]:
            terminal_render(components)
    # Dump snapshot
    for time_val, time_param in zip((universals.a, universals.t), ('a', 't')):
        if time_val in snapshot_times[time_param]:
            filename = output_filenames['snapshot'].format(time_param, time_val)
            if time_param == 't':
                filename += unit_time
            save(components, filename)
    # Dump power spectrum
    for time_val, time_param in zip((universals.a, universals.t), ('a', 't')):
        if time_val in powerspec_times[time_param]:
            filename = output_filenames['powerspec'].format(time_param, time_val)
            if time_param == 't':
                filename += unit_time
            powerspec(components, filename)
    # Dump render
    for time_val, time_param in zip((universals.a, universals.t), ('a', 't')):
        if time_val in render_times[time_param]:
            filename = output_filenames['render'].format(time_param, time_val)
            if time_param == 't':
                filename += unit_time
            render(components, filename, cleanup=((time_param, time_val) == final_render))
    # Increment dump time
    i_dump += 1
    if i_dump < len(dumps):
        next_dump = dumps[i_dump]
    else:
        # Last output have been dumped. Remove autosave files.
        if master:
            for filename in (autosave_filename, autosave_params_filename):
                if os.path.isfile(filename):
                    os.remove(filename)
    return True
cython.declare(autosave_filename='str',
               autosave_params_filename='str',
               )
autosave_filename = ''
autosave_params_filename = '{}/autosave_{}.params'.format(paths['params_dir'], jobid)

@cython.header(# Locals
               integrand='object',  # str or tuple
               index='int',
               )
def nullify_ᔑdt_steps():
    # Reset (nullify) the ᔑdt_steps, making the next kick operation
    # apply for only half a step, even though 'whole' is used.
    for integrand in ᔑdt_steps:
        for index in range(2):
            ᔑdt_steps[integrand][index] = 0

# Function which kick all of the components.
# Here a 'kick' means all interactions together with other source terms
# for fluid components.
@cython.header(# Arguments
               components='list',
               step='str',
               # Locals
               component='Component',
               force='str',
               integrand='object',  # str or tuple
               interactions_list='list',
               method='str',
               receivers='list',
               suppliers='list',
               ᔑdt='dict',
               )
def kick(components, step):
    # Construct the local dict ᔑdt,
    # based on which type of step is to be performed.
    ᔑdt = {}
    for integrand in ᔑdt_steps:
        if step == 'first half':
            ᔑdt[integrand] = ᔑdt_steps[integrand][0]
        elif step == 'second half':
            ᔑdt[integrand] = ᔑdt_steps[integrand][1]
        elif step == 'whole':
            ᔑdt[integrand] = np.sum(ᔑdt_steps[integrand])
        elif master:
            abort('The value "{}" was given for the step'.format(step))
    # Apply the effect of all internal source terms
    # on all fluid components. For particle components, this is a no-op.
    for component in components:
        component.apply_internal_sources(ᔑdt)
    # Find out which components interact with each other
    # under the different interactions.
    interactions_list = find_interactions(components)
    # Invoke each interaction sequentially
    for force, method, receivers, suppliers in interactions_list:
        getattr(interactions, force)(method, receivers, suppliers, ᔑdt)

# Function which drift all of the components
@cython.header(# Arguments
               components='list',
               step='str',
               # Locals
               ᔑdt='dict',
               integrand='object',  # str or tuple
               component='Component',
               )
def drift(components, step):
    # Construct the local dict ᔑdt,
    # based on which type of step is to be performed.
    ᔑdt = {}
    for integrand in ᔑdt_steps:
        if step == 'first half':
            ᔑdt[integrand] = ᔑdt_steps[integrand][0]
        elif step == 'second half':
            ᔑdt[integrand] = ᔑdt_steps[integrand][1]
        elif step == 'whole':
            ᔑdt[integrand] = np.sum(ᔑdt_steps[integrand])
        elif master:
            abort('The value "{}" was given for the step'.format(step))
    # Drift all components sequentially
    for component in components:
        component.drift(ᔑdt)

# Function containing the main time loop of CO𝘕CEPT
@cython.header(# Locals
               autosave_time='double',
               bottleneck='str',
               component='Component',
               components='list',
               do_autosave='bint',
               final_render='tuple',
               output_filenames='dict',
               timespan='double',
               time_step='Py_ssize_t',
               Δt='double',
               Δt_begin='double',
               Δt_max_increase_fac='double',
               Δt_new='double',
               Δt_period='Py_ssize_t',
               )
def timeloop():
    global ᔑdt_steps, i_dump, next_dump
    # Do nothing if no dump times exist
    if not (  [nr for val in output_times['a'].values() for nr in val]
            + [nr for val in output_times['t'].values() for nr in val]):
        return
    # Determine and set the correct initial values for the cosmic time
    # universals.t and the scale factor a(universals.t) = universals.a.
    initiate_time()
    # Get the output filename patterns, the final render time and
    # the total timespan of the simulation.
    # This also creates the global list "dumps".
    output_filenames, final_render, timespan = prepare_output_times()   
    # Get the initial components. These may be loaded from a snapshot
    # or generated on the fly.
    components = get_initial_conditions()
    if not components:
        return
    # The number of time steps before Δt is updated.
    # Setting Δt_period = 8 prevents the formation of spurious
    # anisotropies when evolving fluids with the MacCormack method,
    # as each of the 8 flux directions are then used with the same
    # time step size.
    Δt_period = 8
    # The maximum allowed fractional increase in Δt,
    # from one time step to the next.
    Δt_max_increase_fac = 5e-3
    # Give the initial time step the largest allowed value
    Δt_begin, bottleneck = reduce_Δt(components, ထ, ထ, timespan, worry=False)
    Δt = Δt_begin
    # Arrays which will store the two values
    # ∫_t^(t + Δt/2) integrand(a) dt
    # ∫_(t + Δt/2)^(t + Δt) integrand(a) dt
    ᔑdt_steps = {'1'  : zeros(2, dtype=C2np['double']),
                 'a⁻¹': zeros(2, dtype=C2np['double']),
                 'a⁻²': zeros(2, dtype=C2np['double']),
                 }
    for component in components:
        ᔑdt_steps['a⁻³ʷ'       , component] = zeros(2, dtype=C2np['double'])
        ᔑdt_steps['a⁻³ʷ⁻¹'     , component] = zeros(2, dtype=C2np['double'])
        ᔑdt_steps['a³ʷ⁻²'      , component] = zeros(2, dtype=C2np['double'])
        ᔑdt_steps['a⁻³ʷw/(1+w)', component] = zeros(2, dtype=C2np['double'])
        ᔑdt_steps['a³ʷ⁻²(1+w)' , component] = zeros(2, dtype=C2np['double'])
        ᔑdt_steps['ẇ/(1+w)'    , component] = zeros(2, dtype=C2np['double'])
        ᔑdt_steps['ẇlog(a)'    , component] = zeros(2, dtype=C2np['double'])
    # Specification of first dump and a corresponding index
    i_dump = 0
    next_dump = dumps[i_dump]
    # Possibly output at the beginning of simulation
    dump(components, output_filenames, final_render)
    # Return now if all dumps lie at the initial time
    if i_dump == len(dumps):
        return
    # Record what time it is, for use with autosaving
    autosave_time = time()
    # The main time loop
    masterprint('Beginning of main time loop')
    time_step = -1
    while i_dump < len(dumps):
        time_step += 1
        # Reduce time step size if it is larger than what is allowed
        Δt, bottleneck = reduce_Δt(components, Δt, Δt_begin, timespan)
        # Print out message at beginning of each time step
        print_timestep_heading(time_step, Δt, bottleneck, components)
        # Analyze and print out debugging information, if required
        debug(components)
        # Kick.
        # Even though 'whole' is used, the first kick (and the first
        # kick after a dump) is really only half a step (the first
        # half), as ᔑdt_steps[integrand][1] == 0 for every integrand.
        scalefactor_integrals('first half', Δt)
        kick(components, 'whole')
        do_autosave = bcast(autosave > 0 and (time() - autosave_time) > ℝ[autosave/units.s])
        if dump(components, output_filenames, final_render, 'drift', do_autosave):
            # Restart autosave schedule
            if do_autosave:
                autosave_time = time()
            # Reset the ᔑdt_steps, starting the leapfrog cycle anew
            nullify_ᔑdt_steps()
            continue
        # Increase the time step size after a full time step size period
        if not (time_step % Δt_period):
            # Let the drift operation catch up to the kick operation
            drift(components, 'first half')
            # New, bigger time step size, according to Δt ∝ a
            Δt_new = universals.a*ℝ[Δt_begin/a_begin]
            if Δt_new < Δt:
                Δt_new = Δt
            # Add small, constant contribution to the new time step size
            Δt_new += ℝ[exp(Δt_period*Δt_max_increase_fac)*Δt_begin]
            # Make sure that the relative change
            # of the time step size is not too big.
            if  Δt_new > ℝ[exp(Δt_period*Δt_max_increase_fac)]*Δt:
                Δt_new = ℝ[exp(Δt_period*Δt_max_increase_fac)]*Δt
            Δt = Δt_new
            # Reset the ᔑdt_steps, starting the leapfrog cycle anew
            nullify_ᔑdt_steps()
            continue
        # Drift
        scalefactor_integrals('second half', Δt)
        drift(components, 'whole')
        do_autosave = bcast(autosave > 0 and (time() - autosave_time) > ℝ[autosave/units.s])
        if dump(components, output_filenames, final_render, 'kick', do_autosave):
            # Restart autosave schedule
            if do_autosave:
                autosave_time = time()
            # Reset the ᔑdt_steps, starting the leapfrog cycle anew
            nullify_ᔑdt_steps()
            continue
    # All dumps completed; end of time loop
    masterprint('\nEnd of main time loop'
                + ('{:<' + ('14' if enable_Hubble else '13') + '} {} {}')
                   .format('\nCosmic time:',
                           significant_figures(universals.t, 4, fmt='Unicode'),
                           unit_time)
                + ('{:<14} {}'.format('\nScale factor:',
                                      significant_figures(universals.a, 4, fmt='Unicode'))
                   if enable_Hubble else '')
                )

# Function which prints out basic information
# about the current time step.
@cython.header(# Arguments
               time_step='Py_ssize_t',
               Δt='double',
               bottleneck='str',
               components='list',
               # Locals
               component='Component',
               i='Py_ssize_t',
               part='str',
               parts='list',
               width='Py_ssize_t',
               width_max='Py_ssize_t',
               )
def print_timestep_heading(time_step, Δt, bottleneck, components):
    global heading_ljust
    # Create list of text pieces. Left justify the first column
    # according to the global heading_ljust.
    parts = []
    parts.append(terminal.bold(f'\nTime step {time_step}'))
    parts.append('\n{}:'
                 .format('Cosmic time' if enable_Hubble else 'Time')
                 .ljust(heading_ljust)
                 )
    parts.append('{} {}'.format(significant_figures(universals.t, 4, fmt='unicode'),
                                unit_time,
                                ) 
                 )
    if enable_Hubble:
        parts.append('\nScale factor:'.ljust(heading_ljust))
        parts.append(significant_figures(universals.a, 4, fmt='unicode'))
    parts.append('\nStep size:'.ljust(heading_ljust))
    parts.append('{} {}{}'.format(significant_figures(Δt, 4, fmt='unicode'),
                                  unit_time,
                                  ' (limited by {})'.format(bottleneck) if bottleneck else '',
                                  )
                 )
    for component in components:
        if component.w_type != 'constant':
            parts.append('\nEoS ({}):'.format(component.name).ljust(heading_ljust))
            parts.append(significant_figures(component.w(), 4, fmt='unicode'))
    # Find the maximum width of the first column and left justify
    # the entire first colum to match this maximum width.
    if heading_ljust == 0:
        width_max = 0
        for part in parts:
            if part.endswith(':'):
                width = len(part)
                if width > width_max:
                    width_max = width
        heading_ljust = width_max + 1
        for i, part in enumerate(parts):
            if part.endswith(':'):
                parts[i] = part.ljust(heading_ljust)
    # Print out the combined heading
    masterprint(''.join(parts))
cython.declare(heading_ljust='Py_ssize_t')
heading_ljust = 0

# This function reduces the time step size Δt if it is too,
# based on a number of conditions.
@cython.header(# Arguments
               components='list',
               Δt='double',
               Δt_begin='double',
               timespan='double',
               worry='bint',
               # Locals
               H='double',
               J_over_ϱ_2_i='double',
               J_over_ϱ_2_max='double',
               Jx='double[:, :, :]',
               Jx_ijk='double',
               Jy='double[:, :, :]',
               Jy_ijk='double',
               Jz='double[:, :, :]',
               Jz_ijk='double',
               bottleneck='str',
               component='Component',
               dim='int',
               extreme_component='Component',
               fac_courant='double',
               fac_hubble='double',
               fac_dynamical='double',
               fac_reduce='double',
               fac_timespan='double',
               fac_ẇ='double',
               force='str',
               i='Py_ssize_t',
               j='Py_ssize_t',
               k='Py_ssize_t',
               limiters='list',
               method='str',
               mom2_i='double',
               mom2_max='double',
               momx='double*',
               momx_i='double',
               momy='double*',
               momy_i='double',
               momz='double*',
               momz_i='double',
               resolutions='list',
               v_max='double',
               w='double',
               Δt_courant='double',
               Δt_courant_component='double',
               Δt_hubble='double',
               Δt_dynamical='double',
               Δt_index='Py_ssize_t',
               Δt_min='double',
               Δt_max='double',
               Δt_ratio='double',
               Δt_ratio_abort='double',
               Δt_ratio_warn='double',
               Δt_suggestions='list',
               Δt_ẇ='double',
               Δt_ẇ_component='double',
               Δx_max='double',
               Σmass='double',
               ρ_bar='double',
               ϱ='double[:, :, :]',
               ϱ_ijk='double',
               returns='tuple',  # (Δt, bottleneck)
               )
def reduce_Δt(components, Δt, Δt_begin, timespan, worry=True):
    """This function computes the maximum allowed value of the
    time step size Δt. If the current value of Δt is greater than this,
    the returned value is the reduced Δt.
    The value of Δt should not be greater than the following:
    - A small fraction of the current dynamical time scale.
    - A small fraction of the current Hubble time
      (≃ present age of the universe), if Hubble expansion is enabled.
    - A small fraction of the total timespan of the simulation.
    - The largest Δt allowed by the momenta of the components.
      This amount to the Courant condition for fluids. A very analogous
      criterion is used for particles. Within this criterion,
      the maximum distance a particle is allowed to travel within a
      single time step is determined by the average inter-particle
      distance, or any "smallest scale" intrinsic to the forces acting
      on the particle species.
    - A small fraction of 1/abs(ẇ) for every fluid components,
      so that w varies smoothly.
    The conditions above are written in the same order in the code
    below. The last condition is by far the most involved.
    The optional worry argument flag specifies whether or not a
    drastic reduction in the time step size should trigger a warning
    (or even abort the program, for really drastic reductions).
    """
    # Ratios Δt_max_allowed/Δt, below which the program
    # will show a warning or abort, respectively.
    Δt_ratio_warn  = 0.5
    Δt_ratio_abort = 0.01
    # When reducing the time step, reduce it to this factor times
    # the maximally allowed time step size.
    fac_reduce = 0.95
    # Minimum allowed time step size.
    # If Δt needs to be lower than this, the program will terminate.
    Δt_min = 1e-4*Δt_begin
    # List which will store the maximum allowed Δt suggested by the
    # criteria stated above. The final maximum allowed Δt will be the
    # smallest of these.
    Δt_suggestions = []
    # List which will store the names of the different limiters
    # (reasons why Δt might need to be lowered).
    limiters = []
    # The maximum allowed time step size
    # suggested by the dynamical time scale.
    fac_dynamical = 8e-3
    if enable_Hubble:
        # When the Hubble expansion is enabled, 
        # use the current critical density as the mean density.
        H = hubble()
        ρ_bar = H**2*ℝ[Ωm*3/(8*π*G_Newton)]
    else:
        # In static space, determine the mean density
        # directly from the components.
        Σmass = 0
        for component in components:
            Σmass += measure(component, 'mass')
        ρ_bar = Σmass/boxsize**3
    Δt_dynamical = fac_dynamical/sqrt(G_Newton*ρ_bar)
    Δt_suggestions.append(Δt_dynamical)
    limiters.append('the dynamical timescale')
    # The maximum allowed time step size
    # suggested by the Hubble parameter.
    fac_hubble = 5e-2
    Δt_hubble = fac_hubble/H if enable_Hubble else ထ
    Δt_suggestions.append(Δt_hubble)
    limiters.append('the Hubble expansion')
    # The maximum allowed time step size
    # suggested by the simulation timespan.
    fac_timespan = 1e-1
    Δt_timespan = fac_timespan*timespan
    Δt_suggestions.append(Δt_timespan)
    limiters.append('the simulation timespan')
    # The maximum allowed time step size suggested by the Courant
    # condition. The maximum propagation speed of information in
    # comoving coordinates is
    # v_max = c*sqrt(w)/a + ẋ, ẋ = dx/dt = u/a,
    # where u is the peculiar velocity.
    # For fluids we have
    # ϱ = a**(3*(1 + w))*ρ, J = a**4*u*ρ, and so
    # u = a**(3*w - 1)*J/ϱ and then
    # v_max = c*sqrt(w)/a + J/(a**(2 - 3*w)*ϱ).
    # For particles we have w = 0 and ẋ = mom/(a**2*m), and so
    # v_max = mom/(a**2*mass).
    # The time step should not be allowed to be such that
    # v_max*Δt > Δx_max,
    # where Δx_max is the maximally allowed comoving distance a fluid
    # element or particle may travel in Δt time. This distance is set by
    # the grid resolutions of any forces acting on the components,
    # and also the resolution of the fluid grids for fluid components.
    fac_courant = 2e-1
    Δt_courant = ထ
    extreme_component = None
    for component in components:
        if component.representation == 'particles':
            # Maximum comoving distance a particle should be able to
            # travel in a single time step. This is set to be the
            # boxsize divided by the resolution, where each force
            # on the particles have their own resolution.
            # The number of particles is also used
            # as an addtional resolution.
            resolutions = [cbrt(component.N)]
            for force, method in forces.get(component.species, []):
                if force == 'gravity':
                    if method == 'pm':
                        resolutions.append(φ_gridsize)
                    elif method in ('pp', 'p3m'):
                        resolutions.append(1/component.softening)
            Δx_max = boxsize/np.max(resolutions)
            # Find maximum speed of particles
            mom2_max = 0
            momx = component.momx
            momy = component.momy
            momz = component.momz
            for i in range(component.N_local):
                momx_i = momx[i]
                momy_i = momy[i]
                momz_i = momz[i]
                mom2_i = momx_i**2 + momy_i**2 + momz_i**2
                if mom2_i > mom2_max:
                    mom2_max = mom2_i
            mom2_max = allreduce(mom2_max, op=MPI.MAX)
            v_max = sqrt(mom2_max)/(universals.a**2*component.mass)
        elif component.representation == 'fluid':
            # The maximum comoving distance a fluid element should be
            # able to communicate over in a single time step.
            # This is set to be the boxsize divided by the resolution,
            # where each force on the fluid have their own resolution.
            # The resolution of the fluid grids themselves is also used
            # as an addtional resolution.
            resolutions = [component.gridsize]
            for force, method in forces.get(component.species, []):
                if force == 'gravity':
                    if method == 'pm':
                        resolutions.append(φ_gridsize)
            Δx_max = boxsize/np.max(resolutions)
            # Find maximum speed of information
            J_over_ϱ_2_max = 0
            ϱ  = component.ϱ .grid_noghosts
            Jx = component.Jx.grid_noghosts
            Jy = component.Jy.grid_noghosts
            Jz = component.Jz.grid_noghosts
            for         i in range(ℤ[ϱ.shape[0] - 1]):
                for     j in range(ℤ[ϱ.shape[1] - 1]):
                    for k in range(ℤ[ϱ.shape[2] - 1]):
                        ϱ_ijk  = ϱ [i, j, k]
                        Jx_ijk = Jx[i, j, k]
                        Jy_ijk = Jy[i, j, k]
                        Jz_ijk = Jz[i, j, k]
                        J_over_ϱ_2_i = (Jx_ijk**2 + Jy_ijk**2 + Jz_ijk**2)/ϱ_ijk**2
                        if J_over_ϱ_2_i > J_over_ϱ_2_max:
                            J_over_ϱ_2_max = J_over_ϱ_2_i
            J_over_ϱ_2_max = allreduce(J_over_ϱ_2_max, op=MPI.MAX)
            w = component.w()
            v_max = light_speed*sqrt(w)/universals.a + universals.a**(3*w - 2)*sqrt(J_over_ϱ_2_max)
        # In the odd case of a completely static component,
        # set v_max to be just above 0.
        if v_max == 0:
            v_max = machine_ϵ
        # The 3D Courant condition
        Δt_courant_component = fac_courant*Δx_max/(sqrt(3)*v_max)
        # The component with the lowest value of the maximally allowed
        # time step size determines the global maximally allowed
        # time step size.
        if Δt_courant_component < Δt_courant:
            Δt_courant = Δt_courant_component
            extreme_component = component
    Δt_suggestions.append(Δt_courant)
    limiters.append('the Courant condition for {}'.format(extreme_component.name))
    # The maximum allowed time step size suggested by ẇ
    fac_ẇ = 1e-3
    Δt_ẇ = ထ
    extreme_component = None
    for component in components:
        Δt_ẇ_component = fac_ẇ/(abs(component.ẇ()) + machine_ϵ)
        if Δt_ẇ_component < Δt_ẇ:
            Δt_ẇ = Δt_ẇ_component
            extreme_component = component
    Δt_suggestions.append(Δt_ẇ)
    limiters.append('ẇ of {}'.format(extreme_component.name))
    # The maximum allowed time step satisfying all the conditions above
    Δt_index = np.argmin(Δt_suggestions)
    Δt_max = Δt_suggestions[Δt_index]
    # The name of the limiter with the smallest allowable Δt
    # will be given by the bottleneck variable.
    bottleneck = ''
    # Adjust the current time step size Δt if it greater than the
    # largest allowed value Δt_max.
    if Δt > Δt_max:
        bottleneck = limiters[Δt_index]
        # If Δt should be reduced by a lot, print out a warning
        # or even abort the program.
        if worry:
            # Note that the only condition for which the suggested
            # maximum Δt may fluctuate greatly is the Courant condition.
            # We therefore know for sure that if the time step size
            # needs to be dramatically decreased, it must be due to the
            # Courant condition.
            Δt_ratio = Δt_max/Δt
            if Δt_ratio < Δt_ratio_abort:
                abort('Due to {}, the time step size needs to be rescaled '
                      'by a factor {:.1g}. This extreme change is unacceptable.'
                      .format(bottleneck, Δt_ratio))
            if Δt_ratio < Δt_ratio_warn:
                masterwarn('Rescaling time step size by a factor {:.1g} due to {}.'
                           .format(Δt_ratio, bottleneck))
            # Abort if Δt becomes very small,
            # effectively halting further time evolution.
            if Δt_max < Δt_min:
                abort('Time evolution effectively halted with a time step size of {} {unit_time} '
                      '(originally the time step size was {} {unit_time})'
                      .format(Δt_max, Δt_begin, unit_time=unit_time)
                      )
        # Apply the update 
        Δt = fac_reduce*Δt_max
    return Δt, bottleneck

# Function that either loads existing initial conditions from a snapshot
# or produces the initial conditions itself.
@cython.header(# Locals
               N_or_gridsize='Py_ssize_t',
               abort_msg='str',
               component='Component',
               components='list',
               ic_isfile='bint',
               initial_conditions_generate='list',
               name='str',
               representation='str',
               speices='str',
               returns='list',
               )
def get_initial_conditions():
    # Parse the initial_conditions parameter
    if not initial_conditions:
        return
    abort_msg = (f'Error parsing initial_conditions = "{initial_conditions}". '
                  'This is neither an existing file nor a dict or container of dicts '
                  'specifying the initial components to generate.')
    ic_isfile = False
    if isinstance(initial_conditions, str):
        ic_isfile = bcast(os.path.isfile(initial_conditions) if master else None)
        if ic_isfile:
            # Initial condition snapshot is given. Load it.
            return load(sensible_path(initial_conditions), only_components=True)
    if not ic_isfile:
        # Components to realize are given.
        # Parse the specifications further.
        if isinstance(initial_conditions, (list, tuple)):
            initial_conditions_generate = []
            for d in initial_conditions:
                if not isinstance(d, dict):
                    abort(abort_msg)
                initial_conditions_generate.append(d.copy())
        elif isinstance(initial_conditions, dict):
            initial_conditions_generate = [initial_conditions.copy()]
        else:
            abort(abort_msg)
        # Instantiate and realize the specified components
        components = []
        for d in initial_conditions_generate:
            name = d.pop('name')
            species = d.pop('species')
            representation = get_representation(species)
            if 'N_or_gridsize' in d:
                N_or_gridsize = d.pop('N_or_gridsize')
                if 'N' in d:
                    masterwarn('Both N and N_or_gridsize specified '
                               f'for component "{name}". The value of N will be ignored.'
                               )
                if 'gridsize' in d:
                    masterwarn('Both gridsize and N_or_gridsize specified '
                               f'for component "{name}". The value of gridsize will be ignored.'
                               )
            elif 'N' in d:
                N_or_gridsize = d.pop('N')
                if 'gridsize' in d:
                    masterwarn('Both gridsize and N specified '
                               f'for component "{name}". The value of gridsize will be ignored.'
                               )
                if representation == 'fluid':
                    masterwarn(f'N = {N_or_gridsize} was specified '
                               f'for fluid component "{name}". This will be used as the gridsize.'
                               )
            elif 'gridsize' in d:
                N_or_gridsize = d.pop('gridsize')
                if representation == 'particles':
                    masterwarn(f'gridsize = {N_or_gridsize} was specified '
                               f'for particle component "{name}". This will be used as N.'
                               )
            else:
                if representation == 'particles':
                    abort(f'No N specified for "{name}"')
                elif representation == 'fluid':
                    abort(f'No gridsize specified for "{name}"')
            if 'w' in d:
                w = d.pop('w')
            else:
                w = 'class'            
            # Show a warning if not enough information is given to
            # construct the initial conditions.
            if species in ('neutrinos', 'neutrino fluid') and class_params.get('N_ncdm', 0) == 0:
                masterwarn('Component "{}" with species "{}" specified, '
                           'but the N_ncdm CLASS parameter is 0'.format(name, species))
            # Do the realization
            component = Component(name, species, N_or_gridsize, w=w, **d)
            component.realize()
            components.append(component)
        return components

# Function which checks the sanity of the user supplied output times,
# creates output directories and defines the output filename patterns.
# A Python function is used because it contains a closure
# (a lambda function).
def prepare_output_times():
    """As this function uses universals.t and universals.a as the
    initial values of the cosmic time and the scale factor, you must
    initialize these properly before calling this function.
    """
    global dumps
    # Check that the output times are legal
    if master:
        for time_param, at_begin in zip(('a', 't'), (universals.a, universals.t)):
            for output_kind, output_time in output_times[time_param].items():
                if output_time and np.min(output_time) < at_begin:
                    msg = ('Cannot produce a {} at {} = {:.6g}{}, '
                           'as the simulation starts at {} = {:.6g}{}.'
                           ).format(output_kind, time_param, np.min(output_time),
                                    (' ' + unit_time) if time_param == 't' else '',
                                    time_param, at_begin,
                                    (' ' + unit_time) if time_param == 't' else '')
                    abort(msg)
    # Create output directories if necessary
    if master:
        for time_param in ('a', 't'):
            for output_kind, output_time in output_times[time_param].items():
                # Do not create directory if this kind of output
                # should never be dumped to the disk.
                if not output_time or not output_kind in output_dirs:
                    continue
                # Create directory
                output_dir = output_dirs[output_kind]
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
    Barrier()
    # Construct the patterns for the output file names. This involves
    # determining the number of digits of the scalefactor in the output
    # filenames. There should be enough digits so that adjacent dumps do
    # not overwrite each other, and so that the name of the first dump
    # differs from that of the IC, should it use the same
    # naming convention.
    output_filenames = {}
    for time_param, at_begin in zip(('a', 't'), (universals.a, universals.t)):
        for output_kind, output_time in output_times[time_param].items():
            # This kind of output does not matter if
            # it should never be dumped to the disk.
            if not output_time or not output_kind in output_dirs:
                continue
            # Compute number of digits
            times = sorted(set((at_begin, ) + output_time))
            ndigits = 0
            while True:
                fmt = '{{:.{}f}}'.format(ndigits)
                if (len(set([fmt.format(ot) for ot in times])) == len(times)
                    and (fmt.format(times[0]) != fmt.format(0) or not times[0])):
                    break
                ndigits += 1
            fmt = '{{}}={}'.format(fmt)
            # Use the format (that is, either the format from the a
            # output times or the t output times) with the largest
            # number of digits.
            if output_kind in output_filenames:
                if int(re.search('[0-9]+',
                                 re.search('{.+?}',
                                           output_filenames[output_kind])
                                 .group()).group()) >= ndigits:
                    continue
            # Store output name patterns
            output_dir = output_dirs[output_kind]
            output_base = output_bases[output_kind]
            output_filenames[output_kind] = ('{}/{}{}'.format(output_dir,
                                                              output_base,
                                                              '_' if output_base else '')
                                             + fmt)
    # Lists of sorted dump times of both kinds
    a_dumps = sorted(set([nr for val in output_times['a'].values() for nr in val]))
    t_dumps = sorted(set([nr for val in output_times['t'].values() for nr in val]))
    # Both lists combined into one list of lists, the first ([1])
    # element of which are the cosmic time in both cases.
    dumps = [['a', -1, a] for a in a_dumps]
    a_lower = t_lower = machine_ϵ
    for i, d in enumerate(dumps):
        d[1] = cosmic_time(d[2], a_lower, t_lower)
        a_lower, t_lower = d[2], d[1]
    dumps += [['t', t] for t in t_dumps]
    # Sort the list according to the cosmic time
    dumps = sorted(dumps, key=(lambda d: d[1]))
    # It is possible for an a-time to have the same cosmic time value
    # as a t-time. This case should count as only a single dump time.
    for i, d in enumerate(dumps):
        if i + 1 < len(dumps) and d[1] == dumps[i + 1][1]:
            # Remove the t-time, leaving the a-time
            dumps.pop(i + 1)
    # The t-times for all dumps are now known. We can therefore
    # determine the total simulation time span.
    timespan = (dumps[len(dumps) - 1][1] - universals.t)
    # Determine the final render time (scalefactor or cosmic time).
    # Place the result in a tuple (eg. ('a', 1) or ('t', 13.7)).
    final_render = ()
    if render_times['t']:
        final_render_t = render_times['t'][len(render_times['t']) - 1]
        final_render = ('t', final_render_t)
    if render_times['a']:
        final_render_a = render_times['a'][len(render_times['a']) - 1]
        final_render_t = cosmic_time(final_render_a)
        if not final_render or (final_render and final_render_t > final_render[1]):
            final_render = ('a', final_render_t)
    return output_filenames, final_render, timespan

# Declare global variables used in above functions
cython.declare(ᔑdt_steps='dict',
               i_dump='Py_ssize_t',
               dumps='list',
               next_dump='list',
               )
if special_params:
    # Instead of running a simulation, run some utility
    # as defined by the special_params dict.
    delegate()
else:
    # Run the time loop
    timeloop()
    # Simulation done
    universals.any_warnings = allreduce(universals.any_warnings, op=MPI.LOR)
    if universals.any_warnings:
        masterprint('\nCO𝘕CEPT run finished')
    else:
        masterprint('\nCO𝘕CEPT run finished successfully', fun=terminal.bold_green)
# Shutdown CO𝘕CEPT properly
abort(exit_code=0)
