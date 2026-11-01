#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
EPISODE = 'yt:abcdefghijk'
TITLE = 'Verification agents'


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def environment(work):
    return {**{key: value for key, value in os.environ.items() if not key.startswith('SIGMA_')},
            'SIGMA_DATA_ROOT': str(work / 'data'), 'SIGMA_EVENTS_DIR': str(work / 'data/events'), 'SIGMA_X_DIR': str(work / 'data/x'),
            'SIGMA_SITE_CONFIG': str(work / 'data/site.json'), 'SIGMA_BASE_URL': 'http://localhost',
            'SIGMA_SHOW_ART_CACHE': str(work / 'data/feed_cache/show-art'), 'SIGMA_NO_LINK_LOOKUP': '1',
            'PYTHONPATH': str(ROOT)}


def command(work, name, args):
    result = subprocess.run(args, cwd=ROOT, env=environment(work), text=True, capture_output=True)
    save(work / 'evidence' / (name + '.json'), {'argv': args, 'exit': result.returncode,
                                              'stdout': result.stdout, 'stderr': result.stderr})
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result


def seed(work):
    run = work / 'data/runs/verification'
    run.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    body = ('# Verification agents\n\n## Transcript\n\n'
            '[0:00:00] Agents need reproducible checks before automatic merging. Verification supplies observable evidence.\n'
            '[0:00:30] Review the resulting application as well as the code. A passing check alone does not prove a useful interface.\n')
    source = run / 'source.md'
    source.write_text(body)
    episode = {'episode_id': EPISODE, 'file': 'source.md', 'title': TITLE, 'source': 'Verification Show',
               'source_tag': 'verification', 'tier': 2, 'style': 'interview', 'published': now,
               'url': 'https://www.youtube.com/watch?v=abcdefghijk', 'youtube_id': 'abcdefghijk',
               'has_transcript': True, 'transcript_source': 'synthetic verification fixture', 'user_pick': True}
    save(run / 'manifest.json', {'run_at': now, 'kind': 'custom', 'episodes': [episode]})
    save(run / 'ranked.json', {'week_of': now[:10], 'run_dir': str(run), 'ranked_by': 'verification fixture',
                             'rubric': 2, 'episodes': [{**{k: episode[k] for k in ['episode_id', 'title', 'url', 'source', 'tier', 'published']},
                             'rank': 1, 'score': 7, 'reason': 'The guest describes reproducible agent checks; no investment view stated.',
                             'claims': [{'ticker': [], 'claim': 'The guest says agents need reproducible checks before automatic merging.',
                                         'speaker': 'guest', 'timestamp': 0, 'novelty': 1, 'verifiable': 2}]}]})
    save(run / 'editor.json', {'version': 1, 'prompt_version': 'verification-fixture', 'episodes': [{
        'episode_id': EPISODE, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'key_insights': [{'title': 'Verify before automatic merging', 'text': 'The guest says agents need reproducible checks before automatic merging.',
                          'why_it_matters': 'Verification supplies observable evidence.', 'speaker': 'guest', 'start': 0, 'end': 29,
                          'companies': [], 'inference': None}],
        'dense_summary': [{'title': 'Reproducible checks', 'text': 'The guest links automatic merging to reproducible checks and observable evidence.', 'start': 0, 'end': 29},
                          {'title': 'Review the application', 'text': 'The guest says to review the resulting application as well as the code; passing checks alone do not establish a useful interface.', 'start': 30, 'end': 50}]}]})
    save(work / 'data/site.json', {'site_name': 'Sigma verification', 'picks_label': 'User picks', 'base_url': 'http://localhost'})
    command(work, 'publish-fixture', [sys.executable, '-m', 'sigma.cli', 'publish', str(run / 'ranked.json')])


def read_state(work):
    return json.loads((work / 'instance.json').read_text())


def owned_instance(work):
    state = read_state(work)
    with urllib.request.urlopen(state['url'] + '/', timeout=3) as response:
        if response.headers.get('X-Sigma-Verify-Token') != state['token'] or response.headers.get('X-Sigma-Verify-Pid') != str(state['pid']):
            raise RuntimeError('port is not owned by this verification instance')
        if b'Sigma verification' not in response.read():
            raise RuntimeError('server has not reached the seeded application')
    return state


