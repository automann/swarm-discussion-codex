/**
 * Host adapter "managed entry" helpers — shared between Codex and Claude
 * targets because the entry shape is identical:
 *
 *   { matcher?: string, hooks: [{ type: 'command', command: string }] }
 *
 * The managed tag substring inside each command string identifies entries the
 * repo-harness installer wrote, so install can be idempotent and uninstall can
 * remove only its own entries (leaving sibling user hooks intact — verified
 * for Claude in Phase 0: `~/.claude/settings.json` already had a non-
 * repo-harness `rtk hook claude` entry that must survive install).
 *
 * User-scope command shape keeps the `command -v local-repo-harness || exit 0` shim
 * (Codex consult constraint #5: CLI-missing fallback). Project-scope command
 * shape uses the repo-owned `.ai/harness/bin/local-repo-harness-hook` runtime.
 */

import { ROUTES, type Route } from '../hook/route-registry';
import {
  MANAGED_ENV_TAG,
  buildHookCommand,
  type RuntimeMode,
} from './hook-command';

export const MANAGED_TAG = MANAGED_ENV_TAG;
export const LEGACY_MANAGED_TAG = 'local-repo-harness hook';

export interface HookCommand {
  type: 'command';
  command: string;
  timeout: number;
}

export interface HookEntry {
  matcher?: string;
  hooks: HookCommand[];
}

export type HooksByEvent = Record<string, HookEntry[]>;
export type HookHost = 'claude' | 'codex';

export interface BuildManagedHooksOptions {
  runtimeMode?: RuntimeMode;
}

export function buildHookEntry(
  route: Route,
  host: HookHost,
  opts: BuildManagedHooksOptions = {},
): HookEntry {
  const runtimeMode = opts.runtimeMode ?? 'global-path';
  const entry: HookEntry = {
    hooks: [{
      type: 'command',
      command: buildHookCommand({ route, host, runtimeMode }),
      timeout: 30,
    }],
  };
  if (route.matcher !== undefined) entry.matcher = route.matcher;
  return entry;
}

export function isManagedEntry(entry: HookEntry): boolean {
  if (!entry || !Array.isArray(entry.hooks)) return false;
  return entry.hooks.some((h) => (
    typeof h?.command === 'string' &&
    (h.command.includes(MANAGED_TAG) || h.command.includes(LEGACY_MANAGED_TAG))
  ));
}

export function buildManagedHooks(
  host: HookHost,
  opts: BuildManagedHooksOptions = {},
): HooksByEvent {
  const out: HooksByEvent = {};
  for (const route of ROUTES) {
    if (!out[route.event]) out[route.event] = [];
    out[route.event].push(buildHookEntry(route, host, opts));
  }
  return out;
}

export function stripManagedEntries(existing: HooksByEvent | undefined): HooksByEvent {
  if (!existing) return {};
  const out: HooksByEvent = {};
  for (const [event, entries] of Object.entries(existing)) {
    const kept = (entries ?? []).filter((e) => !isManagedEntry(e));
    if (kept.length > 0) out[event] = kept;
  }
  return out;
}

export function mergeHooks(existing: HooksByEvent, managed: HooksByEvent): HooksByEvent {
  const out: HooksByEvent = { ...existing };
  for (const [event, managedEntries] of Object.entries(managed)) {
    out[event] = [...(out[event] ?? []), ...managedEntries];
  }
  return out;
}
