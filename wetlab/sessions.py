"""Native state readers and recovery adapters; see the report for live verification status."""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path
try:
    from .advanced import ADVANCED, advanced_session, advanced_history, validate_advanced, advanced_bundle
except ImportError:
    from advanced import ADVANCED, advanced_session, advanced_history, validate_advanced, advanced_bundle

NATIVE_IMPORT = {'claude-code', 'codex', 'muse-code'}
FILESYSTEM_RESUME = {'pi', 'qwen-coder', 'opencode', 'mimo', 'goose', 'copilot-cli', 'kimi-code', 'hermes'}
OPENCODE_FORMAT = {'opencode', 'mimo'}
SUPPORTED = NATIVE_IMPORT | FILESYSTEM_RESUME | ADVANCED


def version_output(output: str) -> str:
    """Harbor's Docker exec can merge diagnostics into stdout; keep version lines."""
    return '\n'.join(line for line in output.splitlines() if line.strip()
                     and not re.match(r'^\s*(?:WARNING|WARN|ERROR|DEBUG)\b', line, re.I))


def require_supported(agent: str) -> None:
    if agent=='dspy-rlm':
        raise ValueError('wetlab native recovery is not implemented for dspy-rlm: DSPy native interpreters lose the Python namespace on cold restart and expose no state export/import protocol; replaying code could repeat experiments. No experiment was submitted.')
    if agent not in SUPPORTED:
        raise ValueError(f"wetlab native recovery is not implemented for {agent!r}; "
                         f"supported adapters: {', '.join(sorted(SUPPORTED))}. No experiment was submitted.")


def latest_session(trial: Path, agent: str = 'claude-code') -> Path | None:
    require_supported(agent)
    if agent in ADVANCED: return advanced_session(trial,agent)
    root = trial / 'agent'
    if agent == 'claude-code':
        files = list((root / 'sessions/projects').glob('*/*.jsonl'))
    elif agent == 'codex':
        files = list((root / 'sessions').rglob('rollout-*.jsonl'))
    elif agent == 'pi':
        files = list((root / 'pi/sessions').glob('*.jsonl'))
    elif agent == 'qwen-coder':
        # Harbor's cp -r export nests projects/ once the destination exists.
        files = list((root / 'qwen-sessions').glob('**/chats/*.jsonl'))
    elif agent == 'opencode':
        files = list((root / 'opencode/xdg-data/opencode').glob('opencode.db'))
    elif agent == 'mimo':
        files = list((root / 'mimo/xdg-data/mimocode').glob('mimocode.db'))
    elif agent == 'goose':
        files = list((root / 'goose/xdg-data/goose/sessions').glob('sessions.db'))
    elif agent == 'copilot-cli':
        files = list((root / 'copilot/session-state').glob('*/events.jsonl'))
    elif agent == 'kimi-code':
        files = list((root / '.kimi-code/sessions').glob('*/session_*/agents/main/wire.jsonl'))
    elif agent == 'hermes':
        files = [root / 'hermes-session.jsonl'] if (root / 'hermes-session.jsonl').is_file() else []
    else:
        manifest = root / 'muse-session.json'
        if not manifest.exists():
            return None
        sid = json.loads(manifest.read_text())['session_id']
        files = list((root / 'sessions').glob(f'*/*/*/{sid}/session.jsonl'))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def session_bundle_root(path: Path, agent: str) -> Path:
    if agent in ADVANCED:return advanced_bundle(path,agent)
    # Kimi's state.json is beside agents/, not beside its main wire stream.
    return path.parents[2] if agent == 'kimi-code' else path.parent


