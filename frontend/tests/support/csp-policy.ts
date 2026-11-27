export class DuplicateCspDirective extends Error {
  constructor(name: string) {
    super(`CSP_DUPLICATE_DIRECTIVE: the policy names ${name} more than once, and browsers keep only the first`);
  }
}

export function parsePolicy(policy: string): Record<string, string[]> {
  const parsed: Record<string, string[]> = {};
  for (const directive of policy.split(';')) {
    const [name, ...sources] = directive.trim().split(/\s+/);
    if (name === '') {
      continue;
    }
    const key = name.toLowerCase();
    if (key in parsed) {
      throw new DuplicateCspDirective(key);
    }
    parsed[key] = sources.toSorted();
  }
  return parsed;
}

export function sortedPolicy(policy: Record<string, string[]>): Record<string, string[]> {
  return Object.fromEntries(Object.entries(policy).map(([name, sources]) => [name, sources.toSorted()]));
}
