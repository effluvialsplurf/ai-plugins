#!/usr/bin/env python3
"""egm-runbook: per-feature runbook state, CLI and hook logic (standard library only).

State lives in the plugin data dir, never in the project repo:
    <data>/<repo-key>/ACTIVE                  slug of the active feature
    <data>/<repo-key>/<feature>/state.json    machine-readable state
    <data>/<repo-key>/<feature>/STATE.md      human-readable copy, rewritten on every change

Data dir: --data-dir, else $CLAUDE_PLUGIN_DATA, else the pointer file the hooks write
(~/.cache/egm-runbook/data-dir), else ~/.claude/plugins/data/egm-runbook.
Hooks fail open: any internal error prints nothing and exits 0.
"""
import argparse
import datetime
import fnmatch
import glob
import hashlib
import json
import os
import re
import sys

STEPS = {
    1: ('brainstorm', 'egm', '/egm:egm-brainstorm'),
    2: ('draft', 'egm', '/egm:egm-draft'),
    3: ('review', 'egm', '/egm:egm-review'),
    4: ('resolve', 'egm', '/egm:egm-resolve'),
    5: ('plan', 'claude', 'superpowers:writing-plans'),
    6: ('build', 'claude', 'superpowers:subagent-driven-development'),
    7: ('deep-review', 'claude', 'deep-review'),
    8: ('finish', 'claude', 'superpowers:finishing-a-development-branch'),
    9: ('drift', 'egm', '/egm:egm-drift-report'),
}
STEP_BY_NAME = {v[0]: k for k, v in STEPS.items()}
GATE_LAST = 4  # steps 1..4 are design-only: no code
ARTIFACT_STEP = {'brief': 1, 'design': 2, 'review': 3, 'plan': 5, 'deep-review': 7, 'drift': 9}

CODE_EXT = {
    '.py', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.html', '.htm', '.css', '.scss',
    '.sass', '.less', '.ipynb', '.tf', '.hcl', '.sql', '.sh', '.bash', '.zsh', '.go', '.java', '.kt', '.rb', '.php',
    '.vue', '.svelte', '.c', '.cc', '.cpp', '.h', '.hpp', '.cs', '.rs', '.swift', '.pl', '.lua',
}
CODE_NAMES = {'makefile', 'dockerfile', 'jenkinsfile'}
BLOCKED_SKILLS = {
    'superpowers:writing-plans', 'superpowers:subagent-driven-development',
    'superpowers:executing-plans', 'build-loop:build-loop',
}
BRAINSTORM_SKILL = 'superpowers:brainstorming'
BANNER_MAX_FILES = 10
BANNER_MAX_CHARS = 4000


# ---------------------------------------------------------------- locations

def pointer_file():
    return os.path.join(os.path.expanduser('~'), '.cache', 'egm-runbook', 'data-dir')


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = '%s.%d.tmp' % (path, os.getpid())
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def remember_data_dir():
    """Hooks see CLAUDE_PLUGIN_DATA; the status line and a shell CLI do not. Leave a pointer for them."""
    d = os.environ.get('CLAUDE_PLUGIN_DATA')
    if not d:
        return
    d = os.path.abspath(d)
    try:
        with open(pointer_file(), encoding='utf-8') as f:
            if f.read().strip() == d:
                return
    except OSError:
        pass
    atomic_write(pointer_file(), d + '\n')


def data_dir(override=None):
    d = override or os.environ.get('CLAUDE_PLUGIN_DATA')
    if not d:
        try:
            with open(pointer_file(), encoding='utf-8') as f:
                d = f.read().strip()
        except OSError:
            d = ''
    d = d or os.path.join(os.path.expanduser('~'), '.claude', 'plugins', 'data', 'egm-runbook')
    return os.path.abspath(d)


def find_repo(start):
    """Nearest ancestor holding .git (dir or worktree file), else None."""
    p = os.path.realpath(start or os.getcwd())
    while True:
        if os.path.exists(os.path.join(p, '.git')):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def repo_key(repo):
    return '%s-%s' % (re.sub(r'[^A-Za-z0-9._-]', '_', os.path.basename(repo)),
                      hashlib.sha1(repo.encode()).hexdigest()[:8])


def repo_dir(data, repo):
    return os.path.join(data, repo_key(repo))


def egm_artifact_dir(repo):
    """Folder named by the 'EGM artifact directory:' line of the project CLAUDE.md, else repo root."""
    try:
        with open(os.path.join(repo, 'CLAUDE.md'), encoding='utf-8') as f:
            for line in f:
                m = re.search(r'EGM artifact directory:\s*(.+)', line)
                if m:
                    v = m.group(1).strip().strip('*_`"\' ')
                    while v.startswith('./'):
                        v = v[2:]
                    v = v.rstrip('/')
                    if v and not os.path.isabs(v) and '..' not in v.split('/'):
                        return v
                    return '.'
    except OSError:
        pass
    return '.'


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def ucmd(rest):
    """Copyable command for the USER to type at the prompt (the `!` prefix runs it outside Claude's tools)."""
    return '! python3 %s %s' % (os.path.abspath(__file__), rest)


