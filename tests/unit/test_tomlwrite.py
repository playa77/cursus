"""The TOML writer must read back, through tomllib, exactly what it was given."""
import tomllib
import unittest
from cursus.tomlwrite import dumps


class WriterTests(unittest.TestCase):
    def roundtrip(self, value):
        self.assertEqual(tomllib.loads(dumps(value)), value)

    def test_real_configuration_shapes_round_trip(self):
        self.roundtrip({
            'schema_version': 3, 'process_kind': 'serve',
            'service': {'user': 'alice', 'listen_port': 8787, 'operator_socket': '/run/user/1000/cursus/operator.sock'},
            'execution': {'disk_reserve_mb': 5120, 'path': '/a:/b', 'pass_env': ['XDG_RUNTIME_DIR'], 'clis': {'claude': '/x/claude'}},
            'repositories': [
                {'owner': 'o', 'name': 'n', 'object_format': 'sha1', 'allowed_target_refs': ['refs/heads/main'],
                 'phase_check_ids': ['unit'],
                 'checks': [{'id': 'unit', 'argv': ['/usr/bin/python3', '-m', 'unittest'], 'cwd': '.', 'timeout_seconds': 300}]},
                {'owner': 'o', 'name': 'm', 'object_format': 'sha256', 'allowed_target_refs': ['refs/heads/a', 'refs/heads/b'],
                 'phase_check_ids': ['a'], 'checks': [{'id': 'a', 'argv': ['/bin/true'], 'cwd': 'sub', 'timeout_seconds': 1},
                                                      {'id': 'b', 'argv': ['/bin/false'], 'cwd': '.', 'timeout_seconds': 2}]}]})

    def test_awkward_strings_and_keys_round_trip(self):
        self.roundtrip({'text': 'quote " backslash \\ newline \n tab \t return \r bell \x07 del \x7f unicode é 日本 😀',
                        'path with spaces': {'α': 1}, 'empty': '', 'flag': False, 'list': ['a b', 'c"d'],
                        'roles': {'worker': {'prompt': 'w.md', 'tools': ['read', 'edit']}}})

    def test_empty_list_and_empty_table_round_trip(self):
        self.roundtrip({'repositories': [], 'execution': {'clis': {}}})

    def test_scalars_precede_subtables_so_values_stay_in_their_table(self):
        value = {'a': {'x': 1, 'sub': {'y': 2}, 'z': 3}, 'top': 4}
        self.assertEqual(tomllib.loads(dumps(value)), value)

    def test_unsupported_values_are_refused_not_guessed(self):
        for bad in ({'f': 1.5}, {'n': None}, {'l': [[1]]}, {'l': [{'a': 1}, 2]}, {'s': '\ud800'}, {'': 1}):
            with self.assertRaises(ValueError, msg=bad):
                dumps(bad)

    def test_header_is_a_comment_block(self):
        text = dumps({'a': 1}, 'line one\nline two')
        self.assertTrue(text.startswith('# line one\n# line two\n'))
        self.assertEqual(tomllib.loads(text), {'a': 1})
