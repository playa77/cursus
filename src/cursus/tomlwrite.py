"""Minimal TOML writer for Cursus's own configuration shapes.

The standard library reads TOML but cannot write it, and a new dependency is not justified for
this schema: strings, integers, booleans, flat lists of those, nested tables and arrays of
tables. Anything else is refused rather than guessed at, so a value can never be written in a
form that the loader would read back differently (`tests/unit/test_tomlwrite.py` round-trips
the real shapes through `tomllib`).
"""
import re

BARE = re.compile(r'[A-Za-z0-9_-]+')
ESCAPES = {'"': '\\"', '\\': '\\\\', '\n': '\\n', '\r': '\\r', '\t': '\\t'}


def string(text):
    """A TOML basic string. Control characters and DEL are \\u-escaped; TOML forbids them raw."""
    out = ['"']
    for char in text:
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            raise ValueError('Lone surrogate cannot be written as TOML.')
        if char in ESCAPES:
            out.append(ESCAPES[char])
        elif code < 0x20 or code == 0x7F:
            out.append(f'\\u{code:04x}')
        else:
            out.append(char)
    out.append('"')
    return ''.join(out)


def key(name):
    if not isinstance(name, str) or not name:
        raise ValueError('TOML keys must be non-empty strings.')
    return name if BARE.fullmatch(name) else string(name)


def scalar(item):
    if isinstance(item, bool):
        return 'true' if item else 'false'
    if isinstance(item, int):
        return str(item)
    if isinstance(item, str):
        return string(item)
    if isinstance(item, list):
        if any(isinstance(i, (dict, list)) for i in item):
            raise ValueError('Only flat lists of scalars are supported.')
        return '[' + ', '.join(scalar(i) for i in item) + ']'
    raise ValueError(f'Unsupported TOML value type: {type(item).__name__}.')


def is_tables(item):
    return isinstance(item, list) and bool(item) and all(isinstance(i, dict) for i in item)


def dumps(value, header=''):
    """Serialize a dict. Scalars precede sub-tables in each table, as TOML requires."""
    lines = [f'# {line}'.rstrip() for line in header.splitlines()] + ([''] if header else [])

    def emit(path, table, array=False):
        if path:
            lines.append('')
            lines.append(('[[%s]]' if array else '[%s]') % '.'.join(key(p) for p in path))
        for name, item in table.items():
            if not isinstance(item, dict) and not is_tables(item):
                lines.append(f'{key(name)} = {scalar(item)}')
        for name, item in table.items():
            if isinstance(item, dict):
                emit(path + [name], item)
            elif is_tables(item):
                for entry in item:
                    emit(path + [name], entry, True)

    emit([], value)
    return '\n'.join(lines).lstrip('\n') + '\n'
