"""Settings and System pages (ADR 0018): server-rendered forms; every write goes through `Admin`.

Same boundary as the rest of the website: the Tailscale Serve identity, Host and Origin checks run in
the application middleware, and every POST here also needs the session CSRF token. Blocking file and
git work runs in a thread. A rejected form is re-rendered with the submitted values and per-field
messages (HTTP 422), never an error page that discards the operator's input.
"""
import asyncio
from datetime import datetime, timezone
import re
from fastapi import Request
from fastapi.responses import RedirectResponse

from cursus import __version__
from cursus.admin import SECTIONS, TOOLS, FormProblem
from cursus.contracts import Problem

NAME = re.compile(r'[A-Za-z0-9_.-]+')
PROMPT = re.compile(r'[A-Za-z0-9_.-]+\.md')
DEBATE_ROLES = ('advocate', 'critic', 'judge')
EXTRA_CHECK_ROWS = 2


def name(value):
    if not NAME.fullmatch(value) or value in ('.', '..', 'new'):
        raise Problem('not_found', 'Resource unavailable.')
    return value


class Pages:
    def __init__(self, control, browser):
        self.control, self.browser, self.admin = control, browser, control.admin
        self.actor = control.settings['service']['operator_login']

    def render(self, request, template, status=200, **context):
        context.setdefault('nav', 'settings')
        context.setdefault('saved', request.query_params.get('saved'))
        return self.browser.render(request, template, status, **context)

    def redirect(self, path, saved='1'):
        return RedirectResponse(f'{path}?saved={saved}', status_code=303)

    async def write(self, request, work, again, max_fields=400):
        """Parse and CSRF-check a form, run `work(data)` in a thread, or re-render with `again`."""
        data, _ = await self.browser.form(request, max_fields=max_fields, keyed=False)
        try:
            return await asyncio.to_thread(work, data)
        except FormProblem as exc:
            return again(request, data, exc)

    # --- home -----------------------------------------------------------------------------------

    async def home(self, request):
        checklist = await asyncio.to_thread(self.admin.checklist)
        return self.render(request, 'settings_home.html', title="Settings", items=checklist,
                           sections=SECTIONS, read_only=await asyncio.to_thread(self.admin.read_only))

    # --- generic sections -----------------------------------------------------------------------

    def section(self, request, key, values=None, errors=None, exc=None, status=200):
        title, blurb, fields = SECTIONS[key]
        extra = {}
        if key == 'publisher':
            extra['credentials'] = self.admin.credential_status()
        return self.render(request, 'settings_section.html', status=status, title=title, section=key, blurb=blurb,
                           fields=fields, values=values if values is not None else self.admin.values(key),
                           errors=errors or {}, problem=exc.errors.get('') if exc else None, **extra)

    async def section_page(self, request, key):
        if key not in SECTIONS:
            raise Problem('not_found', 'Resource unavailable.')
        return self.section(request, key)

    async def section_save(self, request, key):
        if key not in SECTIONS:
            raise Problem('not_found', 'Resource unavailable.')
        def work(data):
            changed = self.admin.save_section(key, data, self.actor)
            return self.redirect('/settings/' + key, 'saved' if changed else 'unchanged')
        return await self.write(request, work, lambda r, d, e: self.section(r, key, d, e.errors, e, 422))

    async def token(self, request):
        def work(data):
            self.admin.set_token(data.get('token', ''))
            return self.redirect('/settings/publisher', 'token')
        # The submitted token is deliberately not passed back to the page on failure.
        return await self.write(request, work, lambda r, d, e: self.section(r, 'publisher', None, e.errors, e, 422))

    # --- repositories ---------------------------------------------------------------------------

    def repository_context(self, entry=None, data=None):
        if data is not None:
            count = int(data.get('check_rows', '0') or 0)
            rows = [dict(id=data.get(f'check.{i}.id', ''), argv=data.get(f'check.{i}.argv', ''),
                         cwd=data.get(f'check.{i}.cwd', '.'), timeout_seconds=data.get(f'check.{i}.timeout_seconds', '300'))
                    for i in range(count)]
            values = dict(owner=data.get('owner', ''), name=data.get('name', ''),
                          object_format=data.get('object_format', 'sha1'),
                          allowed_target_refs=data.get('allowed_target_refs', ''),
                          phase_check_ids=data.get('phase_check_ids', ''))
        else:
            entry = entry or dict(owner='', name='', object_format='sha1', allowed_target_refs=['refs/heads/main'],
                                  phase_check_ids=[], checks=[])
            rows = [dict(id=c['id'], argv='\n'.join(c['argv']), cwd=c['cwd'], timeout_seconds=c['timeout_seconds'])
                    for c in entry['checks']]
            values = dict(owner=entry['owner'], name=entry['name'], object_format=entry['object_format'],
                          allowed_target_refs='\n'.join(entry['allowed_target_refs']),
                          phase_check_ids=', '.join(entry['phase_check_ids']))
        rows += [dict(id='', argv='', cwd='.', timeout_seconds='300')] * max(EXTRA_CHECK_ROWS - sum(1 for r in rows if not r['id'] and not r['argv']), 0)
        return dict(values=values, rows=rows)

    async def repositories(self, request):
        repos = await asyncio.to_thread(self.admin.repositories)
        return self.render(request, 'settings_repositories.html', title='Repositories', repositories=repos)

    def repository_form(self, request, entry, data=None, exc=None, status=200):
        context = self.repository_context(entry, data)
        return self.render(request, 'settings_repository.html', status=status, existing=entry,
                           title=f'{entry["owner"]}/{entry["name"]}' if entry else 'Enroll a repository',
                           errors=exc.errors if exc else {}, problem=exc.errors.get('') if exc else None, **context)

    async def repository_new(self, request):
        return self.repository_form(request, None)

    async def repository_create(self, request):
        def work(data):
            owner, repo = self.admin.save_repository(data)
            return self.redirect(f'/settings/repositories/{owner}/{repo}', 'saved')
        return await self.write(request, work, lambda r, d, e: self.repository_form(r, None, d, e, 422))

    async def repository_show(self, request, owner, repo):
        entry = await asyncio.to_thread(self.admin.repository, name(owner), name(repo))
        if entry is None:
            raise Problem('not_found', 'Repository is not enrolled.')
        return self.repository_form(request, entry)

    async def repository_update(self, request, owner, repo):
        entry = await asyncio.to_thread(self.admin.repository, name(owner), name(repo))
        if entry is None:
            raise Problem('not_found', 'Repository is not enrolled.')
        def work(data):
            self.admin.save_repository(data, existing=entry)
            return self.redirect(f'/settings/repositories/{owner}/{repo}', 'saved')
        return await self.write(request, work, lambda r, d, e: self.repository_form(r, entry, d, e, 422))

    async def repository_remove(self, request, owner, repo):
        entry = await asyncio.to_thread(self.admin.repository, name(owner), name(repo))
        if entry is None:
            raise Problem('not_found', 'Repository is not enrolled.')
        data, _ = await self.browser.form(request, keyed=False)
        busy = await self.control.store.repository_phases(owner, repo)
        if busy:
            return self.repository_form(request, entry, None, FormProblem({'': (
                f'{busy} unfinished phase(s) still use this repository. Cancel them (or wait for them to finish) '
                'before removing it; a removed repository would leave them unable to advance.')}), 422)
        await asyncio.to_thread(self.admin.remove_repository, owner, repo)
        return self.redirect('/settings/repositories', 'removed')

    # --- roles and prompts ----------------------------------------------------------------------

    def debate_notes(self, roles):
        notes = []
        if all(r in roles for r in DEBATE_ROLES):
            if {roles[r]['cli'] for r in DEBATE_ROLES} != {'claude', 'codex', 'agy'}:
                notes.append('Debates need advocate, critic and judge on three different CLIs (claude, codex, agy).')
            if not (roles['advocate']['cli'] == roles['planner']['cli'] == roles['interviewer']['cli']):
                notes.append('Debates need the advocate, planner and interviewer on the same CLI.')
        return notes

    async def roles(self, request):
        def read():
            return self.admin.roles_view(), self.admin.release_state(), self.admin.prompt_names()
        roles, release, prompts = await asyncio.to_thread(read)
        return self.render(request, 'settings_roles.html', title='Roles and prompts', roles=roles, release=release,
                           prompts=prompts, notes=self.debate_notes(roles))

    def role_form(self, request, role, data=None, exc=None, status=200):
        def known(key):  # an unfilled REPLACE_ placeholder is shown as an empty input, not as a value
            return '' if key in role['holes'] else role.get(key, '')
        values = dict(data) if data is not None else dict(
            tier=role['tier'], cli=role['cli'], model=known('model'), reasoning=known('reasoning'),
            provider=known('provider'), timeout_seconds=role['timeout_seconds'], prompt=role['prompt'],
            **{'tool.' + t: 'on' for t in role['tools']})
        return self.render(request, 'settings_role.html', status=status, title=f'Role: {role["name"]}', role=role,
                           values=values, tools=TOOLS, prompts=self.admin.prompt_names(),
                           errors=exc.errors if exc else {}, problem=exc.errors.get('') if exc else None)

    async def role_show(self, request, role_name):
        roles = await asyncio.to_thread(self.admin.roles_view)
        if name(role_name) not in roles:
            raise Problem('not_found', 'Unknown role.')
        return self.role_form(request, roles[role_name])

    async def role_save(self, request, role_name):
        roles = await asyncio.to_thread(self.admin.roles_view)
        if name(role_name) not in roles:
            raise Problem('not_found', 'Unknown role.')
        def work(data):
            commit = self.admin.save_role(role_name, data, self.actor)
            return self.redirect('/settings/roles', commit[:10] if commit else 'unchanged')
        return await self.write(request, work, lambda r, d, e: self.role_form(r, roles[role_name], d, e, 422))

    async def pin(self, request):
        await self.browser.form(request, keyed=False)
        try:
            commit = await asyncio.to_thread(self.admin.pin_current, self.actor)
        except FormProblem as exc:
            raise Problem('invalid_config', exc.message) from None
        return self.redirect('/settings/roles', commit[:10] if commit else 'unchanged')

    def prompt_form(self, request, file, text, exc=None, status=200):
        return self.render(request, 'settings_prompt.html', status=status, title=f'Prompt: {file}', file=file, text=text,
                           uses=[n for n, r in self.admin.roles_view().items() if r['prompt'] == file],
                           errors=exc.errors if exc else {}, problem=exc.errors.get('') if exc else None)

    async def prompt_show(self, request, file):
        if not PROMPT.fullmatch(file):
            raise Problem('not_found', 'Unknown prompt.')
        return self.prompt_form(request, file, await asyncio.to_thread(self.admin.prompt_text, file))

    async def prompt_save(self, request, file):
        if not PROMPT.fullmatch(file):
            raise Problem('not_found', 'Unknown prompt.')
        def work(data):
            commit = self.admin.save_prompt(file, data.get('text', ''), self.actor)
            return self.redirect('/settings/roles', commit[:10] if commit else 'unchanged')
        return await self.write(request, work, lambda r, d, e: self.prompt_form(r, file, d.get('text', ''), e, 422))

    # --- system ---------------------------------------------------------------------------------

    async def system(self, request, problem=None, status=200):
        deployment = await self.control.store.deployment()
        history = await asyncio.to_thread(self.admin.history)
        return self.render(request, 'settings_system.html', status=status, title='System', deployment=deployment,
                           history=history, preflight=self.browser.preflight_result, version=__version__,
                           runner_id=self.control.settings['runner']['id'], config_path=str(self.admin.path),
                           started=self.browser.started, supervised=self.admin.supervised,
                           settings_pending=self.admin.pending(), problem=problem)

    async def run_preflight(self, request):
        await self.browser.form(request, keyed=False)
        rows = await self.admin.preflight()
        self.browser.preflight_result = (datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'), rows)
        return self.redirect('/settings/system', 'preflight')

    async def restore(self, request):
        data, _ = await self.browser.form(request, keyed=False)
        try:
            await asyncio.to_thread(self.admin.restore, data.get('name', ''))
        except FormProblem as exc:
            return await self.system(request, exc.message, 422)
        return self.redirect('/settings/system', 'restored')

    async def restart(self, request):
        data, _ = await self.browser.form(request, keyed=False)
        deployment = await self.control.store.deployment()
        busy = deployment['unresolved_attempts'] or deployment['queued_jobs']
        if busy and data.get('interrupt') != 'on':
            return await self.system(request, (
                f'{deployment["unresolved_attempts"]} attempt(s) are active and {deployment["queued_jobs"]} job(s) are queued. '
                'A restart cannot resume a running CLI session. Drain first and wait, or tick the box to interrupt them.'), 422)
        try:
            self.admin.request_restart()
        except Problem as exc:
            return await self.system(request, exc.message, 422)
        return self.render(request, 'restarting.html', title='Restarting')


def mount(app, control, browser):
    pages = Pages(control, browser)
    app.state.settings_pages = pages

    @app.get('/settings')
    async def home(request: Request):
        return await pages.home(request)

    @app.get('/settings/system')
    async def system(request: Request):
        return await pages.system(request)

    @app.post('/settings/system/preflight')
    async def preflight(request: Request):
        return await pages.run_preflight(request)

    @app.post('/settings/system/restore')
    async def restore(request: Request):
        return await pages.restore(request)

    @app.post('/settings/system/restart')
    async def restart(request: Request):
        return await pages.restart(request)

    @app.get('/settings/repositories')
    async def repositories(request: Request):
        return await pages.repositories(request)

    @app.get('/settings/repositories/new')
    async def repository_new(request: Request):
        return await pages.repository_new(request)

    @app.post('/settings/repositories/new')
    async def repository_create(request: Request):
        return await pages.repository_create(request)

    @app.get('/settings/repositories/{owner}/{repo}')
    async def repository_show(request: Request, owner: str, repo: str):
        return await pages.repository_show(request, owner, repo)

    @app.post('/settings/repositories/{owner}/{repo}')
    async def repository_update(request: Request, owner: str, repo: str):
        return await pages.repository_update(request, owner, repo)

    @app.post('/settings/repositories/{owner}/{repo}/remove')
    async def repository_remove(request: Request, owner: str, repo: str):
        return await pages.repository_remove(request, owner, repo)

    @app.get('/settings/roles')
    async def roles(request: Request):
        return await pages.roles(request)

    @app.post('/settings/roles/pin')
    async def pin(request: Request):
        return await pages.pin(request)

    @app.get('/settings/roles/{role}')
    async def role_show(request: Request, role: str):
        return await pages.role_show(request, role)

    @app.post('/settings/roles/{role}')
    async def role_save(request: Request, role: str):
        return await pages.role_save(request, role)

    @app.get('/settings/prompts/{file}')
    async def prompt_show(request: Request, file: str):
        return await pages.prompt_show(request, file)

    @app.post('/settings/prompts/{file}')
    async def prompt_save(request: Request, file: str):
        return await pages.prompt_save(request, file)

    @app.post('/settings/publisher/token')
    async def token(request: Request):
        return await pages.token(request)

    @app.get('/settings/{section}')
    async def section_page(request: Request, section: str):
        return await pages.section_page(request, section)

    @app.post('/settings/{section}')
    async def section_save(request: Request, section: str):
        return await pages.section_save(request, section)
