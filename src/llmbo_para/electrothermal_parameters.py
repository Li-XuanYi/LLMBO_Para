"""Six optimization roles; fixed material properties are not hidden variables."""
ELECTROTHERMAL_NAMES=('eps_s_n','eps_s_p','D_s_n_ref','D_s_p_ref','C_th','G_th')
ELECTROTHERMAL_UNITS=('1','1','m2.s-1','m2.s-1','J.K-1','W.K-1')
PARAMETER_ROLES=dict(zip(ELECTROTHERMAL_NAMES,(
    'negative active material volume fraction','positive active material volume fraction',
    'negative solid diffusivity at reference temperature','positive solid diffusivity at reference temperature',
    'whole-cell heat capacity','effective thermal conductance to ambient')))
