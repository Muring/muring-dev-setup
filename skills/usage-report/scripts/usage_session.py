"""Verify caller-supplied session identity against local transcript metadata only."""
import json
import os
from pathlib import Path
import re

from usage_store import digest, resolve_project


def identify(config, tool, session_id=None, transcript=None, hook_input=None):
    unknown = lambda reason: dict(state='unknown', reason=reason, session=None, project=None)
    if hook_input:
        if tool != 'Claude':
            raise ValueError('hook input is supported for Claude only')
        hook = json.loads(Path(hook_input).read_text(encoding='utf-8'))
        if hook.get('agent_id'):
            return unknown('subagent_hook_requires_separate_identity')
        if not hook.get('session_id') or not hook.get('transcript_path'):
            return unknown('incomplete_hook_identity')
        if session_id and session_id != hook['session_id']:
            return unknown('conflicting_session_ids')
        if transcript and Path(transcript).resolve() != Path(hook['transcript_path']).resolve():
            return unknown('conflicting_transcripts')
        session_id, transcript = hook['session_id'], hook['transcript_path']
    if tool == 'Codex':
        ids = {v for v in (os.environ.get('CODEX_SESSION_ID'), os.environ.get('CODEX_THREAD_ID'), session_id) if v}
        if len(ids) > 1:
            return unknown('conflicting_session_ids')
        session_id = next(iter(ids), None)
    # Claude has no assumed universal session environment variable. Use a supplied
    # session ID (e.g. hook input) and verify it; never choose the newest transcript.
    if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', session_id):
        return unknown('session_id_unavailable')
    roots = [Path(r['path']).expanduser().resolve() for r in config['roots'] if r['tool'] == tool]
    if transcript:
        paths = [Path(transcript).expanduser().resolve()]
        if not any(paths[0].is_relative_to(root) for root in roots):
            return unknown('transcript_outside_configured_roots')
    else:
        paths = sorted({p.resolve() for root in roots if root.is_dir()
                        for p in root.rglob('*' + session_id + '*.jsonl')})
    matches = set()
    for path in paths:
        if 'subagents' in path.parts:
            continue
        ids, cwd = set(), None
        try:
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    row = json.loads(line)
                    if tool == 'Codex' and row.get('type') == 'session_meta':
                        meta = row.get('payload') or {}
                        ids.add(meta.get('id'))
                        cwd = meta.get('cwd') or cwd
                    elif tool == 'Claude':
                        if row.get('sessionId'):
                            ids.add(row['sessionId'])
                        cwd = cwd or row.get('cwd')
        except (OSError, ValueError):
            return unknown('transcript_unreadable_or_active_write')
        if ids == {session_id} and cwd:
            matches.add(cwd)
        elif ids:
            return unknown('transcript_identity_mismatch')
    if len(matches) != 1:
        return unknown('metadata_missing_or_ambiguous')
    cwd = next(iter(matches))
    project = resolve_project(cwd, config['projects'])
    if project == 'unmapped':
        return unknown('source_project_unmapped')
    return dict(state='verified', session=digest([tool, session_id]), project=project)
