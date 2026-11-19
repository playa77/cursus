"""Pure milestone availability and transition decisions (single package M1)."""

from cursus.contracts import Problem


def admitted(value):
    if (value['workflow'] != 'code' or value['source']['kind'] == 'interview'
            or value['plan_debate'] or value['spec_debate']):
        raise Problem('unsupported_milestone', 'This workflow requires a later milestone.')


def decide(snapshot, change):
    """Select the first immutable repository step; extended by WP-08."""
    if change['kind'] != 'submit':
        raise Problem('unsupported_milestone', 'Action requires a later milestone.')
    value = change['input']
    admitted(value)
    return {'state': 'intake', 'step': 'resolve_input', 'slot': 'repository',
            'input': {'repo': value['repo'], 'source': value['source']}}
