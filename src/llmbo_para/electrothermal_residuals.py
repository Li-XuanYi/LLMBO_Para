"""Past-only directional curve evidence for Region, never extra BO objectives."""
import math


def residual_evidence_contract():
    return {'version': 'signed_residual_v1', 'sign_convention': 'prediction_minus_observation',
            'aggregation': 'unweighted_sample_mean_and_first_last_sample_quartile_means',
            'quartile_count': 'max(1,ceil(sample_count/4))', 'display_significant_digits': 8}


def signed_output_summary(output):
    if output.unit not in ('V', 'K'):
        raise ValueError('residual evidence requires normalized V or K; no unit conversion is performed')
    result = {'valid': bool(output.valid), 'unit': output.unit, 'sample_count': len(output.time_s),
              'signed_mean': None, 'early_signed_mean': None, 'late_signed_mean': None}
    if not output.valid:
        return result
    try:
        time = tuple(map(float, output.time_s)); observed = tuple(map(float, output.observed))
        predicted = tuple(map(float, output.predicted))
        if (not time or len(time) != len(observed) or len(time) != len(predicted)
                or any(not math.isfinite(v) for row in (time, observed, predicted) for v in row)
                or any(b <= a for a, b in zip(time, time[1:]))):
            raise ValueError('valid output has inconsistent residual evidence')
        residual = tuple(a-b for a, b in zip(predicted, observed))
        quarter = max(1, (len(residual)+3)//4)
        average = lambda values: float(format(math.fsum(values)/len(values), '.8g'))
        result.update(signed_mean=average(residual), early_signed_mean=average(residual[:quarter]),
                      late_signed_mean=average(residual[-quarter:]))
    except (TypeError, OverflowError) as exc:
        raise ValueError('valid output has inconsistent residual evidence') from exc
    return result


def signed_record_summary(record):
    return {row.rate: {'voltage': signed_output_summary(row.voltage),
                       'temperature': signed_output_summary(row.cell_temperature)} for row in record.rates}
