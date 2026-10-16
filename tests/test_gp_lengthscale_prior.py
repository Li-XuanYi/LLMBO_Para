"""Density-measure, optional-prior, and legacy-posterior regression checks."""

import copy
import math

import numpy as np
import pytest

from llmbo_para.gp_prior import lengthscale_log_prior, normalize_lengthscale_prior
from llmbo_para.surrogate import Matern52GP


def prior(mu=None, sigma=math.sqrt(3.0)):
    return {"mu": [math.sqrt(2.0) + 0.5 * math.log(6.0)] * 6 if mu is None else mu,
            "sigma": sigma, "density_domain": "lengthscale", "bounds": [0.03, 8.0]}


def training_data():
    rng = np.random.default_rng(831)
    x = rng.uniform(0.1, 0.9, (9, 6))
    y = np.sin(3 * x[:, 0]) + 0.4 * x[:, 3]
    z = rng.uniform(0.1, 0.9, (3, 6))
    return x, y, z


def test_conditioned_lognormal_density_matches_hand_computation():
    p = prior(mu=[0.1, -0.2, 0.3, 0.4, -0.5, 0.6], sigma=[0.7, 0.8, 0.9, 1.0, 1.1, 1.2])
    ell = np.array([0.03, 0.1, 0.35, 1.0, 2.0, 8.0])
    expected = 0.0
    for value, mu, sigma in zip(ell, p["mu"], p["sigma"]):
        normal_cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
        mass = normal_cdf((math.log(8.0) - mu) / sigma) - normal_cdf((math.log(0.03) - mu) / sigma)
        density = math.exp(-0.5 * ((math.log(value) - mu) / sigma) ** 2)
        density /= value * sigma * math.sqrt(2 * math.pi) * mass
        expected += math.log(density)
    assert lengthscale_log_prior(np.log(ell), p) == pytest.approx(expected, abs=1e-12)


def test_density_matches_scipy_and_integrates_to_one():
    stats = pytest.importorskip("scipy.stats")
    integrate = pytest.importorskip("scipy.integrate")
    p = prior()
    mu, sigma = p["mu"][0], p["sigma"]
    distribution = stats.lognorm(s=sigma, scale=math.exp(mu))
    mass = distribution.cdf(8.0) - distribution.cdf(0.03)
    ell = np.array([0.04, 0.1, 0.35, 1.0, 2.0, 7.0])
    assert lengthscale_log_prior(np.log(ell), p) == pytest.approx(
        float(distribution.logpdf(ell).sum() - 6 * math.log(mass)), abs=1e-12)
    integral = integrate.quad(lambda v: math.exp(lengthscale_log_prior([math.log(v)] * 6, p) / 6),
                              0.03, 8.0)[0]
    assert integral == pytest.approx(1.0, abs=1e-9)


def test_density_mode_is_point_five_not_exp_mu():
    p = prior()
    mu, sigma = p["mu"][0], p["sigma"]
    mode = math.exp(mu - sigma * sigma)
    assert mode == pytest.approx(0.502, abs=0.001)
    assert math.exp(mu) == pytest.approx(10.075, abs=0.01)
    at_mode = lengthscale_log_prior([math.log(mode)] * 6, p)
    assert at_mode > lengthscale_log_prior([math.log(mode) - 0.01] * 6, p)
    assert at_mode > lengthscale_log_prior([math.log(mode) + 0.01] * 6, p)
    # Omitting -log(ell) would push this mode outside the search box.
    assert at_mode > lengthscale_log_prior([math.log(8.0)] * 6, p)


def test_normalization_uses_survival_function_in_positive_tail():
    p = prior(mu=[-12.0] * 6, sigma=1.0)
    assert math.isfinite(lengthscale_log_prior([math.log(0.04)] * 6, p))


@pytest.mark.parametrize("ell", [0.02, 8.1])
def test_prior_rejects_lengthscales_outside_search_support(ell):
    assert lengthscale_log_prior([math.log(ell)] * 6, prior()) == -math.inf


@pytest.mark.parametrize("change", [
    {"mu": [0.0] * 5}, {"mu": [math.nan] * 6}, {"sigma": 0.0},
    {"sigma": -1.0}, {"sigma": math.inf}, {"sigma": [1.0] * 5},
    {"density_domain": "log_lengthscale"}, {"bounds": [0.02, 8.0]},
    {"unknown_setting": True},
])
def test_prior_invalid_configuration_is_rejected(change):
    p = prior()
    p.update(change)
    with pytest.raises(ValueError):
        normalize_lengthscale_prior(p)


def test_density_measure_must_be_explicit():
    p = prior()
    del p["density_domain"]
    with pytest.raises(ValueError, match="density_domain"):
        normalize_lengthscale_prior(p)


def test_scalar_sigma_expands_and_neutral_shifts_are_identical():
    x, y, z = training_data()
    neutral = prior()
    shifted = prior(mu=(np.array(neutral["mu"]) + np.zeros(6)).tolist(), sigma=[neutral["sigma"]] * 6)
    assert normalize_lengthscale_prior(neutral) == normalize_lengthscale_prior(shifted)
    a = Matern52GP(max_sweeps=40, lengthscale_prior=neutral).fit(x, y)
    b = Matern52GP(max_sweeps=40, lengthscale_prior=shifted).fit(x, y)
    np.testing.assert_array_equal(a.params, b.params)
    np.testing.assert_array_equal(a.predict(z), b.predict(z))


