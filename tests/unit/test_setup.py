"""Installer plans and strict input rejection without touching host services."""
from pathlib import Path
import subprocess
import sys
import unittest
from tests.support import workspace


class SetupTests(unittest.TestCase):
    def call(self, host, *args):
        return subprocess.run([sys.executable,'deploy/setup.py',host,'--release','a'*40,*args],
            capture_output=True,text=True,check=False)

    def test_both_hosts_dry_run_without_provisioning(self):
        for host in ('worker','controller'):
            result = self.call(host,'--dry-run')
            self.assertEqual(result.returncode,0,result.stdout)
            self.assertIn('Completed dry-run',result.stdout)
            self.assertIn('/opt/cursus/releases/',result.stdout)
            self.assertNotIn('cursus-exec-',result.stdout)
            self.assertNotIn('RUN ',result.stdout)
        self.assertIn('podman',self.call('worker').stdout)
        self.assertIn('PostgreSQL peer role',self.call('controller').stdout)

    def test_incompatible_supplied_config_is_never_preserved(self):
        with workspace() as ws:
            config = ws.root/'config.toml'
            config.write_text('schema_version = 1\n')
            result = self.call('worker','--dry-run','--config',str(config))
            self.assertNotEqual(result.returncode,0)
            self.assertIn('deliberate migration',result.stdout)
            self.assertNotIn('PLAN apt-get',result.stdout)

    def test_activation_requires_concrete_config(self):
        result = self.call('worker','--activate','--dry-run')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('explicit complete --config',result.stdout)