def native_history(path: Path, agent: str) -> tuple[str, dict]:
    """Stable native identity and original messages, for continuation attestation.

    OpenCode updates token accounting and summaries on earlier messages. Its native
    parts carry the actual text/tool context; compare those and the message IDs.
    JSONL formats are append-only, so every original record must survive exactly.
    """
    if agent in ADVANCED: return advanced_history(path,agent)
    if agent in OPENCODE_FORMAT:
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            sid = db.execute('SELECT id FROM session WHERE parent_id IS NULL '
                             'ORDER BY time_updated DESC LIMIT 1').fetchone()
            if not sid: raise ValueError('missing OpenCode session identity')
            sid = sid[0]
            parts = {f'part:{i}': json.loads(data) for i, data in
                     db.execute('SELECT id,data FROM part WHERE session_id=?', (sid,))}
            messages = {f'message:{i}': json.loads(data)['role'] for i, data in
                        db.execute('SELECT id,data FROM message WHERE session_id=?', (sid,))}
            return sid, parts | messages
    if agent == 'goose':
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            sid = db.execute('SELECT id FROM sessions WHERE parent_session_id IS NULL '
                             'ORDER BY updated_at DESC,id DESC LIMIT 1').fetchone()
            if not sid: raise ValueError('missing Goose session identity')
            return sid[0], {str(i): {'role': role, 'content': json.loads(content)} for i, role, content in
                            db.execute('SELECT id,role,content_json FROM messages WHERE session_id=? ORDER BY id', sid)}
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    if not rows: raise ValueError('empty native session')
    if agent == 'hermes':
        rec = rows[0]
        if not rec.get('id') or not isinstance(rec.get('messages'), list):
            raise ValueError('missing Hermes native identity/messages')
        return rec['id'], {str(i): msg for i, msg in enumerate(rec['messages'])}
    if agent == 'kimi-code':
        meta = json.loads((session_bundle_root(path, agent) / 'state.json').read_text())
        sid = meta.get('id')
        if meta.get('cwd') is None: raise ValueError('missing Kimi Code workspace')
    elif agent == 'copilot-cli':
        sid = rows[0].get('data', {}).get('sessionId')
    else:
        sid = rows[0].get('id') if agent == 'pi' else rows[0].get('sessionId')
    if not sid: raise ValueError('missing native session identity')
    if agent == 'qwen-coder' and any(r.get('sessionId', sid) != sid for r in rows):
        raise ValueError('mixed native session identities')
    return sid, {str(i): row for i, row in enumerate(rows)}


def assert_continuation(previous: Path, current: Path, agent: str) -> None:
    old_id, old = native_history(previous, agent)
    new_id, new = native_history(current, agent)
    if old_id != new_id or any(new.get(k) != v for k, v in old.items()):
        raise ValueError('native session identity or previous context changed during continuation')
    if len(new) <= len(old):
        raise ValueError('native session contains no new continuation events')


