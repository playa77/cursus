"""Execution counts are operator configuration, never account-pool size."""
from cursus.contracts import Problem

PROVIDERS = ('claude', 'codex', 'agy')
LANES = ('worker', *PROVIDERS, 'pi', 'verifier', 'repository')


def validate_capacity(value):
    expected = {'worker', *PROVIDERS, 'pi', 'verifier', 'repository'}
    if not isinstance(value, dict) or set(value) != expected:
        raise Problem('invalid_config', 'Capacity requires worker, claude, codex, agy, pi, verifier and repository.')
    for key, number in value.items():
        maximum = 4 if key == 'worker' else 2 if key in PROVIDERS else 1
        if type(number) is not int or not 1 <= number <= maximum:
            raise Problem('invalid_config', f'{key} capacity must be between 1 and {maximum}.')
    return dict(value)


def lane(job):
    if job['slot'] == 'frontier':
        return job['invocation']['role']['cli']
    return job['slot']


def fixture_capacity():
    """Only in-process compatibility fixtures; deployed configs have no defaults."""
    return dict(worker=2, claude=1, codex=1, agy=1, pi=1, verifier=1, repository=1)
