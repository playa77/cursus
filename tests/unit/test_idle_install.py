"""Offline startup/admission checks for an installed, unenrolled deployment."""
from hashlib import sha256
import os
from pathlib import Path
import pwd
import tempfile
import tomllib
import unittest
from uuid import uuid4

from cursus.config import load
from cursus.contracts import Problem
from cursus.control import Control
from tests.unit.test_install_entrypoint import ROOT, helper
from tests.unit.test_native_setup import module


class IdleDeploymentTests(unittest.TestCase):
    def test_empty_enrollment_cannot_authorize_a_repository(self):
        control = Control({'repositories':[]},None)
        with self.assertRaises(Problem) as result:
            control.enrolled(dict(owner='anyone',name='anything',target_ref='refs/heads/main'))
        self.assertEqual(result.exception.code,'not_enrolled')

    def test_runner_loads_without_any_publisher_files(self):
        native = module('deploy/native_setup.py','idle_native_profiles')
        writer = helper().toml_text
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = tomllib.loads((ROOT/'deploy/runner.host.example.toml').read_text())
            config['repositories'] = []
            config['capacity'] = dict(worker=2,claude=1,codex=1,agy=1,verifier=1,repository=1)
            config['execution'] = dict(disk_reserve_mb=1,host_reserve_mb=1)
            user = pwd.getpwuid(os.getuid()).pw_name
            service = config['service']
            for key in ('state_root','spool_root','repository_root','worktree_root','review_root'):
                service[key] = str(root/key)
            service.update(user=user,origin='https://controller.example.ts.net',runner_id=str(uuid4()),
                           bearer_file=str(root/'bearer'),capabilities_file=str(root/'capabilities.toml'))
            config['publisher'].update(git_credential_file=str(root/'git-token'),github_credential_file=str(root/'api-token'))
            manifest = {'packages':{cli:dict(binary_digest='a'*64,observed_version='fixture-1.0') for cli in native.CLIS}}
            profile = native.profiles(manifest,'unused-fixture-image',{cli:'fixture-model' for cli in native.CLIS},'fixture-provider',config['capacity'])
            profile['qualification'] = 'native-checked'
            for cli in native.CLIS:profile[cli]['probe_evidence'] = ['offline-fixture']
            raw = writer(profile)
            Path(service['capabilities_file']).write_text(raw)
            service['capabilities_digest'] = sha256(raw.encode()).hexdigest()
            bearer = Path(service['bearer_file']);bearer.write_text('fixture-bearer\n');bearer.chmod(0o600)
            path = root/'runner.toml';path.write_text(writer(config))
            self.assertEqual(load('runner',str(path))['repositories'],[])
            self.assertFalse((root/'git-token').exists())
            self.assertFalse((root/'api-token').exists())

    def test_new_run_screen_explains_empty_enrollment_without_a_broken_form(self):
        from cursus.browser import environment
        html = environment().get_template('index.html').render(intake=True,repositories=[],
                    title='New run',theme='system',login='fixture',csrf='fixture',request_id=lambda:str(uuid4()))
        self.assertIn('No repositories enrolled',html)
        self.assertNotIn('name="repository"',html)
        self.assertNotIn('Create run',html)

    def test_enrolled_deployment_keeps_the_new_run_form(self):
        from cursus.browser import environment
        from tests.support import settings
        html = environment().get_template('index.html').render(intake=True,
                    repositories=settings()['repositories'],title='New run',theme='system',
                    login='fixture',csrf='fixture',request_id=lambda:str(uuid4()))
        self.assertIn('name="repository"',html)
        self.assertIn('Create run',html)
        self.assertNotIn('No repositories enrolled',html)
