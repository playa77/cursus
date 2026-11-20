"""Idle (unenrolled) deployment behavior. The config-loading counterpart returns with the single-process config (WP-C1)."""
import unittest
from uuid import uuid4

from cursus.contracts import Problem
from cursus.control import Control


class IdleDeploymentTests(unittest.TestCase):
    def test_empty_enrollment_cannot_authorize_a_repository(self):
        control = Control({'repositories':[]},None)
        with self.assertRaises(Problem) as result:
            control.enrolled(dict(owner='anyone',name='anything',target_ref='refs/heads/main'))
        self.assertEqual(result.exception.code,'not_enrolled')

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
