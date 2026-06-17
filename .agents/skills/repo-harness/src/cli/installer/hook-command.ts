import type { Route } from '../hook/route-registry';
import type { HookHost } from './managed-entries';
import type { Location } from './types';

export const MANAGED_ENV_TAG = 'REPO_HARNESS_MANAGED=1';

export type RuntimeMode = 'global-path' | 'project-vendored-bun';
export type RuntimeSelection = 'auto' | RuntimeMode;

export interface BuildHookCommandOptions {
  route: Route;
  host: HookHost;
  runtimeMode: RuntimeMode;
}

export function resolveRuntimeMode(
  location: Location,
  selection: RuntimeSelection = 'auto',
): RuntimeMode {
  if (selection !== 'auto') return selection;
  return location === 'local' ? 'project-vendored-bun' : 'global-path';
}

export function isRuntimeSelection(value: string): value is RuntimeSelection {
  return value === 'auto' || value === 'global-path' || value === 'project-vendored-bun';
}

export function buildHookCommand(opts: BuildHookCommandOptions): string {
  const { route, host } = opts;
  if (opts.runtimeMode === 'global-path') {
    return `${MANAGED_ENV_TAG}; if command -v local-repo-harness-hook >/dev/null 2>&1; then HOOK_HOST=${host} REPO_HARNESS_HOOK_RUNTIME=global-path exec local-repo-harness-hook ${route.event} --route ${route.routeId}; fi; command -v local-repo-harness >/dev/null 2>&1 || exit 0; HOOK_HOST=${host} REPO_HARNESS_HOOK_RUNTIME=global-path exec local-repo-harness hook ${route.event} --route ${route.routeId}`;
  }

  return `${MANAGED_ENV_TAG}; repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0; hook="$repo_root/.ai/harness/bin/local-repo-harness-hook"; [ -x "$hook" ] || exit 0; export HOOK_HOST=${host} REPO_HARNESS_HOOK_RUNTIME=project-vendored-bun; exec "$hook" ${route.event} --route ${route.routeId}`;
}
