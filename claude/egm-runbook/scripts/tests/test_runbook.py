"""Hook and CLI decision tests. Everything runs in a temp HOME, data dir and repo."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'runbook.py')


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = os.path.realpath(self.tmp.name)
        self.home = os.path.join(t, 'home')
        self.data = os.path.join(t, 'data')
        self.repo = os.path.join(t, 'repo')
        for d in (self.home, self.data, os.path.join(self.repo, '.git')):
            os.makedirs(d)
        self.env = dict(os.environ, HOME=self.home, CLAUDE_PLUGIN_DATA=self.data)

    def cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, '--cwd', self.repo, *args],
                              env=self.env, capture_output=True, text=True)

    def hook(self, name, event):
        event = dict(event, cwd=self.repo)
        r = subprocess.run([sys.executable, SCRIPT, 'hook', name], input=json.dumps(event),
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def pre(self, tool, **ti):
        out = self.hook('pre-tool-use', {'tool_name': tool, 'tool_input': ti})
        return out['hookSpecificOutput'] if out else None

    def write(self, rel, text='x'):
        p = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w') as f:
            f.write(text)
        return p

    def start(self, feat='my-feature'):
        r = self.cli('start', feat)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestHooks(Base):
    def test_no_active_feature_is_silent(self):
        for name, ev in [('session-start', {}), ('user-prompt', {'prompt': 'hi'}),
                         ('pre-tool-use', {'tool_name': 'Write', 'tool_input': {'file_path': self.repo + '/a.py'}}),
                         ('pre-tool-use', {'tool_name': 'Skill', 'tool_input': {'skill': 'superpowers:writing-plans'}})]:
            self.assertIsNone(self.hook(name, ev), name)

    def test_code_edit_blocked_in_step_2(self):
        self.start()
        self.write('concepts_brief.md')
        d = self.pre('Write', file_path=os.path.join(self.repo, 'app', 'views.py'))
        self.assertEqual(d['permissionDecision'], 'deny')
        self.assertNotIn('runbook skip', d['permissionDecisionReason'])
        self.assertIn('design gate is closed', d['permissionDecisionReason'])
        self.assertEqual(self.pre('Edit', file_path='app/views.py')['permissionDecision'], 'deny')
        self.assertEqual(self.pre('NotebookEdit', notebook_path=self.repo + '/a.py')['permissionDecision'], 'deny')

    def test_md_and_docs_allowed_in_step_2(self):
        self.start()
        self.assertIsNone(self.pre('Write', file_path=os.path.join(self.repo, 'docs', 'designs', 'x.md')))
        self.assertIsNone(self.pre('Write', file_path=os.path.join(self.repo, 'notes.md')))
        self.assertIsNone(self.pre('Write', file_path=os.path.join(self.repo, 'docs', 'sample.py')))
        self.assertIsNone(self.pre('Write', file_path=os.path.join(self.tmp.name, 'elsewhere.py')))

    def test_artifact_dir_allowed(self):
        self.write('CLAUDE.md', 'EGM artifact directory: `design/egm`\n')
        self.start()
        self.assertIsNone(self.pre('Write', file_path=os.path.join(self.repo, 'design', 'egm', 'x.html')))

    def test_code_edit_allowed_after_gate_skipped(self):
        self.start()
        self.assertTrue(self.pre('Write', file_path=self.repo + '/a.py'))
        r = self.cli('skip', 'gate', '--reason', 'hotfix')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIsNone(self.pre('Write', file_path=self.repo + '/a.py'))
        with open(os.path.join(self.data, os.listdir(self.data)[0], 'my-feature', 'state.json')) as f:
            state = json.load(f)
        self.assertEqual(state['overrides'][0]['reason'], 'hotfix')

    def test_skill_blocked_in_step_3(self):
        self.start()
        self.write('concepts_brief.md')
        self.write('docs/designs/my-feature.md')
        self.assertIn('Step 3/9 review', self.cli('next').stdout)
        for s in ('superpowers:writing-plans', 'superpowers:subagent-driven-development',
                  'superpowers:executing-plans', 'build-loop:build-loop'):
            self.assertEqual(self.pre('Skill', skill=s)['permissionDecision'], 'deny', s)
        d = self.pre('Skill', skill='superpowers:brainstorming')
        self.assertIn('/egm:egm-brainstorm', d['permissionDecisionReason'])
        self.assertIsNone(self.pre('Skill', skill='superpowers:test-driven-development'))

    def test_skill_allowed_once_gate_done(self):
        self.start()
        for s in ('brainstorm', 'draft', 'review', 'resolve'):
            self.assertEqual(self.cli('done', s, '--reason', 'reviewed').returncode, 0)
        self.assertIsNone(self.pre('Skill', skill='superpowers:writing-plans'))
        self.assertIsNone(self.pre('Write', file_path=self.repo + '/a.py'))

    def test_banner_shown_without_active_feature(self):
        os.makedirs(os.path.join(self.home, '.claude', 'workflow-alerts'))
        with open(os.path.join(self.home, '.claude', 'workflow-alerts', 'a.md'), 'w') as f:
            f.write('merge conflict on foo')
        out = self.hook('session-start', {})
        self.assertIn('merge conflict on foo', out['systemMessage'])
        self.assertIn('merge conflict on foo', out['hookSpecificOutput']['additionalContext'])

    def test_session_start_injects_feature_and_egm_line(self):
        self.start()
        ctx = self.hook('session-start', {})['hookSpecificOutput']['additionalContext']
        self.assertIn('my-feature', ctx)
        self.assertIn('/egm:egm-brainstorm', ctx)
        self.assertIn("don't use superpowers:brainstorming", ctx)
        self.assertIn('my-feature', self.hook('user-prompt', {})['hookSpecificOutput']['additionalContext'])


    def test_more_code_kinds_blocked(self):
        self.start()
        self.assertEqual(self.pre('NotebookEdit', notebook_path=self.repo + '/n.ipynb')['permissionDecision'], 'deny')
        self.assertEqual(self.pre('Write', file_path=self.repo + '/Makefile')['permissionDecision'], 'deny')
        self.assertEqual(self.pre('Write', file_path=self.repo + '/sub/Dockerfile')['permissionDecision'], 'deny')
        self.assertEqual(self.pre('Write', file_path=self.repo + '/infra/main.tf')['permissionDecision'], 'deny')
        self.assertEqual(self.pre('MultiEdit', file_path=self.repo + '/a.py', edits=[])['permissionDecision'], 'deny')
        self.assertIsNone(self.pre('Write', file_path=self.repo + '/config.json'))
        self.assertIsNone(self.pre('Write', file_path=self.repo + '/ci.yml'))

    def test_unreadable_state_warns_and_fails_open(self):
        self.start()
        sp = os.path.join(self.data, os.listdir(self.data)[0], 'my-feature', 'state.json')
        with open(sp, 'w') as f:
            f.write('{broken')
        out = self.hook('session-start', {})['hookSpecificOutput']['additionalContext']
        self.assertIn('unreadable', out)
        self.assertIn(sp, out)
        self.assertIn('unreadable', self.hook('user-prompt', {})['hookSpecificOutput']['additionalContext'])
        self.assertIsNone(self.pre('Write', file_path=self.repo + '/a.py'))

    def test_pointer_file_lets_statusline_find_data(self):
        self.start()
        self.hook('user-prompt', {})  # a hook run records the data dir
        env = {k: v for k, v in self.env.items() if k != 'CLAUDE_PLUGIN_DATA'}
        sl = os.path.join(os.path.dirname(SCRIPT), 'statusline')
        r = subprocess.run([sys.executable, sl], input=json.dumps({'cwd': self.repo}),
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout, 'runbook: my-feature · 1/9 brainstorm')
        r = subprocess.run([sys.executable, sl, '--data-dir', self.data], input=json.dumps({'cwd': self.repo}),
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout, 'runbook: my-feature · 1/9 brainstorm')


    def test_unwritable_pointer_does_not_disable_hooks(self):
        self.start()
        os.makedirs(os.path.join(self.home, '.cache'))
        with open(os.path.join(self.home, '.cache', 'egm-runbook'), 'w') as f:
            f.write('a file where the pointer directory should be')
        d = self.pre('Write', file_path=self.repo + '/a.py')
        self.assertEqual(d['permissionDecision'], 'deny')
        self.assertIn('my-feature', self.hook('user-prompt', {})['hookSpecificOutput']['additionalContext'])


class TestCli(Base):
    def test_status_autodetects_design_doc(self):
        self.start()
        self.assertIn('[todo] draft', self.cli('status').stdout)
        self.write('docs/designs/my-feature.md')
        out = self.cli('status').stdout
        self.assertIn('[done] draft', out)
        self.assertIn('[todo] brainstorm', out)

    def test_record_review_and_plan_detected(self):
        self.start()
        self.write('out/consolidated_review_report.md')
        self.cli('record', 'review', 'out/consolidated_review_report.md')
        self.assertIn('[done] review', self.cli('status').stdout)

    def test_state_stays_out_of_repo_and_statusline(self):
        self.start()
        self.assertEqual(os.listdir(self.repo), ['.git'])
        sl = os.path.join(os.path.dirname(SCRIPT), 'statusline')
        r = subprocess.run([sys.executable, sl], input=json.dumps({'cwd': self.repo}),
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.stdout, 'runbook: my-feature · 1/9 brainstorm')
        self.cli('finish')
        r = subprocess.run([sys.executable, sl], input=json.dumps({'cwd': self.repo}),
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.stdout, '')

    def test_skip_requires_reason(self):
        self.start()
        self.assertNotEqual(self.cli('skip', 'gate').returncode, 0)

    def state(self):
        with open(os.path.join(self.data, os.listdir(self.data)[0], 'my-feature', 'state.json')) as f:
            return json.load(f)

    def test_done_on_design_step_needs_reason_and_is_logged(self):
        self.start()
        r = self.cli('done', '3')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('--reason', r.stderr)
        self.assertEqual(self.state()['steps']['3'], 'todo')
        self.assertEqual(self.cli('done', '3', '--reason', 'review done offline').returncode, 0)
        o = self.state()['overrides'][0]
        self.assertEqual((o['kind'], o['step'], o['reason']), ('completion', 'review', 'review done offline'))
        self.assertEqual(self.cli('done', 'build').returncode, 0)  # later steps need no reason

    def test_artifact_dir_parsing(self):
        for line, want in [('**EGM artifact directory:** egm', 'egm'), ('- EGM artifact directory: ./egm/', 'egm'),
                           ('EGM artifact directory: out/egm', 'out/egm'), ('EGM artifact directory: /etc', '.'),
                           ('EGM artifact directory: ../x', '.')]:
            self.write('CLAUDE.md', line + '\n')
            sys.path.insert(0, os.path.dirname(SCRIPT))
            import runbook
            self.assertEqual(runbook.egm_artifact_dir(self.repo), want, line)

    def test_stale_brief_not_counted(self):
        self.write('concepts_brief.md')
        old = os.path.getmtime(self.repo) - 3600
        os.utime(os.path.join(self.repo, 'concepts_brief.md'), (old, old))
        self.start()
        self.assertIn('[todo] brainstorm', self.cli('status').stdout)
        new = os.path.getmtime(self.repo) + 60
        os.utime(os.path.join(self.repo, 'concepts_brief.md'), (new, new))
        self.assertIn('[done] brainstorm', self.cli('status').stdout)

    def test_recorded_brief_counts_even_if_old(self):
        p = self.write('concepts_brief.md')
        old = os.path.getmtime(p) - 3600
        os.utime(p, (old, old))
        self.start()
        self.cli('record', 'brief', 'concepts_brief.md')
        self.assertIn('[done] brainstorm', self.cli('status').stdout)

    def test_start_refuses_existing_unless_force(self):
        self.start()
        r = self.cli('start', 'my-feature')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('--force', r.stderr)
        self.cli('skip', 'gate', '--reason', 'x')
        self.assertEqual(self.cli('start', 'my-feature', '--force').returncode, 0)
        kinds = [(o['kind'], o.get('carried')) for o in self.state()['overrides']]
        self.assertEqual(kinds, [('skip', True), ('restart', True)])

    def test_force_restart_keeps_log_archives_old_state_and_closes_gate(self):
        self.start()
        self.cli('skip', 'gate', '--reason', 'first reason')
        self.cli('start', 'my-feature', '--force')
        st = self.state()
        self.assertEqual(st['overrides'][0]['reason'], 'first reason')
        self.assertEqual(st['steps']['2'], 'todo')
        hist = os.path.join(self.data, os.listdir(self.data)[0], 'my-feature', 'history')
        self.assertTrue(any(f.endswith('state.json') for f in os.listdir(hist)))
        self.assertIsNotNone(self.pre('Write', file_path=self.repo + '/a.py'))  # carried skip does not reopen the gate


class TestOverrideGuard(Base):
    def bash(self, command):
        out = self.hook('pre-tool-use', {'tool_name': 'Bash', 'tool_input': {'command': command}})
        return out['hookSpecificOutput'] if out else None

    def rb(self, rest):
        return 'python3 %s %s' % (os.path.abspath(SCRIPT), rest)

    def open_gate(self):
        for s in ('brainstorm', 'draft', 'review', 'resolve'):
            self.assertEqual(self.cli('done', s, '--reason', 'user did it').returncode, 0)

    def test_blocked_gate_changes_in_step_3(self):
        self.start()
        self.write('concepts_brief.md')
        self.write('docs/designs/my-feature.md')
        for rest in ('done resolve --reason x', 'done 4 --reason x', 'done review --reason x', 'skip gate --reason x',
                     'skip build --reason x', 'record review out.md', 'record brief b.md', 'record design d.md',
                     'record resolve r.md', 'start f --force', 'finish', 'switch other',
                     '--data-dir /tmp/x done draft --reason r'):
            d = self.bash(self.rb(rest))
            self.assertEqual((rest, d and d['permissionDecision']), (rest, 'deny'))
        self.assertEqual(self.bash('cd x && ' + self.rb('skip gate --reason y'))['permissionDecision'], 'deny')
        self.assertEqual(self.bash('bash -c "%s"' % self.rb('skip gate --reason y'))['permissionDecision'], 'deny')

    def test_option_prefix_abbreviations_denied_and_rejected(self):
        self.start()
        for rest in ('--cw . skip gate --reason x', '--cwd . skip gate --reason x', '--data-d /tmp/x skip gate --reason x',
                     'start f --fo', 'start f --forc'):
            d = self.bash(self.rb(rest))
            self.assertEqual((rest, d and d['permissionDecision']), (rest, 'deny'))
        for argv in (['--cw', '.', 'skip', 'gate', '--reason', 'x'], ['start', 'my-feature', '--fo'],
                     ['skip', 'gate', '--reas', 'x'], ['ski', 'gate', '--reason', 'x']):
            r = self.cli(*argv)
            self.assertNotEqual(r.returncode, 0, argv)
        self.assertNotIn('skip', [o['kind'] for o in self.state_overrides()])

    def state_overrides(self):
        with open(os.path.join(self.data, os.listdir(self.data)[0], 'my-feature', 'state.json')) as f:
            return json.load(f)['overrides']

    def test_data_dir_exemption_is_exact(self):
        self.start()
        real = os.path.join(self.data, os.listdir(self.data)[0], 'my-feature', 'state.json')
        d = self.bash(self.rb('status --data-dir /tmp/zz;>%s' % real))
        self.assertEqual(d['permissionDecision'], 'deny')
        for tail in (';>x', ' && cat %s' % real, '|tee %s' % real, '$(id)', '`id`', '>%s' % real):
            d = self.bash(self.rb('status --data-dir %s%s' % (self.data, tail)))
            self.assertEqual((tail, d and d['permissionDecision']), (tail, 'deny'))
        d = self.bash(self.rb('status --data-dir ${CLAUDE_PLUGIN_DATA};>x'))
        self.assertEqual(d['permissionDecision'], 'deny')
        self.assertEqual(self.bash(self.rb('status --data-dir "%s"; echo >%s' % (self.data, real)))['permissionDecision'], 'deny')
        for ok in ('status --data-dir %s' % self.data, 'status --data-dir "%s"' % self.data,
                   "status --data-dir '%s'" % self.data, 'status --data-dir=%s' % self.data,
                   'status --data-dir ${CLAUDE_PLUGIN_DATA}', 'status --data-dir "${CLAUDE_PLUGIN_DATA}"',
                   'status --data-dir "$CLAUDE_PLUGIN_DATA"'):
            self.assertIsNone(self.bash(self.rb(ok)), ok)
        self.assertIsNone(self.bash(self.rb('status --data-dir /tmp/zz;>x')))  # nothing about state

    def test_quoted_mentions_allowed(self):
        self.start()
        for cmd in ('git commit -m "docs: runbook skip gate wording"',
                    'grep -n "runbook.py skip" SKILL.md', 'rg "runbook done" docs',
                    "git commit -m 'runbook.py skip gate'",
                    'cat plugins/egm-runbook/scripts/runbook.py', 'echo "runbook.py skip gate"',
                    'git log --grep="runbook skip gate"'):
            self.assertIsNone(self.bash(cmd), cmd)

    def test_unquoted_mention_is_an_accepted_false_positive(self):
        self.start()
        for cmd in ('grep -n runbook.py skip file', 'echo runbook.py skip gate'):
            self.assertEqual(self.bash(cmd)['permissionDecision'], 'deny', cmd)

    def test_regressions_from_wrappers_and_shell_syntax_denied(self):
        self.start()
        sk = os.path.abspath(SCRIPT)
        run = 'python3 %s skip gate --reason x' % sk
        for cmd in ('timeout 5 ' + run, '{ %s; }' % run, 'if true; then %s; fi' % run,
                    'for i in 1 2; do %s; done' % run, 'while false; do %s; done' % run,
                    'f() { %s; }; f' % run, '! ' + run, 'sudo -u root ' + run, 'nice -n 5 ' + run,
                    'env -i ' + run, 'env -u FOO ' + run, 'time -p ' + run,
                    'python3 -W error %s skip gate --reason x' % sk, 'python3 -X dev %s skip gate --reason x' % sk,
                    'setsid ' + run, 'stdbuf -o0 ' + run, 'flock /tmp/l ' + run, 'watch -n1 ' + run,
                    '>/dev/null ' + run, 'xargs -I{} ' + run, 'find . -exec %s \\;' % run,
                    'python3 "%s" skip gate --reason x' % sk, "python3 '%s' skip gate --reason x" % sk,
                    '%s skip gate --reason x' % sk, 'cd x && ' + run, 'ls; ' + run,
                    'echo $(%s)' % run, 'echo `%s`' % run, 'echo "$(%s)"' % run,
                    "bash -c '%s'" % run, 'sh -lc "%s"' % run, 'eval "%s"' % run,
                    'sudo bash -c "%s"' % run, 'echo "<<X"\n' + run):
            d = self.bash(cmd)
            self.assertEqual((cmd, d and d['permissionDecision']), (cmd, 'deny'))

    def test_heredocs(self):
        self.start()
        run = 'python3 %s skip gate --reason x' % os.path.abspath(SCRIPT)
        msg = ('git commit -m "$(cat <<\'EOF\'\nfix: stop `%s` (and `runbook skip gate`)\n'
               'runbook.py done resolve --reason y\nEOF\n)"' % run)
        self.assertIsNone(self.bash(msg))
        self.assertIsNone(self.bash("cat <<'EOF' > notes.md\n%s\nEOF" % run))
        self.assertIsNone(self.bash('cat <<-EOF\n\t%s\n\tEOF' % 'runbook.py skip gate'.replace('runbook.py', 'x')))
        for cmd in ('bash <<EOF\n%s\nEOF' % run, "sh <<'EOF'\n%s\nEOF" % run,
                    'cat <<EOF\n$(%s)\nEOF' % run, 'cat <<EOF\n`%s`\nEOF' % run,
                    "cat <<'EOF'\nhello\nEOF\n%s" % run, "cat <<'A' <<'B'\none\nA\ntwo\nB\n%s" % run):
            d = self.bash(cmd)
            self.assertEqual((cmd, d and d['permissionDecision']), (cmd, 'deny'))

    def test_hook_is_fast_on_big_heredoc_and_typical_command(self):
        import time
        self.start()
        big = "git commit -m \"$(cat <<'EOF'\n" + 'line of text (with parens) and `ticks`\n' * 140 + 'EOF\n)"'
        self.assertGreater(len(big), 5000)
        for cmd in (big, 'git status && ls -la src | head'):
            t = time.time()
            self.assertIsNone(self.bash(cmd))
            self.assertLess(time.time() - t, 1.0)

    def deny_all(self, cmds):
        for cmd in cmds:
            d = self.bash(cmd)
            self.assertEqual((cmd, d and d['permissionDecision']), (cmd, 'deny'))

    def test_line_continuations(self):
        self.start()
        sk = os.path.abspath(SCRIPT)
        self.deny_all(['python3 "%s" \\\n skip gate --reason ok' % sk,
                       'python3 "%s" \\\n done 1 --reason ok' % sk,
                       'python3 "%s" \\\n record review p.md' % sk,
                       'python3 "%s" start f \\\n --force' % sk,
                       'python3 \\\n"%s" skip gate --reason ok' % sk,
                       'python3 %s \\\n\\\n skip gate --reason ok' % sk,
                       'python3 %s "ski\\\np" gate --reason ok' % sk,
                       'python3 %s sk\\\nip gate --reason ok' % sk])
        self.assertIsNone(self.bash('python3 "%s" \\\n status' % sk))

    def test_heredoc_fed_to_shell_that_is_not_last_on_its_line(self):
        self.start()
        run = 'python3 %s skip gate --reason x' % os.path.abspath(SCRIPT)
        self.deny_all(["bash <<'EOF' 2>&1\n%s\nEOF" % run, 'bash <<EOF && echo hi\n%s\nEOF' % run,
                       'bash <<EOF | tee out\n%s\nEOF' % run, "bash <<'EOF' >/tmp/o 2>&1 ; true\n%s\nEOF" % run,
                       "<<'EOF' bash\n%s\nEOF" % run, 'bash <<EOF &>/tmp/o\n%s\nEOF' % run])
        self.assertIsNone(self.bash("cat <<'EOF' 2>&1\n%s\nEOF" % run))
        self.assertIsNone(self.bash("cat <<'EOF' | tee out\n%s\nEOF" % run))
        self.assertIsNone(self.bash('ls 2>&1 | head; echo a >&2; cmd &>/dev/null'))

    def test_too_complex_commands_are_denied_quickly(self):
        import time
        self.start()
        t = time.time()
        d = self.bash(' '.join(['eval'] * 200))
        self.assertLess(time.time() - t, 0.5)
        self.assertEqual(d['permissionDecision'], 'deny')
        self.assertIn('command too complex for the runbook gate check; ask the user to run it',
                      d['permissionDecisionReason'])
        d = self.bash('echo $(echo $(echo $(echo $(echo $(echo hi)))))')
        self.assertIn('too complex', d['permissionDecisionReason'])
        self.assertIsNone(self.bash('echo $(echo $(date)) && git commit -m "$(cat <<\'EOF\'\nx\nEOF\n)"'))
        # a precise gate hit still wins over the complexity message
        run = 'python3 %s skip gate --reason x' % os.path.abspath(SCRIPT)
        self.assertIn('changes or bypasses', self.bash(run + ' ' + ' '.join(['eval'] * 200))['permissionDecisionReason'])

    def test_redirects_and_ansi_c_quoting_in_the_subcommand_slot(self):
        self.start()
        sk = 'python3 %s' % os.path.abspath(SCRIPT)
        self.deny_all(['%s 2>&1 skip gate --reason x' % sk, '%s >/tmp/o skip gate --reason x' % sk,
                       '%s > /tmp/o skip gate --reason x' % sk, "%s $'skip' gate --reason x" % sk,
                       '%s <<<x skip gate --reason x' % sk, '%s <<< x skip gate --reason x' % sk,
                       "%s $'\\x73kip' gate --reason x" % sk, "%s $'\\163kip' gate --reason x" % sk,
                       '%s &>/tmp/o skip gate --reason x' % sk, '%s 2>/dev/null done 1 --reason x' % sk,
                       '%s <<<"x" skip gate --reason x' % sk, '%s $"skip" gate --reason x' % sk,
                       "bash -c -- '%s skip gate --reason x'" % sk, "bash -c -x '%s skip gate --reason x'" % sk])
        for ok in ('status 2>&1', '2>&1 status', 'status >/tmp/o', 'status > /tmp/o', "$'status'", 'next <<<x'):
            self.assertIsNone(self.bash('%s %s' % (sk, ok)), ok)

    def test_path_with_a_space_and_quoted_sentence_false_positive(self):
        self.start()
        self.deny_all(['python3 "/some dir/scripts/runbook.py" skip gate --reason x',
                       'python3 /some\\ dir/scripts/runbook.py skip gate --reason x'])
        self.assertEqual(self.bash('grep "scripts/runbook.py" skip')['permissionDecision'], 'deny')

    def test_state_path_substring_false_positive(self):
        self.start()
        self.assertEqual(self.bash('ls ~/.cache/egm-runbook-notes')['permissionDecision'], 'deny')


    def test_glob_for_script_denied_in_command_position(self):
        self.start()
        d = self.bash('python3 %s/run*.py skip gate --reason x' % os.path.dirname(os.path.abspath(SCRIPT)))
        self.assertEqual(d['permissionDecision'], 'deny')
        self.assertEqual(self.bash('python3 scripts/r?nbook.py done 2 --reason x')['permissionDecision'], 'deny')
        self.assertIsNone(self.bash('python3 scripts/run*.py status'))
        self.assertIsNone(self.bash('ls scripts/run*.py'))

    def test_allowed_commands(self):
        self.start()
        for rest in ('status', 'next', 'record plan p.md', 'record deep-review r.md', 'start newone',
                     'done build', 'done finish', 'done 5', 'done drift'):
            self.assertIsNone(self.bash(self.rb(rest)), rest)
        self.assertIsNone(self.bash('ls -la && git status'))
        # the form the skill uses: --data-dir with the data dir path is exempt
        self.assertIsNone(self.bash('python3 "%s" --data-dir "%s" status' % (os.path.abspath(SCRIPT), self.data)))

    def test_done_build_allowed_in_step_6_and_finish_after_gate(self):
        self.start()
        self.open_gate()
        self.assertIn('Step 5/9', self.cli('next').stdout)
        self.assertEqual(self.cli('done', 'plan').returncode, 0)
        self.assertIn('Step 6/9', self.cli('next').stdout)
        self.assertIsNone(self.bash(self.rb('done build')))
        self.assertIsNone(self.bash(self.rb('finish')))
        self.assertIsNone(self.bash(self.rb('switch other')))
        self.assertEqual(self.bash(self.rb('skip gate --reason x'))['permissionDecision'], 'deny')

    def test_bash_naming_state_location_denied(self):
        self.start()
        for cmd in ('cat %s/*/*/state.json' % self.data, 'sed -i s/todo/done/ %s/x/STATE.md' % self.data,
                    'echo hi > ~/.cache/egm-runbook/data-dir', 'ls $CLAUDE_PLUGIN_DATA',
                    'cat "${CLAUDE_PLUGIN_DATA}/x"'):
            d = self.bash(cmd)
            self.assertEqual((cmd, d and d['permissionDecision']), (cmd, 'deny'))

    def test_write_into_state_denied_at_any_step(self):
        self.start()
        target = os.path.join(self.data, os.listdir(self.data)[0], 'my-feature', 'state.json')
        for tool in ('Write', 'Edit', 'MultiEdit'):
            self.assertEqual(self.pre(tool, file_path=target)['permissionDecision'], 'deny', tool)
        self.assertEqual(self.pre('Write', file_path=os.path.join(self.home, '.cache', 'egm-runbook', 'data-dir'))
                         ['permissionDecision'], 'deny')
        self.open_gate()
        self.assertEqual(self.pre('Write', file_path=target)['permissionDecision'], 'deny')

    def test_deny_message_has_absolute_copyable_user_command(self):
        self.start()
        d = self.bash(self.rb('done resolve --reason x'))
        msg = d['permissionDecisionReason']
        self.assertIn('must come from the user', msg)
        want = '! python3 %s done resolve --reason "..."' % os.path.abspath(SCRIPT)
        self.assertIn(want, msg)
        self.assertTrue(os.path.isabs(os.path.abspath(SCRIPT)))
        self.assertNotIn(self.data, msg)
        code = self.pre('Write', file_path=self.repo + '/a.py')['permissionDecisionReason']
        self.assertIn('! python3 %s skip gate --reason "..."' % os.path.abspath(SCRIPT), code)

    def test_gate_hint_in_session_start_and_status_only_while_closed(self):
        self.start()
        ctx = self.hook('session-start', {})['hookSpecificOutput']['additionalContext']
        self.assertIn('! python3 %s skip gate' % os.path.abspath(SCRIPT), ctx)
        self.assertIn('! python3 %s skip gate' % os.path.abspath(SCRIPT), self.cli('status').stdout)
        self.open_gate()
        self.assertNotIn('skip gate', self.cli('status').stdout)

    def test_no_output_without_active_feature(self):
        for cmd in (self.rb('skip gate --reason x'), 'cat %s/x' % self.data):
            self.assertIsNone(self.bash(cmd))
        self.assertIsNone(self.pre('Write', file_path=os.path.join(self.data, 'x.json')))


if __name__ == '__main__':
    unittest.main()