def test_no_prior_reproduces_pre_change_numerical_snapshot():
    x, y, z = training_data()
    gp = Matern52GP(max_sweeps=12).fit(x, y)
    np.testing.assert_array_equal(gp.params, [-0.5998221244986779, 2.0794415416798357,
        2.0794415416798357, 1.2001778755013222, 2.0794415416798357,
        2.0794415416798357, -0.6, -7.10655789731998, 0.0])
    assert gp.marginal_log_likelihood == pytest.approx(7.890813668253331, abs=1e-12)
    np.testing.assert_allclose(gp.predict(z), [[0.6920619245630549, 1.3133414578902745,
        1.2271414554682003], [0.024414841717392645, 0.04567206454214715,
        0.04716196339029176]], rtol=0, atol=1e-12)
    assert gp.optimization_objective == gp.marginal_log_likelihood
    assert gp.log_prior == 0


def test_legacy_state_without_new_fields_retains_predictions():
    x, y, z = training_data()
    gp = Matern52GP(max_sweeps=12).fit(x, y, group=(0, 3))
    state = gp.state_dict()
    for name in ("lengthscale_prior", "initial_lengthscale", "log_prior", "optimization_objective"):
        del state[name]
    restored = Matern52GP.from_state(state)
    assert restored.lengthscale_prior is None
    np.testing.assert_array_equal(restored.predict(z), gp.predict(z))
    np.testing.assert_array_equal(restored.posterior_covariance(z), gp.posterior_covariance(z))


def test_weak_non_neutral_prior_changes_fit_and_roundtrips_posterior():
    x, y, z = training_data()
    neutral = prior()
    tilted = prior(mu=(np.array(neutral["mu"]) + np.array([-.5, .5, .5, -.5, .5, .5])).tolist())
    a = Matern52GP(max_sweeps=100, lengthscale_prior=neutral).fit(x, y)
    b = Matern52GP(max_sweeps=100, lengthscale_prior=tilted).fit(x, y)
    assert np.max(np.abs(a.params[:6] - b.params[:6])) > .02
    assert np.max(np.abs(a.predict(z)[0] - b.predict(z)[0])) > 1e-5
    assert b.marginal_log_likelihood == pytest.approx(b._mll(b.params), abs=1e-12)
    assert b.log_prior == pytest.approx(lengthscale_log_prior(b.params[:6], tilted), abs=1e-12)
    assert b.optimization_objective == pytest.approx(b.marginal_log_likelihood + b.log_prior, abs=1e-12)
    diagnostics = b.fit_diagnostics
    assert diagnostics["objective_name"] == "map_log_posterior"
    assert diagnostics["marginal_log_likelihood_trace"][-1] == b.marginal_log_likelihood
    assert diagnostics["objective_trace"][-1] == b.optimization_objective
    np.testing.assert_allclose(np.array(diagnostics["marginal_log_likelihood_trace"])
        + diagnostics["lengthscale_log_prior_trace"], diagnostics["objective_trace"], atol=1e-12)
    assert np.all(np.diff(diagnostics["objective_trace"]) >= -1e-10)
    restored = Matern52GP.from_state(b.state_dict())
    assert restored.state_dict() == b.state_dict()
    np.testing.assert_array_equal(restored.predict(z), b.predict(z))
    np.testing.assert_array_equal(restored.posterior_covariance(z), b.posterior_covariance(z))


@pytest.mark.parametrize("initial", [.1, .35, 1.0, [.1, .2, .3, .4, .5, .6]])
def test_initial_lengthscale_can_be_shared_across_comparison_arms(initial):
    x, y, _ = training_data()
    gp = Matern52GP(max_sweeps=0, initial_lengthscale=initial, lengthscale_prior=prior()).fit(x, y)
    np.testing.assert_allclose(np.exp(gp.params[:6]), initial, atol=1e-15)
    assert Matern52GP.from_state(gp.state_dict()).initial_lengthscale == initial


@pytest.mark.parametrize("initial", [0, .02, 8.1, math.nan, [1, 2], [1, 2, 3, 4, 5, math.inf]])
def test_initial_lengthscale_invalid_values_are_rejected(initial):
    x, y, _ = training_data()
    with pytest.raises(ValueError, match="initial_lengthscale"):
        Matern52GP(initial_lengthscale=initial).fit(x, y)


@pytest.mark.parametrize("group", [[0], [0, 3], list(range(6))])
def test_prior_cannot_be_combined_with_nonempty_group(group):
    x, y, _ = training_data()
    with pytest.raises(ValueError, match="full six-dimensional"):
        Matern52GP(lengthscale_prior=prior()).fit(x, y, group=group)


@pytest.mark.parametrize("bad_hyperparameters", [[0.0] * 8, [math.nan] * 9, [-5.0] * 9])
def test_from_state_rejects_bad_lengthscale_hyperparameters(bad_hyperparameters):
    x, y, _ = training_data()
    state = copy.deepcopy(Matern52GP(max_sweeps=0).fit(x, y).state_dict())
    state["hyperparameters"] = bad_hyperparameters
    with pytest.raises(ValueError):
        Matern52GP.from_state(state)