def doctor(work):
    state = owned_instance(work)
    if state['checkout'] != str(ROOT):
        raise RuntimeError('instance belongs to a different checkout')
    if importlib.util.find_spec('playwright') is None:
        raise RuntimeError('Playwright is missing; install the optional verify dependencies')
    with urllib.request.urlopen(state['url'] + '/episodes.json', timeout=3) as response:
        if not any(row['episode_id'] == EPISODE for row in json.load(response)['episodes']):
            raise RuntimeError('seeded episode is missing')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if state['source_sha'] != head:
        raise RuntimeError('checkout revision changed; launch a fresh instance')
    return state


def serve(work):
    state = read_state(work)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header('X-Sigma-Verify-Token', state['token'])
            self.send_header('X-Sigma-Verify-Pid', str(os.getpid()))
            super().end_headers()

        def translate_path(self, path):
            target = Path(super().translate_path(path))
            if not target.exists() and target.with_suffix('.html').is_file():
                return str(target.with_suffix('.html'))
            return str(target)

    handler = functools.partial(Handler, directory=str(work / 'dist'))
    with http.server.ThreadingHTTPServer(('127.0.0.1', state['port']), handler) as server:
        server.serve_forever()


def launch(work):
    if any(work.iterdir()):
        raise RuntimeError('launch needs an empty scratch directory; existing state was preserved')
    (work / 'evidence').mkdir()
    command(work, 'source-status', ['git', 'status', '--porcelain'])
    command(work, 'source-diff', ['git', 'diff', 'HEAD'])
    seed(work)
    command(work, 'build', [sys.executable, '-m', 'sigma.cli', 'site', '--out', str(work / 'dist')])
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    state = {'checkout': str(ROOT), 'source_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
             'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'port': port, 'url': f'http://127.0.0.1:{port}', 'token': secrets.token_hex(24), 'pid': None}
    save(work / 'instance.json', state)
    with (work / 'evidence/server.log').open('w') as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_serve', '--work', str(work)],
                                 cwd=ROOT, env=environment(work), stdout=log, stderr=log, start_new_session=True)
    state['pid'] = child.pid
    save(work / 'instance.json', state)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError('owned server exited; inspect evidence/server.log')
        try:
            doctor(work)
            print(json.dumps(state))
            return
        except (OSError, RuntimeError):
            time.sleep(0.05)
    os.kill(child.pid, signal.SIGTERM)
    child.wait(timeout=3)
    raise RuntimeError('seeded instance was not ready in ten seconds')