def validate_session(path: Path, agent: str = 'claude-code') -> tuple[bool, str]:
    try:
        require_supported(agent)
        if agent in ADVANCED:
            validate_advanced(path,agent)
            return True, 'ok'
        if agent in OPENCODE_FORMAT:
            sid, history = native_history(path, agent)
            with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('corrupt OpenCode database')
                row = db.execute('SELECT data FROM message WHERE session_id=? '
                                 'ORDER BY time_created DESC,id DESC LIMIT 1', (sid,)).fetchone()
            last = json.loads(row[0]) if row else {}
            if last.get('role') != 'assistant' or last.get('finish') != 'stop' or not last.get('time', {}).get('completed'):
                raise ValueError('OpenCode session has no completed assistant turn')
            if any(v.get('type') == 'tool' and v.get('state', {}).get('status') not in ('completed', 'error')
                   for v in history.values() if isinstance(v, dict)):
                raise ValueError('unfinished OpenCode tool call')
            return True, 'ok'
        if agent == 'goose':
            _, history = native_history(path, agent)
            if not history: raise ValueError('empty Goose native history')
            last = list(history.values())[-1]
            calls, results = set(), set()
            for msg in history.values():
                for part in msg['content']:
                    if part.get('type') == 'error': raise ValueError('Goose native session contains an error')
                    if part.get('type') == 'toolRequest': calls.add(part['id'])
                    if part.get('type') == 'toolResponse': results.add(part['id'])
            if calls - results: raise ValueError('unfinished Goose tool call')
            # Goose's platform todo extension can request another model turn
            # after submission. Its native resume accepts a fully resolved tool
            # response boundary; no tool may still be executing at suspension.
            resolved_tool_boundary = last['role'] == 'user' and bool(last['content']) and all(
                p.get('type') == 'toolResponse' for p in last['content'])
            if last['role'] != 'assistant' and not resolved_tool_boundary:
                raise ValueError('Goose session has no completed turn or resolved tool boundary')
            return True, 'ok'
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if not records:
            raise ValueError('empty native session')
        calls, results = set(), set()
        if agent == 'claude-code':
            messages = [r['message'] for r in records if isinstance(r.get('message'), dict)
                        and not r.get('isSidechain')]
            if not any(r.get('sessionId') for r in records):
                raise ValueError('missing Claude session identity')
            for msg in messages:
                for c in msg.get('content', []) if isinstance(msg.get('content'), list) else []:
                    if c.get('type') == 'tool_use': calls.add(c['id'])
                    if c.get('type') == 'tool_result': results.add(c['tool_use_id'])
            if not messages or messages[-1].get('role') != 'assistant' or messages[-1].get('stop_reason') != 'end_turn':
                raise ValueError('Claude session has no completed assistant turn')
        elif agent == 'codex':
            if records[0].get('type') != 'session_meta' or not records[0].get('payload', {}).get('id'):
                raise ValueError('missing Codex session metadata')
            for rec in records:
                if rec.get('type') != 'response_item': continue
                item = rec.get('payload', {})
                if item.get('type') in ('function_call', 'custom_tool_call'): calls.add(item['call_id'])
                if item.get('type') in ('function_call_output', 'custom_tool_call_output'): results.add(item['call_id'])
            if not any(r.get('type') == 'event_msg' and r.get('payload', {}).get('type') == 'task_complete' for r in records[-12:]):
                raise ValueError('Codex session has no completed turn')
        elif agent == 'pi':
            native_history(path, agent)
            if records[0].get('type') != 'session' or not records[0].get('cwd'):
                raise ValueError('missing Pi workspace/session header')
            # Pi can branch: validate the active ancestry rather than discarded branches.
            from harbor.agents.installed.pi import Pi
            active = Pi._active_session_events(list(enumerate(records)))
            messages = [r['message'] for _, r in active if r.get('type') == 'message']
            for msg in messages:
                if msg.get('role') == 'toolResult': results.add(msg['toolCallId'])
                for c in msg.get('content', []) if isinstance(msg.get('content'), list) else []:
                    if c.get('type') == 'toolCall': calls.add(c['id'])
            if not messages or messages[-1].get('role') != 'assistant' or messages[-1].get('stopReason') != 'stop':
                raise ValueError('Pi session has no completed assistant turn')
        elif agent == 'qwen-coder':
            native_history(path, agent)
            messages = [r for r in records if isinstance(r.get('message'), dict)]
            for rec in messages:
                for part in rec['message'].get('parts', []):
                    if 'functionCall' in part: calls.add(part['functionCall']['id'])
                    if 'functionResponse' in part: results.add(part['functionResponse']['id'])
            if not messages or messages[-1].get('type') != 'assistant' or any('functionCall' in p for p in messages[-1]['message'].get('parts', [])):
                raise ValueError('Qwen session has no completed assistant turn')
        elif agent == 'copilot-cli':
            native_history(path, agent)
            end = max((i for i, r in enumerate(records) if r.get('type') == 'assistant.turn_end'), default=-1)
            start = max((i for i, r in enumerate(records) if r.get('type') in ('assistant.turn_start', 'user.message')), default=-1)
            if end <= start:
                raise ValueError('Copilot session has no completed assistant turn')
            for rec in records:
                if rec.get('type') == 'tool.execution_start': calls.add(rec['data']['toolCallId'])
                if rec.get('type') == 'tool.execution_complete': results.add(rec['data']['toolCallId'])
        elif agent == 'kimi-code':
            native_history(path, agent)
            end = max((i for i, r in enumerate(records) if r.get('type') == 'prompt.completed' and r.get('reason') == 'completed'), default=-1)
            start = max((i for i, r in enumerate(records) if r.get('type') in ('turn.prompt', 'agent.turn.started')), default=-1)
            if end <= start:
                raise ValueError('Kimi Code session has no completed prompt')
            for rec in records:
                if rec.get('type') != 'agent.message.appended': continue
                msg = rec.get('message', {}).get('message', {})
                for call in msg.get('toolCalls', []): calls.add(call['id'])
                if msg.get('role') == 'tool': results.add(msg['toolCallId'])
        elif agent == 'hermes':
            _, history = native_history(path, agent)
            messages = list(history.values())
            for msg in messages:
                for call in msg.get('tool_calls') or []: calls.add(call['id'])
                if msg.get('role') == 'tool': results.add(msg['tool_call_id'])
            if not messages or messages[-1].get('role') != 'assistant' or messages[-1].get('tool_calls'):
                raise ValueError('Hermes session has no completed assistant turn')
        else:
            # Muse's own importer validates stream identity and workspace metadata.
            from harbor.agents.installed.muse_code import MuseCode
            rows = MuseCode._read_session(path)
            MuseCode._native_session_id(rows)
            if not MuseCode._session_metadata(rows).get('workspace_root'):
                raise ValueError('missing Muse workspace metadata')
        if calls - results:
            raise ValueError(f'{len(calls - results)} unfinished native tool calls')
        return True, 'ok'
    except Exception as exc:
        return False, f'{type(exc).__name__}: {exc}'
