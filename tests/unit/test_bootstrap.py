"""WP-01 acceptance: installed entry point and trust-boundary contracts."""

import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4

from cursus import __version__
from cursus.bootstrap import main
from cursus.contracts import (
    MAX_REQUEST_BYTES, MAX_SEQUENCE, MAX_SPEC_BYTES,
    Problem, canonical_json, decode_json, digest, validate,
)
from tests.support import workspace


class BootstrapTests(unittest.TestCase):
    def test_help_is_offline_and_lists_m1_commands(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as result:
                main(["--help"])
        self.assertEqual(result.exception.code, 0)
        self.assertIn("submit", output.getvalue())
        self.assertIn("status", output.getvalue())

    def test_installed_entry_point_and_module(self):
        binary = Path(sys.executable).parent / "cursus"
        result = subprocess.run([str(binary), "--version"], capture_output=True,
                                text=True, timeout=5, check=True)
        self.assertEqual(result.stdout.strip(), f"cursus {__version__}")
        result = subprocess.run([sys.executable, "-I", "-m", "cursus.bootstrap", "--help"],
                                capture_output=True, text=True, timeout=5, check=True)
        self.assertIn("usage: cursus", result.stdout)

    def test_unsupported_commands_fail(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                main(["control"])
        self.assertEqual(result.exception.code, 2)

    def test_workspace_is_empty_isolated_and_cleaned(self):
        with workspace() as first, workspace() as second:
            self.assertNotEqual(first.root, second.root)
            self.assertIn(" ", str(first.root))
            for path in (first.state, first.artifacts, first.worktrees):
                self.assertTrue(path.is_dir())
                self.assertEqual(list(path.iterdir()), [])
            root = first.root
        self.assertFalse(root.exists())


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.id = str(uuid4())
        self.repo = {"owner": "example", "name": "trusted-repo", "target_ref": "refs/heads/main"}
        self.input = {"workflow": "code", "repo": self.repo,
                      "source": {"kind": "inline", "text": "Implement the spec."},
                      "plan_debate": False, "spec_debate": False}
        self.file = {"id": self.id, "digest": "a" * 64, "length": 0,
                     "name": "résultat.txt", "media_type": "text/plain"}

    def assert_problem(self, code, call, *args, **kwargs):
        with self.assertRaises(Problem) as error:
            call(*args, **kwargs)
        self.assertEqual(error.exception.code, code)
        return error.exception

    def test_scalars_and_boundaries(self):
        for contract, value in (("Id", self.id), ("Time", "2026-11-19T12:30:00Z"),
                                ("Time", "2026-11-19T12:30:00.123+00:00"),
                                ("Seq", 1), ("Seq", MAX_SEQUENCE), ("Digest", "f" * 64),
                                ("Sha", "a" * 40)):
            with self.subTest(contract=contract, value=value):
                self.assertEqual(validate(contract, value), value)
        self.assertEqual(validate("Sha", "a" * 64, object_format="sha256"), "a" * 64)
        invalid = {"Id": ["not-a-uuid", self.id.upper(), "{" + self.id + "}"],
                   "Time": ["2026-02-30T00:00:00Z", "2026-11-19", "2026-11-19T00:00:00+01:00"],
                   "Seq": [True, 0, -1, MAX_SEQUENCE + 1, 1.0, "1"],
                   "Digest": ["A" * 64, "a" * 40], "Sha": ["a" * 64, "a" * 7]}
        for contract, values in invalid.items():
            for value in values:
                with self.subTest(contract=contract, value=value), self.assertRaises(Problem):
                    validate(contract, value)

    def test_refs_agree_with_git(self):
        valid = ["refs/heads/main", "refs/heads/wp/a-b/é", "refs/heads/a@b", "refs/heads/a./b"]
        invalid = ["refs/heads/", "refs/heads/a..b", "refs/heads/a.lock/b", "refs/heads/.hidden",
                   "refs/heads/a//b", "refs/heads/a.", "refs/heads/a@{b", "refs/heads/a b",
                   "refs/heads/a\\b", "refs/heads/a*b", "refs/heads/a?b", "refs/heads/a[b",
                   "refs/heads/a~b", "refs/heads/a^b", "refs/heads/a:b", "refs/heads/a\x7fb",
                   "refs/heads/a\nb", "refs/heads/a/"]
        for ref in valid + invalid:
            with self.subTest(ref=ref):
                git = subprocess.run(["git", "check-ref-format", ref], capture_output=True, timeout=5)
                self.assertEqual(git.returncode == 0, ref in valid)
                if ref in valid:
                    self.assertEqual(validate("Ref", ref), ref)
                else:
                    self.assert_problem("invalid_ref", validate, "Ref", ref)
        for ref in ("main", "refs/tags/v1", "HEAD", "@"):
            self.assert_problem("invalid_ref", validate, "Ref", ref)

    def test_duplicate_keys_and_malformed_json(self):
        for raw in ('{"a":1,"a":2}', '{"nested":{"kind":"inline","kind":"repo"}}',
                    '{"a":1,"\\u0061":2}'):
            self.assert_problem("duplicate_key", decode_json, raw)
        for raw in (b'"\xff"', '{', 'NaN', 'Infinity', '1e999', '"\\ud800"', b'\xff\xfe{}'):
            with self.subTest(raw=raw), self.assertRaises(Problem):
                decode_json(raw)
        self.assert_problem("payload_too_large", decode_json, " " * (MAX_REQUEST_BYTES + 1))

    def test_canonical_utf8_order_and_digest(self):
        self.assertEqual(canonical_json({"z": [2, 1], "a": "é"}), b'{"a":"\xc3\xa9","z":[2,1]}')
        reordered = dict(reversed(list(self.input.items())))
        self.assertEqual(digest("Input", self.input), digest("Input", reordered))
        explicit = dict(self.input, form="phase")
        self.assertEqual(digest("Input", self.input), digest("Input", explicit))
        normalized = validate("Input", self.input)
        self.assertEqual(digest("Input", self.input), hashlib.sha256(canonical_json(normalized)).hexdigest())
        with self.assertRaises(Problem):
            digest("Input", dict(self.input, extra="ignored?"))
        for value in (math.nan, math.inf, {1: "key"}, (1, 2), {1, 2}, "\ud800"):
            with self.subTest(value=repr(value)), self.assertRaises(Problem):
                canonical_json(value)

    def test_input_variants_and_no_mutation(self):
        normalized = validate("Input", self.input)
        self.assertEqual(normalized["form"], "phase")
        self.assertNotIn("form", self.input)
        normalized["repo"]["name"] = "changed"
        self.assertEqual(self.repo["name"], "trusted-repo")
        for kind in ("marketing", "grant", "business", "debug"):
            value = dict(self.input, workflow=kind)
            if kind != "debug":
                del value["repo"]
            self.assertEqual(validate("Input", value)["workflow"], kind)
            with self.assertRaises(Problem):
                validate("Input", dict(value, form="phase"))
        for patch in ({"repo": None}, {"workflow": "unknown"}, {"form": "other"},
                      {"source": {"text": "missing kind"}}, {"plan_debate": "false"},
                      {"source": {"kind": "interview", "text": "wrong variant"}}):
            with self.subTest(patch=patch), self.assertRaises(Problem):
                validate("Input", dict(self.input, **patch))

    def test_repo_source_and_size_limit(self):
        source = {"kind": "repo", "owner": "example", "name": "trusted-repo",
                  "commit": "a" * 40, "path": "docs/spec.md"}
        self.assertEqual(validate("Input", dict(self.input, source=source))["source"], source)
        for path in ("../spec.md", "/spec", "docs/../spec", "docs\\spec", "docs//spec", "a\x00"):
            with self.subTest(path=path), self.assertRaises(Problem):
                validate("Input", dict(self.input, source=dict(source, path=path)))
        value = dict(self.input, source={"kind": "inline", "text": "é" * (MAX_SPEC_BYTES // 2)})
        validate("Input", value)
        value["source"]["text"] += "x"
        self.assert_problem("payload_too_large", validate, "Input", value)

    def test_actions_require_matching_fields(self):
        self.assertEqual(validate("Action", {"kind": "submit", "input": self.input})["kind"], "submit")
        cases = [{"kind": "answer", "phase_id": self.id, "question_id": self.id, "text": "yes"},
                 {"kind": "steer", "attempt_id": self.id, "text": "Investigate"},
                 {"kind": "cancel", "phase_id": self.id},
                 {"kind": "abandon", "attempt_id": self.id, "reason": "Unrecoverable"},
                 {"kind": "declare_unrecoverable", "attempt_id": self.id, "reason": "Lost journal"}]
        for value in cases:
            with self.subTest(kind=value["kind"]):
                self.assertEqual(validate("Action", value), value)
                with self.assertRaises(Problem):
                    validate("Action", dict(value, input=self.input))
        self.assert_problem("invalid_variant", validate, "Action", {"kind": "merge"})
        self.assert_problem("invalid_variant", validate, "Action", {})

    def test_candidates_bind_only_their_variant(self):
        code = {"kind": "code", "repo": self.repo, "base_sha": "a" * 40,
                "attempt_ref": "refs/heads/wp/phase/package/attempt", "head_sha": "b" * 40}
        files = {"kind": "files", "files": [self.file]}
        self.assertEqual(validate("Candidate", code), code)
        self.assertEqual(validate("Candidate", files), files)
        for value in (dict(code, files=[self.file]), dict(files, head_sha="b" * 40),
                      {"kind": "files", "files": []}, {"kind": "files", "files": [self.file, self.file]},
                      {"repo": self.repo}):
            with self.subTest(value=value), self.assertRaises(Problem):
                validate("Candidate", value)

    def test_file_metadata_and_safe_errors(self):
        self.assertEqual(validate("FileRef", self.file), self.file)
        for patch in ({"length": True}, {"length": -1}, {"name": "../x"}, {"name": ".."},
                      {"name": "a\\b"}, {"name": "x\n"}, {"media_type": "text/plain\r\nX: x"}):
            with self.subTest(patch=patch), self.assertRaises(Problem):
                validate("FileRef", dict(self.file, **patch))
        error = self.assert_problem("invalid_variant", validate, "Action", {"kind": "SECRET"})
        self.assertNotIn("SECRET", json.dumps(error.as_dict()))
        self.assertEqual(set(error.as_dict()), {"code", "message"})
        self.assert_problem("unsupported_contract", validate, "Job", {})


if __name__ == "__main__":
    unittest.main()