def cleanup(work):
    state = read_state(work)
    try:
        owned = owned_instance(work)
    except OSError:
        try:
            os.kill(state['pid'], 0)
        except ProcessLookupError:
            owned = None
        else:
            raise RuntimeError('server identity unavailable while PID exists; refusing to kill an unverified process')
    if owned:
        os.kill(owned['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(owned['url'] + '/', timeout=0.2).close()
            except OSError:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError('owned server still answers after SIGTERM')
    save(work / 'evidence/cleanup.json', {'server_stopped': True, 'scratch_preserved': True,
                                         'evidence': sorted(p.name for p in (work / 'evidence').iterdir())})
    print('Owned server stopped; scratch and evidence preserved at ' + str(work / 'evidence'))


def drive(work, feature):
    state = doctor(work)
    from playwright.sync_api import sync_playwright

    evidence = work / 'evidence'
    before = {str(p.relative_to(work / 'data')): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (work / 'data').rglob('*') if p.is_file()}
    result = {'feature': feature, 'url': state['url'], 'actions': [], 'viewports': []}
    def action(text):
        result['actions'].append(text)
        save(evidence / (feature + '.json'), result)
    chrome = os.environ.get('SIGMA_VERIFY_BROWSER')
    if not chrome and Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').is_file():
        chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True, **({'executable_path': chrome} if chrome else {}))
        try:
            for width in [1280, 390]:
                context = browser.new_context(viewport={'width': width, 'height': 900})
                context.tracing.start(screenshots=True, snapshots=True, sources=False)
                errors = []
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(state['url'] + '/') else route.abort())
                try:
                    page.goto(state['url'] + '/', wait_until='networkidle')
                    action(f'{width}: open homepage')
                    card = page.locator('#top li.entry').filter(has=page.get_by_role('link', name=TITLE, exact=True))
                    card.wait_for(state='visible')
                    if feature == 'reading':
                        card.get_by_role('button', name='Toggle details for ' + TITLE).click()
                        card.locator('.key-insights').wait_for(state='visible')
                        assert card.locator('.dense-summary').count() == 0
                        assert card.get_by_role('button', name='Toggle details for ' + TITLE).get_attribute('aria-expanded') == 'true'
                        action(f'{width}: expand episode; insights visible and chronological summary absent')
                        page.screenshot(path=str(evidence / f'{feature}-{width}-expanded.png'))
                        with page.expect_navigation(wait_until='domcontentloaded'):
                            card.get_by_role('link', name='Open the episode page').click()
                    else:
                        with page.expect_navigation(wait_until='domcontentloaded'):
                            page.locator('.top-head').get_by_role('link', name='User picks', exact=True).click()
                        page.locator('#f-count').wait_for()
                        page.wait_for_function('document.querySelector("#f-count")?.textContent === "1 episode"')
                        action(f'{width}: homepage picks chip opens Find with one picked result')
                        assert page.get_by_label('Picks', exact=True).input_value() == '1'
                        page.get_by_label('Search titles, guests and claims', exact=True).fill('no-such-verification-episode')
                        page.wait_for_function('document.querySelector("#f-count")?.textContent === "0 episodes"')
                        action(f'{width}: unmatched query produces zero results')
                        page.get_by_label('Search titles, guests and claims', exact=True).fill('Verification')
                        page.wait_for_function('document.querySelector("#f-count")?.textContent === "1 episode"')
                        with page.expect_navigation(wait_until='domcontentloaded'):
                            page.locator('#f-out h3').get_by_role('link', name=TITLE, exact=True).click()
                    page.locator('.dense-summary').wait_for()
                    assert page.locator('.key-insights li').count() == 1
                    assert page.locator('.dense-summary > section').count() == 2
                    assert [heading.split(' ', 1)[0] for heading in page.locator('.dense-summary > section h3').all_text_contents()] == ['0:00–0:29', '0:30–0:50']
                    action(f'{width}: episode page shows one insight and two chronological sections')
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    assert not errors
                    page.screenshot(path=str(evidence / f'{feature}-{width}.png'), full_page=True)
                    (evidence / f'{feature}-{width}.aria.txt').write_text(page.locator('body').aria_snapshot())
                    if feature == 'reading':
                        page.goto(state['url'] + '/episodes/yt_abcdefghijk.html', wait_until='domcontentloaded')
                        assert page.locator('.dense-summary > section').count() == 2
                        action(f'{width}: direct episode entry also renders both sections')
                    else:
                        with page.expect_navigation(wait_until='domcontentloaded'):
                            page.locator('.meta').get_by_role('link', name='User picks', exact=True).first.click()
                        page.locator('#f-count').wait_for()
                        page.wait_for_function('document.querySelector("#f-count")?.textContent === "1 episode"')
                        page.goto(state['url'] + '/find/', wait_until='domcontentloaded')
                        page.locator('#f-count').wait_for()
                        page.get_by_label('Picks', exact=True).select_option('1')
                        page.wait_for_function('document.querySelector("#f-count")?.textContent === "1 episode"')
                        action(f'{width}: episode badge and direct Find entry both support picks filtering')
                    result['viewports'].append({'width': width, 'javascript_errors': errors, 'overflow': False})
                finally:
                    context.tracing.stop(path=str(evidence / f'{feature}-{width}.zip'))
                    context.close()
        finally:
            browser.close()
    after = {str(p.relative_to(work / 'data')): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in (work / 'data').rglob('*') if p.is_file()}
    assert before == after, 'browser driving changed source or publication data'
    result.update(status='passed', data_unchanged=True, source_sha=state['source_sha'])
    save(evidence / (feature + '.json'), result)
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['launch', 'doctor', 'drive', 'cleanup', '_serve'])
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--feature', choices=['reading', 'picks'], default='reading')
    args = parser.parse_args()
    work = args.work.expanduser().resolve()
    if args.action == 'launch':
        work.mkdir(parents=True, exist_ok=True)
        launch(work)
    elif args.action == '_serve':
        serve(work)
    elif args.action == 'doctor':
        print(json.dumps(doctor(work)))
    elif args.action == 'cleanup':
        cleanup(work)
    else:
        drive(work, args.feature)


if __name__ == '__main__':
    main()
