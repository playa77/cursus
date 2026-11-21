"""The publication boundary's HTTP behavior, with the network layer faked (no GitHub contact)."""
import io
import json
from pathlib import Path
import unittest
import urllib.error
from unittest.mock import patch
from cursus.contracts import Problem
from cursus.repository import GitHub, NoRedirect
from tests.support import workspace


class FakeOpener:
    def __init__(self, behavior):
        self.behavior, self.requests = behavior, []

    def open(self, request, timeout=None):
        self.requests.append(request)
        return self.behavior(request)


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def client(ws):
    token = ws.root / 'github-token'
    token.write_text('fixture-token\n')
    token.chmod(0o600)
    return GitHub(str(token))


class GitHubBoundaryTests(unittest.TestCase):
    def test_request_reaches_the_network_layer_with_the_bearer_and_parses_the_reply(self):
        with workspace() as ws:
            opener = FakeOpener(lambda request: Response(json.dumps({'number': 7}).encode()))
            with patch('urllib.request.build_opener', return_value=opener) as build, patch('time.sleep'):
                reply = client(ws).request('POST', '/repos/o/r/pulls', {'title': 't'})
            self.assertEqual(reply, {'number': 7})
            request = opener.requests[0]
            self.assertEqual(request.full_url, 'https://api.github.com/repos/o/r/pulls')
            self.assertEqual(request.get_header('Authorization'), 'Bearer fixture-token')
            self.assertTrue(any(isinstance(h, NoRedirect) for h in build.call_args.args))  # Redirects are never followed.

    def test_redirects_are_refused(self):
        with self.assertRaises(Problem) as caught:
            NoRedirect().redirect_request(None, None, 302, 'Found', {}, 'https://elsewhere.example/')
        self.assertEqual(caught.exception.code, 'transport')

    def test_denial_or_throttling_pauses_the_boundary_without_retry(self):
        with workspace() as ws:
            def denied(request):
                raise urllib.error.HTTPError(request.full_url, 403, 'Forbidden', {}, None)
            opener = FakeOpener(denied)
            github = client(ws)
            with patch('urllib.request.build_opener', return_value=opener), patch('time.sleep'):
                with self.assertRaises(Problem) as first:
                    github.request('GET', '/x')
                with self.assertRaises(Problem) as second:
                    github.request('GET', '/x')
            self.assertEqual(first.exception.code, 'publication_unknown')
            self.assertEqual(second.exception.code, 'github_unavailable')
            self.assertEqual(len(opener.requests), 1)  # No automatic retry, no second attempt.


class NoStaleImportTests(unittest.TestCase):
    def test_every_cursus_import_in_the_source_resolves(self):
        """Function-level imports hide removed names until the code path runs; resolve them all."""
        import ast
        import importlib
        import importlib.util
        unresolved = []
        for path in sorted(Path('src/cursus').glob('*.py')):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('cursus'):
                    module = importlib.import_module(node.module)
                    for alias in node.names:
                        if hasattr(module, alias.name):
                            continue
                        try:
                            found = importlib.util.find_spec(f'{node.module}.{alias.name}')
                        except (ModuleNotFoundError, AttributeError):
                            found = None
                        if not found:
                            unresolved.append(f'{path}:{node.lineno} {node.module}.{alias.name}')
        self.assertEqual(unresolved, [])


if __name__ == '__main__':
    unittest.main()