def gate_hint(st):
    """How the user finishes or overrides the closed design gate. Claude must not run these."""
    n = current_step(st)
    cur = STEPS[n][0] if n and n <= GATE_LAST else 'resolve'
    return ('Gate overrides come only from the user. To mark the current design step done: %s . '
            'To override the whole gate: %s'
            % (ucmd('done %s --reason "..."' % cur), ucmd('skip gate --reason "..."')))


# ---------------------------------------------------------------- state

def slugify(s):
    slug = re.sub(r'[^a-z0-9._-]+', '-', s.strip().lower()).strip('-.')
    if not slug:
        raise SystemExit('error: feature name is empty')
    return slug


def feature_dir(data, repo, feature):
    return os.path.join(repo_dir(data, repo), feature)


def load(data, repo, feature):
    try:
        with open(os.path.join(feature_dir(data, repo, feature), 'state.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def active_feature(data, repo):
    try:
        with open(os.path.join(repo_dir(data, repo), 'ACTIVE'), encoding='utf-8') as f:
            return f.read().strip() or None
    except OSError:
        return None


def set_active(data, repo, feature):
    path = os.path.join(repo_dir(data, repo), 'ACTIVE')
    if feature is None:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    atomic_write(path, feature + '\n')


def new_state(feature, repo):
    return {'feature': feature, 'repo': repo, 'created': now(), 'finished': None,
            'steps': {str(n): 'todo' for n in STEPS}, 'artifacts': {}, 'overrides': []}


def save(data, repo, st):
    d = feature_dir(data, repo, st['feature'])
    atomic_write(os.path.join(d, 'state.json'), json.dumps(st, indent=2))
    atomic_write(os.path.join(d, 'STATE.md'), render_md(st))


def artifact_path(st, name):
    """Absolute path of an artifact: recorded one, or the conventional default if any."""
    repo = st['repo']
    rec = st['artifacts'].get(name)
    if rec:
        return rec if os.path.isabs(rec) else os.path.join(repo, rec)
    art = egm_artifact_dir(repo)
    feat = st['feature']
    if name == 'brief':
        return os.path.join(repo, art, 'concepts_brief.md')
    if name == 'design':
        return os.path.join(repo, 'docs', 'designs', feat + '.md')
    if name == 'deep-review':
        hits = sorted(glob.glob(os.path.join(repo, 'docs', 'reviews', '*%s*.md' % glob.escape(feat))))
        return hits[-1] if hits else None
    return None  # review, plan, drift: only when recorded


def started_ts(st):
    try:
        return datetime.datetime.fromisoformat(st['created']).timestamp()
    except (KeyError, ValueError):
        return 0


def detect(st):
    """Step statuses with auto-detection applied (does not mutate st)."""
    steps = dict(st['steps'])
    for name, n in ARTIFACT_STEP.items():
        p = artifact_path(st, name)
        if steps[str(n)] == 'todo' and p and os.path.isfile(p):
            # A conventional-path brief may be left over from an earlier feature: only count it if
            # it was recorded for this feature or written after the feature started.
            if name == 'brief' and not st['artifacts'].get('brief') and os.path.getmtime(p) < started_ts(st):
                continue
            steps[str(n)] = 'done'
    return steps


def gate_open(st, steps=None):
    steps = steps or detect(st)
    if any(o['step'] == 'gate' and not o.get('carried') for o in st['overrides']):
        return True
    return all(steps[str(n)] in ('done', 'skipped') for n in range(1, GATE_LAST + 1))


def current_step(st, steps=None):
    """First of steps 1..8 not done/skipped; 9 if only the optional drift step is left; None when all done."""
    steps = steps or detect(st)
    for n in range(1, 9):
        if steps[str(n)] == 'todo':
            return n
    if steps['9'] == 'todo':
        return 9
    return None


def next_guidance(st, steps=None):
    n = current_step(st, steps)
    feat = st['feature']
    art = egm_artifact_dir(st['repo'])
    if n is None:
        return 'All steps are done or skipped. Run: runbook finish'
    name, who, cmd = STEPS[n]
    user = 'You type'
    tips = {
        1: '%s: %s   (output: %s/concepts_brief.md)' % (user, cmd, art),
        2: '%s: %s   (output: docs/designs/%s.md)' % (user, cmd, feat),
        3: '%s: %s   (consolidated preset writes consolidated_review_report.md; then you record it: %s)' % (user, cmd, ucmd('record review <path>')),
        4: '%s: %s   (applies approved fixes; then you mark it done: %s)' % (user, cmd, ucmd('done resolve --reason "..."')),
        5: 'Claude may invoke %s with docs/designs/%s.md as the spec, once you agree. Then: runbook record plan <path>. '
           'Alternative covering steps 5-8: build-loop, "start the loop from docs/designs/%s.md report <path>".' % (cmd, feat, feat),
        6: 'Claude may invoke %s once you agree. Then: runbook done build' % cmd,
        7: 'Claude may invoke deep-review on the diff once you agree (writes docs/reviews/<date>-<slug>.md), then '
           'deep-review:receiving-deep-review',
        8: 'Claude may invoke %s once you agree. Then: runbook done finish' % cmd,
        9: 'Optional. %s: %s   (writes <YYYY-MM-DD>_DRIFT_REPORT.md). Or end now: runbook finish' % (user, cmd),
    }
    return 'Step %d/9 %s. %s' % (n, name, tips[n])


def one_liner(st):
    steps = detect(st)
    n = current_step(st, steps)
    if n is None:
        return 'egm-runbook: feature %s: all steps done. Run runbook finish.' % st['feature']
    return 'egm-runbook: feature %s. %s' % (st['feature'], next_guidance(st, steps))


def render_md(st):
    steps = detect(st)
    out = ['# egm-runbook: %s' % st['feature'], '',
           '- Repo: `%s`' % st['repo'], '- Created: %s' % st['created'],
           '- Finished: %s' % (st['finished'] or 'no'),
           '- Gate (steps 1-4, no code): %s' % ('open' if gate_open(st, steps) else 'closed'), '',
           '## Steps', '']
    for n, (name, _who, cmd) in STEPS.items():
        art = [a for a, s in ARTIFACT_STEP.items() if s == n]
        p = artifact_path(st, art[0]) if art else None
        extra = ' -> `%s`' % p if p and (st['artifacts'].get(art[0]) or os.path.isfile(p)) else ''
        out.append('%d. [%s] %s (%s)%s' % (n, steps[str(n)], name, cmd, extra))
    out += ['', '## Next', '', next_guidance(st, steps)]
    if not gate_open(st, steps):
        out += ['', gate_hint(st)]
    out += ['', '## Overrides', '']
    out += ['- %s %s step=%s reason: %s' % (o['ts'], o.get('kind', 'skip'), o['step'], o['reason'])
            for o in st['overrides']] or ['none']
    return '\n'.join(out) + '\n'


def parse_step(s):
    if s == 'gate':
        return 'gate'
    s = s.strip().lower()
    if s.isdigit() and int(s) in STEPS:
        return int(s)
    if s in STEP_BY_NAME:
        return STEP_BY_NAME[s]
    raise SystemExit('error: unknown step %r (use 1-9, a step name %s, or gate)' % (s, ', '.join(STEP_BY_NAME)))


# ---------------------------------------------------------------- CLI

def ctx(args):
    repo = find_repo(args.cwd)
    if not repo:
        raise SystemExit('error: not inside a git repository')
    return data_dir(args.data_dir), repo


def need_active(args):
    data, repo = ctx(args)
    feat = active_feature(data, repo)
    st = load(data, repo, feat) if feat else None
    if not st:
        raise SystemExit('error: no active feature in this repo. Run: runbook start <feature>')
    return data, repo, st


def persist_detected(st):
    for k, v in detect(st).items():
        st['steps'][k] = v


def cmd_start(a):
    data, repo = ctx(a)
    feat = slugify(a.feature)
    if os.path.exists(feature_dir(data, repo, feat)) and not a.force:
        raise SystemExit('error: feature %s already exists. Use "runbook switch %s" to resume it, or '
                         '"runbook start %s --force" to reset its state.' % (feat, feat, feat))
    st = new_state(feat, repo)
    msg = 'Started feature %s.' % feat
    fdir = feature_dir(data, repo, feat)
    if os.path.exists(fdir):  # --force: archive the old state and keep the override log
        stamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
        hist = os.path.join(fdir, 'history')
        for name in ('state.json', 'STATE.md'):
            try:
                with open(os.path.join(fdir, name), encoding='utf-8', errors='replace') as f:
                    atomic_write(os.path.join(hist, '%s-%s' % (stamp, name)), f.read())
            except OSError:
                pass
        old = load(data, repo, feat)
        carried = [dict(o, carried=True) for o in (old or {}).get('overrides', [])]
        carried.append({'ts': now(), 'kind': 'restart', 'step': 'start --force', 'carried': True,
                        'reason': 'state reset; previous state archived in history/%s-*' % stamp})
        st['overrides'] = carried
        msg = 'Restarted feature %s (old state archived under %s).' % (feat, hist)
    save(data, repo, st)
    set_active(data, repo, feat)
    print(msg)
    print(next_guidance(st))


def cmd_status(a):
    data, repo, st = need_active(a)
    persist_detected(st)
    save(data, repo, st)
    print(render_md(st), end='')


def cmd_next(a):
    data, repo, st = need_active(a)
    persist_detected(st)
    save(data, repo, st)
    print(next_guidance(st))


def cmd_record(a):
    data, repo, st = need_active(a)
    if a.artifact not in ARTIFACT_STEP:
        raise SystemExit('error: artifact must be one of %s' % ', '.join(ARTIFACT_STEP))
    p = os.path.abspath(os.path.join(a.cwd or os.getcwd(), a.path))
    rel = os.path.relpath(p, repo)
    st['artifacts'][a.artifact] = rel if not rel.startswith('..') else p
    persist_detected(st)
    save(data, repo, st)
    print('Recorded %s = %s%s' % (a.artifact, p, '' if os.path.exists(p) else ' (file does not exist yet)'))
    print(next_guidance(st))


def cmd_done(a):
    data, repo, st = need_active(a)
    n = parse_step(a.step)
    if n == 'gate':
        raise SystemExit('error: "gate" is only valid with skip')
    persist_detected(st)
    reason = (a.reason or '').strip()
    if n <= GATE_LAST and st['steps'][str(n)] != 'done':
        if not reason:
            raise SystemExit('error: --reason is required to mark a design step (1-4) done by hand; it is logged')
        st['overrides'].append({'ts': now(), 'kind': 'completion', 'step': STEPS[n][0], 'reason': reason})
    st['steps'][str(n)] = 'done'
    save(data, repo, st)
    print('Step %d %s: done.' % (n, STEPS[n][0]))
    print(next_guidance(st))


def cmd_skip(a):
    data, repo, st = need_active(a)
    if not (a.reason or '').strip():
        raise SystemExit('error: --reason is required for skip')
    n = parse_step(a.step)
    persist_detected(st)
    if n == 'gate':
        for k in range(1, GATE_LAST + 1):
            if st['steps'][str(k)] == 'todo':
                st['steps'][str(k)] = 'skipped'
    else:
        st['steps'][str(n)] = 'skipped'
    st['overrides'].append({'ts': now(), 'kind': 'skip', 'step': 'gate' if n == 'gate' else STEPS[n][0],
                            'reason': a.reason.strip()})
    save(data, repo, st)
    print('Override logged: %s skipped. Reason: %s' % ('gate (steps 1-4)' if n == 'gate' else STEPS[n][0], a.reason.strip()))
    print(next_guidance(st))


def cmd_switch(a):
    data, repo = ctx(a)
    feat = slugify(a.feature)
    st = load(data, repo, feat)
    if not st:
        raise SystemExit('error: no feature %s in this repo. Run: runbook start %s' % (feat, feat))
    st['finished'] = None
    save(data, repo, st)
    set_active(data, repo, feat)
    print('Active feature: %s' % feat)
    print(next_guidance(st))


def cmd_finish(a):
    data, repo, st = need_active(a)
    persist_detected(st)
    left = [STEPS[n][0] for n in range(1, 9) if st['steps'][str(n)] == 'todo']
    st['finished'] = now()
    save(data, repo, st)
    set_active(data, repo, None)
    print('Finished feature %s. State kept at %s' % (st['feature'], feature_dir(data, repo, st['feature'])))
    if left:
        print('Note: steps never done or skipped: %s' % ', '.join(left))


# ---------------------------------------------------------------- hooks

def hook_event():
    try:
        ev = json.load(sys.stdin)
        return ev if isinstance(ev, dict) else {}
    except ValueError:
        return {}


def emit(obj):
    sys.stdout.write(json.dumps(obj))


def alerts_banner():
    d = os.path.join(os.path.expanduser('~'), '.claude', 'workflow-alerts')
    try:
        files = sorted(glob.glob(os.path.join(d, '*.md')))[:BANNER_MAX_FILES]
    except OSError:
        return ''
    parts = []
    for p in files:
        try:
            with open(p, encoding='utf-8', errors='replace') as f:
                text = f.read(BANNER_MAX_CHARS).strip()
        except OSError:
            continue
        if text:
            parts.append('WARNING workflow alert (%s):\n%s' % (os.path.basename(p), text))
    return '\n\n'.join(parts)


def active_state(event, data):
    repo = find_repo(event.get('cwd'))
    if not repo:
        return None
    feat = active_feature(data, repo)
    return load(data, repo, feat) if feat else None


def unreadable_warning(event, data):
    """One line when the active feature's state.json exists but cannot be read (the gate is then off)."""
    repo = find_repo(event.get('cwd'))
    feat = active_feature(data, repo) if repo else None
    if not feat:
        return ''
    path = os.path.join(feature_dir(data, repo, feat), 'state.json')
    if os.path.exists(path) and load(data, repo, feat) is None:
        return ('egm-runbook WARNING: state file for feature %s is unreadable (%s); the design gate is OFF '
                'until it is fixed or restarted with runbook start %s --force.' % (feat, path, feat))
    return ''


def hook_session_start(event, data):
    ctx_lines = []
    warn = unreadable_warning(event, data)
    if warn:
        ctx_lines.append(warn)
    st = active_state(event, data)
    if st:
        steps = detect(st)
        ctx_lines.append(one_liner(st))
        if not gate_open(st, steps):
            ctx_lines.append("Design work for this feature uses egm; don't use superpowers:brainstorming.")
            ctx_lines.append('No code may be written until the egm review is concluded (steps 1-4).')
            ctx_lines.append(gate_hint(st))
    banner = alerts_banner()
    if not ctx_lines and not banner:
        return
    out = {}
    if banner:
        out['systemMessage'] = banner
        ctx_lines.append(banner)
    out['hookSpecificOutput'] = {'hookEventName': 'SessionStart', 'additionalContext': '\n'.join(ctx_lines)}
    emit(out)


def hook_prompt(event, data):
    lines = [unreadable_warning(event, data)]
    st = active_state(event, data)
    if st:
        lines.append(one_liner(st))
    lines = [x for x in lines if x]
    if lines:
        emit({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': '\n'.join(lines)}})


def deny(reason):
    emit({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                 'permissionDecisionReason': reason}})


def is_code_in_repo(path, repo, cwd):
    p = path if os.path.isabs(path) else os.path.join(cwd or repo, path)
    p = os.path.realpath(p)
    try:
        rel = os.path.relpath(p, repo)
    except ValueError:
        return False
    if rel.startswith('..'):
        return False
    if os.path.splitext(rel)[1].lower() not in CODE_EXT and os.path.basename(rel).lower() not in CODE_NAMES:
        return False
    rel = rel.replace(os.sep, '/')
    art = egm_artifact_dir(repo)
    if rel.startswith('docs/'):
        return False
    if art != '.' and (rel + '/').startswith(art.strip('/') + '/'):
        return False
    return True


def data_paths(data):
    """Paths Claude must not touch: the data dir and the pointer file's folder."""
    home = os.path.expanduser('~')
    paths = {os.path.realpath(data), os.path.abspath(data), os.path.dirname(pointer_file())}
    return paths, home


def touches_state(path, data, cwd):
    p = path if os.path.isabs(path) else os.path.join(cwd or os.getcwd(), path)
    p = os.path.realpath(os.path.expanduser(p))
    paths, _ = data_paths(data)
    return any(p == q or p.startswith(q.rstrip(os.sep) + os.sep) for q in map(os.path.realpath, paths))


DATA_DIR_FLAG = re.compile(
    r"""--data-dir(?:=|\s+)(?:"([^"]*)"|'([^']*)'|([^\s;|&><()`"']+))(?=\s|$)""")
DATA_DIR_LITERALS = ('${CLAUDE_PLUGIN_DATA}', '$CLAUDE_PLUGIN_DATA')


def strip_exempt_data_dir(text, data):
    """Blank out `--data-dir <value>` only when the value is exactly the real data dir or the literal
    CLAUDE_PLUGIN_DATA variable, bare or as one quoted token, and nothing shell-active follows it."""
    allowed = {data, os.path.realpath(data)} | set(DATA_DIR_LITERALS)

    def sub(m):
        value = next(g for g in m.groups() if g is not None)
        return ' ' if value in allowed else m.group(0)
    return DATA_DIR_FLAG.sub(sub, text)


def mentions_state(text, data):
    """True when a shell command text names the data dir or the pointer file."""
    text = strip_exempt_data_dir(text, data)
    if re.search(r'\$\{?CLAUDE_PLUGIN_DATA\b', text):
        return True
    paths, home = data_paths(data)
    needles = set(paths)
    for q in list(paths):
        if q.startswith(home + os.sep):
            needles.add('~' + q[len(home):])
            needles.add('$HOME' + q[len(home):])
    return any(n in text for n in needles)


VALUE_OPTS = ('--data-dir', '--cwd', '--reason')
SHELLS = ('bash', 'sh', 'zsh', 'dash', 'ksh')
MAX_DEPTH = 4
MAX_RESCANS = 64
GLOB_CHARS = '*?['
TOO_COMPLEX = 'command too complex for the runbook gate check; ask the user to run it'
ANSI_SIMPLE = {'a': '\a', 'b': '\b', 'e': '\x1b', 'E': '\x1b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t',
               'v': '\v', '\\': '\\', "'": "'", '"': '"', '?': '?'}
REDIRECT = re.compile(r'^(?:\d+|&)?(>>|>&|>\||>|<<<|<&|<>|<)(.*)$', re.S)


class _Budget:
    """Caps the nested rescans (substitutions, here-doc bodies, sh -c, eval) of one hook call."""

    def __init__(self):
        self.left = MAX_RESCANS
        self.exceeded = False

    def spend(self):
        if self.left <= 0:
            self.exceeded = True
            return False
        self.left -= 1
        return True


def _matching(text, i, open_ch, close_ch):
    depth = 0
    for j in range(i, len(text)):
        if text[j] == open_ch:
            depth += 1
        elif text[j] == close_ch:
            depth -= 1
            if depth == 0:
                return j
    return len(text)


def _ansi_c(text, i):
    """Decode the body of $'...' starting at i (just after the opening quote); return (string, next index)."""
    out, n = [], len(text)
    while i < n and text[i] != "'":
        c = text[i]
        if c == '\\' and i + 1 < n:
            e = text[i + 1]
            if e in ANSI_SIMPLE:
                out.append(ANSI_SIMPLE[e])
                i += 2
                continue
            m = re.match(r'x[0-9a-fA-F]{1,2}|u[0-9a-fA-F]{1,4}|U[0-9a-fA-F]{1,8}|[0-7]{1,3}', text[i + 1:])
            if m:
                g = m.group()
                try:
                    out.append(chr(int(g[1:], 16) if g[0] in 'xuU' else int(g, 8)))
                except (ValueError, OverflowError):
                    pass
                i += 1 + len(g)
                continue
            out.append(c + e)
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out), i + 1


def _substitution_cmds(body, depth, budget):
    """Commands inside $( ) and backticks of text that the shell expands (an unquoted here-doc body)."""
    cmds = []
    i = 0
    while i < len(body):
        if body.startswith('$(', i):
            if depth >= MAX_DEPTH or not budget.spend():
                budget.exceeded = True
                return cmds
            inner, i = _parse(body, i + 2, ')', depth + 1, budget)
            cmds.extend(inner)
        elif body[i] == '`':
            if depth >= MAX_DEPTH or not budget.spend():
                budget.exceeded = True
                return cmds
            j = body.find('`', i + 1)
            j = len(body) if j < 0 else j
            cmds.extend(_parse(body[i + 1:j], 0, None, depth + 1, budget)[0])
            i = j + 1
        else:
            i += 1
    return cmds


def _parse(text, i, stop, depth, budget):
    """Split shell text into simple commands: lists of (word, quoted) pairs. Command substitutions become
    commands of their own; here-doc bodies are skipped (scanned only when fed to a shell, or when the
    delimiter is unquoted and so the shell expands substitutions in them). Backslash-newline is dropped as
    the shell does, $'...' is decoded, and redirection operators (2>&1, >&, &>) stay in their word.
    Returns (commands, next index). Approximate: it exists to find words and where quoting hides them."""
    cmds, words, buf, had = [], [], [], False
    pending = []  # here-docs waiting for the next newline: (delimiter, strip_tabs, delimiter_quoted, words)
    n = len(text)

    def flush():
        nonlocal buf, had
        if buf or had:
            words.append((''.join(buf), had))
        buf, had = [], False

    def end_cmd():
        nonlocal words
        flush()
        if words:
            cmds.append(words)
        words = []

    def substitution(i):
        paren = text.startswith('$(', i)
        if depth >= MAX_DEPTH or not budget.spend():
            budget.exceeded = True
            if paren:
                return _matching(text, i + 1, '(', ')') + 1
            j = text.find('`', i + 1)
            return (n if j < 0 else j) + 1
        if paren:
            inner, j = _parse(text, i + 2, ')', depth + 1, budget)
            cmds.extend(inner)
            return j
        j = text.find('`', i + 1)
        j = n if j < 0 else j
        cmds.extend(_parse(text[i + 1:j], 0, None, depth + 1, budget)[0])
        return j + 1

    while i < n:
        c = text[i]
        if c == ')' and stop == ')':
            end_cmd()
            return cmds, i + 1
        if c == "'":
            j = text.find("'", i + 1)
            j = n if j < 0 else j
            buf.append(text[i + 1:j])
            had = True
            i = j + 1
        elif c == '"':
            had = True
            i += 1
            while i < n and text[i] != '"':
                if text[i] == '\\' and text.startswith('\n', i + 1):
                    i += 2
                elif text[i] == '\\' and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                elif text.startswith('$(', i) or text[i] == '`':
                    i = substitution(i)
                else:
                    buf.append(text[i])
                    i += 1
            i += 1
        elif c == '\\' and text.startswith('\n', i + 1):
            i += 2  # line continuation: the shell removes it and the word goes on
        elif c == '\\' and i + 1 < n:
            buf.append(text[i + 1])
            had = True
            i += 2
        elif c == '$' and text.startswith("$'", i):
            dec, i = _ansi_c(text, i + 2)
            buf.append(dec)
            had = True
        elif c == '$' and text.startswith('$"', i):
            i += 1
        elif text.startswith('$(', i) or c == '`':
            i = substitution(i)
        elif text.startswith('<<<', i):
            buf.append('<<<')  # here-string: a redirection, not a here-doc
            i += 3
        elif c == '<' and text.startswith('<<', i):
            j, strip = i + 2, False
            if text[j:j + 1] == '-':
                strip, j = True, j + 1
            while j < n and text[j] in ' \t':
                j += 1
            m = re.match(r"""(['"])(.*?)\1|(\\?)([A-Za-z0-9_]+)""", text[j:])
            flush()
            if m:
                delim = m.group(2) if m.group(1) else m.group(4)
                pending.append((delim, strip, bool(m.group(1) or m.group(3)), words))
                i = j + m.end()
            else:
                i += 2
        elif c == '\n':
            end_cmd()
            i += 1
            for delim, strip, delim_quoted, owner in pending:
                lines = []
                while i < n:
                    eol = text.find('\n', i)
                    line = text[i:n if eol < 0 else eol]
                    i = n if eol < 0 else eol + 1
                    candidate = line.rstrip('\r')
                    if (candidate.lstrip('\t') if strip else candidate) == delim:
                        break
                    lines.append(line)
                body = '\n'.join(lines)
                if any(os.path.basename(w) in SHELLS for w, _ in owner):
                    if depth >= MAX_DEPTH or not budget.spend():
                        budget.exceeded = True
                    else:
                        cmds.extend(_parse(body, 0, None, depth + 1, budget)[0])  # the body is a script
                elif not delim_quoted:
                    cmds.extend(_substitution_cmds(body, depth, budget))
            pending = []
        elif c == '#' and not buf and not had:
            while i < n and text[i] != '\n':
                i += 1
        elif c in ' \t':
            flush()
            i += 1
        elif c == '&' and ((i > 0 and text[i - 1] in '<>') or text.startswith('&>', i)):
            buf.append(c)  # part of a redirection: >&, <&, &>
            i += 1
        elif c in ';&|()':
            end_cmd()
            i += 1
        else:
            buf.append(c)
            i += 1
    end_cmd()
    return cmds, n


def is_runbook_token(word, quoted):
    """A token that names the script: basename runbook.py or runbook (quoted or not), or an unquoted glob
    that can match runbook.py."""
    base = os.path.basename(word)
    if base in ('runbook.py', 'runbook'):
        return True
    return not quoted and any(ch in base for ch in GLOB_CHARS) and fnmatch.fnmatchcase('runbook.py', base)


def strip_redirects(pairs):
    """Argument texts with redirection operators and their targets removed (`2>&1`, `>f`, `> f`, `<<<x`)."""
    out, skip = [], False
    for w, quoted in pairs:
        if skip:
            skip = False
            continue
        m = REDIRECT.match(w) if (not quoted or w.startswith('<<<')) else None
        if m:
            skip = m.group(2) == ''
            continue
        out.append(w)
    return out


def _calls(command, depth, budget):
    for seg in _parse(command, 0, None, depth, budget)[0]:
        texts = [w for w, _ in seg]
        for k, (w, quoted) in enumerate(seg):
            if is_runbook_token(w, quoted):
                yield strip_redirects(seg[k + 1:])
            base = os.path.basename(w)
            if base in SHELLS:
                for j in range(k + 1, len(texts) - 1):
                    t = texts[j]
                    if t.startswith('-') and not t.startswith('--') and 'c' in t:
                        m = j + 1
                        while m < len(texts) - 1 and texts[m].startswith('-'):
                            m += 1
                        if depth >= MAX_DEPTH or not budget.spend():
                            budget.exceeded = True
                        else:
                            yield from _calls(texts[m], depth + 1, budget)
                        break
            elif base == 'eval' and not quoted:
                if depth >= MAX_DEPTH or not budget.spend():
                    budget.exceeded = True
                    return
                yield from _calls(' '.join(texts[k + 1:]), depth + 1, budget)


def scan_runbook_calls(command):
    """Return (list of argument lists that follow a runbook token, too_complex).

    Any token whose basename is runbook.py or runbook counts, anywhere in the command (no command position,
    no wrapper list); other quoted tokens (commit messages, grep patterns, echo text) are ignored. The string
    given to `sh -c`/`bash -c` and the arguments of `eval` are scanned again as shell text, as are `$( )`,
    backticks and the here-docs fed to a shell. The nesting depth and the number of rescans are capped;
    too_complex is True when a cap was hit."""
    budget = _Budget()
    calls = list(_calls(command, 0, budget))
    return calls, budget.exceeded


def gate_change(args, gate_is_open):
    """Return (description, rest-of-command for the user) when these runbook args open, bypass or erase the gate."""
    pos, flags, i = [], [], 0
    while i < len(args):
        t = args[i]
        name = t.split('=')[0]
        if t.startswith('--') and len(name) > 2:
            # The CLI rejects abbreviations, but treat any prefix of a known option as that option.
            if any(v.startswith(name) for v in VALUE_OPTS) and '=' not in t:
                i += 1
            if '--force'.startswith(name):
                flags.append('--force')
        elif not t.startswith('-'):
            pos.append(t)
        i += 1
    if not pos:
        return None
    sub = pos[0]
    if sub == 'skip':
        return 'skip', 'skip gate --reason "..."'
    if sub == 'done':
        step = pos[1] if len(pos) > 1 else ''
        try:
            n = parse_step(step)
        except SystemExit:
            return 'done %s' % step, 'done <step> --reason "..."'
        if n == 'gate' or n <= GATE_LAST:
            return 'done %s' % step, 'done %s --reason "..."' % step
    elif sub == 'record':
        art = pos[1] if len(pos) > 1 else ''
        if art not in ('plan', 'deep-review', 'drift'):
            return 'record %s' % art, 'record %s <path>' % (art or '<artifact>')
    elif sub == 'start' and '--force' in flags:
        return 'start --force', 'start %s --force' % (pos[1] if len(pos) > 1 else '<feature>')
    elif sub in ('finish', 'switch') and not gate_is_open:
        return sub, sub + (' %s' % pos[1] if sub == 'switch' and len(pos) > 1 else '')
    return None


def user_only(why, rest):
    return ('egm-runbook: blocked, %s. Gate overrides must come from the user, not from Claude. '
            'Do not retry or work around it. Ask the user to type this at the prompt: %s' % (why, ucmd(rest)))


def hook_pretool(event, data):
    st = active_state(event, data)
    if not st:
        return
    tool = event.get('tool_name')
    ti = event.get('tool_input') or {}
    is_open = gate_open(st)
    if tool == 'Bash':
        command = str(ti.get('command') or '')
        calls, too_complex = scan_runbook_calls(command)
        for args in calls:
            hit = gate_change(args, is_open)
            if hit:
                deny(user_only('`runbook %s` changes or bypasses the design gate' % hit[0], hit[1]))
                return
        if too_complex:
            deny('egm-runbook: ' + TOO_COMPLEX)
            return
        if mentions_state(command, data):
            deny(user_only('the command names the runbook state location and could edit the gate state directly',
                           'done <step> --reason "..."'))
        return
    if tool in ('Write', 'Edit', 'MultiEdit', 'NotebookEdit'):
        path = ti.get('file_path') or ti.get('notebook_path')
        if path and touches_state(str(path), data, event.get('cwd')):
            deny(user_only('writing to the runbook state would edit the gate state directly',
                           'done <step> --reason "..."'))
            return
    if is_open:
        return
    how = ('The design gate is closed. Ask the user whether to finish the egm steps (1-4) or to override the '
           'gate; do not override it yourself. ' + gate_hint(st))
    if tool == 'Skill':
        raw = str(ti.get('skill') or '').strip().lstrip('/')
        bare = raw.split(':')[-1]
        names = {raw}
        if ':' not in raw:  # tolerate an unprefixed skill name
            names |= {'superpowers:' + raw, 'build-loop:' + raw}
        if bare == 'build-loop':
            names.add('build-loop:build-loop')
        if names & BLOCKED_SKILLS:
            deny('egm-runbook: %s is blocked while feature %s is in the design steps (1-4, egm review not concluded). %s'
                 % (raw, st['feature'], how))
        elif BRAINSTORM_SKILL in names:
            deny('egm-runbook: design work for feature %s uses egm. Ask the user to type /egm:egm-brainstorm '
                 'instead of using superpowers:brainstorming. %s' % (st['feature'], how))
    elif tool in ('Write', 'Edit', 'MultiEdit', 'NotebookEdit'):
        path = ti.get('file_path') or ti.get('notebook_path')
        repo = st['repo']
        if path and is_code_in_repo(str(path), repo, event.get('cwd')):
            deny('egm-runbook: no code may be written in steps 1-4 (egm design, review not concluded) '
                 'for feature %s; blocked %s. Markdown, docs/ and the egm artifact directory are allowed. %s'
                 % (st['feature'], path, how))


def statusline_text(event, data):
    cwd = event.get('cwd') or (event.get('workspace') or {}).get('current_dir')
    st = active_state({'cwd': cwd}, data)
    if not st:
        return ''
    n = current_step(st)
    return 'runbook: %s · %s' % (st['feature'], 'done' if n is None else '%d/9 %s' % (n, STEPS[n][0]))


def cmd_hook(a):
    try:
        event = hook_event()
        try:
            remember_data_dir()
        except Exception:  # an unwritable pointer must never switch the hook off
            pass
        data = data_dir(a.data_dir)
        {'session-start': hook_session_start, 'user-prompt': hook_prompt,
         'pre-tool-use': hook_pretool}[a.event](event, data)
    except Exception:  # hooks fail open: never wedge a session
        pass
    return 0


def statusline_main(argv=None):
    try:
        ap = argparse.ArgumentParser()
        ap.add_argument('--data-dir')
        a, _ = ap.parse_known_args(argv)
        sys.stdout.write(statusline_text(hook_event(), data_dir(a.data_dir)))
    except Exception:
        pass
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog='runbook', allow_abbrev=False)
    p.add_argument('--data-dir')
    p.add_argument('--cwd', help='directory inside the repo (default: current directory)')
    sub = p.add_subparsers(dest='cmd', required=True)
    for name, fn, argspec in [
        ('start', cmd_start, ['feature']), ('status', cmd_status, []), ('next', cmd_next, []),
        ('record', cmd_record, ['artifact', 'path']), ('done', cmd_done, ['step']),
        ('skip', cmd_skip, ['step']), ('switch', cmd_switch, ['feature']), ('finish', cmd_finish, []),
    ]:
        sp = sub.add_parser(name, allow_abbrev=False)
        for x in argspec:
            sp.add_argument(x)
        if name == 'skip':
            sp.add_argument('--reason', required=True)
        if name == 'done':
            sp.add_argument('--reason', help='required for steps 1-4; logged as a completion override')
        if name == 'start':
            sp.add_argument('--force', action='store_true', help='reset an existing feature')
        sp.set_defaults(fn=fn)
    hp = sub.add_parser('hook', allow_abbrev=False)
    hp.add_argument('event', choices=['session-start', 'user-prompt', 'pre-tool-use'])
    hp.set_defaults(fn=cmd_hook)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    return a.fn(a) or 0


if __name__ == '__main__':
    sys.exit(main())
