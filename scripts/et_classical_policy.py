"""Official jMetalPy algorithms, isolated from the battery/LLM environment.

JSON lines on stdin/stdout are the only evaluator interface. The caller owns
physical validation, cached objectives, solve accounting and stopping evidence.
"""
import hashlib
import importlib.metadata
import inspect
import json
import math
from pathlib import Path
import random
import sys

METHODS = {'nsga2': 'jmetal.algorithm.multiobjective.nsgaii.NSGAII',
           'smpso': 'jmetal.algorithm.multiobjective.smpso.SMPSO'}


class EvaluationLimit(Exception):
    pass


class IncompletePair(Exception):
    pass


def install_restrictions():
    """Reject normal Python socket, child-process and PyBaMM operations."""
    def audit(event, args):
        if (event.startswith('socket.') or event == 'subprocess.Popen'
                or event == 'os.system' or event == 'import' and args[0].split('.')[0] == 'pybamm'):
            raise PermissionError('policy operation forbidden: '+event)
    sys.addaudithook(audit)


def run(spec, exchange):
    import numpy as np
    from jmetal.algorithm.multiobjective.nsgaii import NSGAII
    from jmetal.algorithm.multiobjective.smpso import SMPSO
    from jmetal.core.problem import FloatProblem
    from jmetal.core.solution import FloatSolution
    from jmetal.operator.crossover import SBXCrossover
    from jmetal.operator.mutation import PolynomialMutation
    from jmetal.util.archive import CrowdingDistanceArchive
    from jmetal.util.termination_criterion import TerminationCriterion

    method = spec['method']
    if method not in METHODS or type(spec['rounds']) is not int or spec['rounds'] < 1:
        raise ValueError('explicit method and positive new-evaluation count required')
    initial = spec['initial_x']
    if len(initial) != 16 or len({tuple(x) for x in initial}) != 16 or any(
            len(x) != 6 or any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in x) for x in initial):
        raise ValueError('six-dimensional unique sixteen-point initialization required')
    random.seed(spec['seed']); np.random.seed(spec['seed'])

    class Problem(FloatProblem):
        def __init__(self):
            super().__init__()
            self.lower_bound = [0.] * 6; self.upper_bound = [1.] * 6
            self.obj_directions = [self.MINIMIZE] * 2
            self.obj_labels = ['F_U_scaled', 'F_T_scaled']
            self.created = self.requests = self.new = 0

        def number_of_objectives(self): return 2
        def number_of_constraints(self): return 0
        def name(self): return 'external_two_error_evaluator'

        def create_solution(self):
            if self.created >= 16:
                raise ValueError('unexpected extra random initialization')
            solution = FloatSolution(self.lower_bound, self.upper_bound, 2, 0)
            solution.variables = list(initial[self.created]); self.created += 1
            return solution

        def evaluate(self, solution):
            if self.new >= spec['rounds']: raise EvaluationLimit
            if self.requests >= 16 + 128 * spec['rounds']:
                raise ValueError('proposal liveness guard exceeded')
            message = {'type': 'evaluate', 'ordinal': self.requests, 'x': list(solution.variables)}
            self.requests += 1
            response = exchange(message)
            if type(response.get('cached')) is not bool:
                raise ValueError('authoritative cache status required')
            if not response['cached']: self.new += 1
            if response.get('complete_pair_valid') is not True or response.get('objectives') is None:
                raise IncompletePair
            values = response['objectives']
            if len(values) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
                raise ValueError('finite true two-objective reply required')
            solution.objectives = list(values)
            return solution

    problem = Problem()

    class NewEvaluationStop(TerminationCriterion):
        def update(self, *args, **kwargs): pass
        @property
        def is_met(self): return problem.new >= spec['rounds']

    mutation = PolynomialMutation(probability=1/6, distribution_index=20)
    settings = {'population_size': 16, 'mutation_probability': 1/6, 'mutation_index': 20}
    if method == 'nsga2':
        settings.update(offspring_population_size=1, crossover_probability=.9, crossover_index=15)
        algorithm = NSGAII(problem=problem, population_size=16, offspring_population_size=1,
            mutation=mutation, crossover=SBXCrossover(probability=.9, distribution_index=15),
            termination_criterion=NewEvaluationStop())
    else:
        settings.update(leaders_archive_size=64, official_speed_and_perturbation_rules=True)
        algorithm = SMPSO(problem=problem, swarm_size=16, mutation=mutation,
            leaders=CrowdingDistanceArchive(64), termination_criterion=NewEvaluationStop())
    partial = False
    try:
        algorithm.run()
    except EvaluationLimit:
        partial = True
    source = Path(inspect.getfile(type(algorithm)))
    if problem.new != spec['rounds']: raise ValueError('new evaluation budget not completed')
    return {'type': 'completed', 'state': {'method': method, 'library_class': METHODS[method],
        'jmetalpy_version': importlib.metadata.version('jmetalpy'), 'algorithm_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'settings': settings, 'new_evaluations': problem.new, 'library_requests': problem.requests,
        'library_evaluations': algorithm.evaluations, 'partial_generation': partial}}


def main():
    spec = json.loads(sys.stdin.readline())
    def exchange(message):
        print(json.dumps(message, allow_nan=False), flush=True)
        line = sys.stdin.readline()
        if not line: raise ValueError('evaluator closed without feedback')
        return json.loads(line)
    try:
        message = run(spec, exchange); code = 0
    except Exception as exc:
        message = {'type': 'failed', 'reason': 'incomplete_objective_pair' if isinstance(exc, IncompletePair) else type(exc).__name__, 'detail': str(exc)}
        code = 1
    print(json.dumps(message, allow_nan=False), flush=True)
    return code


if __name__ == '__main__':
    import os
    for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'): os.environ[k] = '1'
    install_restrictions()
    code = main(); sys.stdout.flush(); sys.stderr.flush(); os._exit(code)
