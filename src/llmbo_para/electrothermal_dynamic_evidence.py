"""Bounded evidence from actual postinitial observations, never new BO labels."""
import math


def dynamic_evidence_contract() -> dict:
    return {'version':'dynamic_residual_v1','sign_convention':'prediction_minus_observation',
        'origin':'same_rate_trace_time_s_index_zero_no_guess',
        'initial_rule':'exact_time_equal_to_simulation_start',
        'dynamic_rule':'observation_time_strictly_after_simulation_start',
        'dynamic_mean':'unweighted_sample_mean_of_all_postinitial_residuals',
        'display_selection':'all_if_n_le_8_else_floor_j_times_n_minus_1_over_7_j_0_to_7',
        'max_displayed_dynamic_samples':8,'display_significant_digits':8,'times':'unrounded_actual_observation_times',
        'limits':'not_time_integrals_slopes_extra_observations_or_optimization_objectives'}


def _origin(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        return None
    return float(value)


def dynamic_output_summary(output, *, simulation_start_s: float | None) -> dict:
    """Separate the actual initial residual from bounded postinitial evidence.

    Missing origin is unknown, not time zero. Display thinning never changes the
    all-dynamic sample mean, nor any objective or observation sampling grid.
    """
    if output.unit not in ('V','K'):
        raise ValueError('dynamic evidence requires normalized V or K without conversion')
    origin = _origin(simulation_start_s)
    try:
        sample_count = len(output.time_s)
    except TypeError as exc:
        if output.valid:
            raise ValueError('valid output has an invalid observation time grid') from exc
        sample_count = None
    result = {'output_valid':bool(output.valid),'unit':output.unit,'sample_count':sample_count,
        'simulation_start_s':origin,'status':'invalid_output','initial_residual':None,
        'dynamic_sample_count':None,'displayed_sample_count':0,'dynamic_sample_mean':None,'dynamic_samples':[]}
    if not output.valid:
        return result
    try:
        times = tuple(map(float,output.time_s)); observed = tuple(map(float,output.observed))
        predicted = tuple(map(float,output.predicted))
        if (not times or len(times)!=len(observed) or len(times)!=len(predicted)
                or any(not math.isfinite(v) for values in (times,observed,predicted) for v in values)
                or any(b<=a for a,b in zip(times,times[1:]))):
            raise ValueError('valid output has inconsistent dynamic evidence')
        residuals = tuple(p-o for p,o in zip(predicted,observed))
        if any(not math.isfinite(v) for v in residuals):
            raise ValueError('valid output has nonfinite residuals')
    except (TypeError,OverflowError) as exc:
        raise ValueError('valid output has inconsistent dynamic evidence') from exc
    if origin is None:
        result['status'] = 'origin_unavailable'
        return result
    if any(t<origin for t in times):
        raise ValueError('observation precedes the same-solve simulation origin')
    display = lambda value: float(format(value,'.8g'))
    dynamic = []
    for t,residual in zip(times,residuals):
        if t==origin:
            result['initial_residual'] = {'time_s':t,'residual':display(residual)}
        else:
            dynamic.append((t,residual))
    count = len(dynamic)
    result.update(status='dynamic' if count else 'initial_only',dynamic_sample_count=count)
    if count:
        try:
            average = math.fsum(v for _,v in dynamic)/count
        except OverflowError as exc:
            raise ValueError('dynamic residual mean is nonfinite') from exc
        if not math.isfinite(average):
            raise ValueError('dynamic residual mean is nonfinite')
        indices = range(count) if count<=8 else (j*(count-1)//7 for j in range(8))
        samples = [{'time_s':dynamic[i][0],'residual':display(dynamic[i][1])} for i in indices]
        result.update(dynamic_sample_mean=display(average),dynamic_samples=samples,displayed_sample_count=len(samples))
    return result


def dynamic_record_summary(record) -> dict:
    """Use each channel's original grid and only its same-rate trace index zero."""
    rows = {}
    for rate in record.rates:
        origin = None
        try:
            origin = rate.trace['time_s'][0]
        except (TypeError,KeyError,IndexError):
            pass
        rows[rate.rate] = {
            'voltage':dynamic_output_summary(rate.voltage,simulation_start_s=origin),
            'temperature':dynamic_output_summary(rate.cell_temperature,simulation_start_s=origin)}
    return rows
