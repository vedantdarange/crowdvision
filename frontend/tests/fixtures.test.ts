// @vitest-environment node
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
it('checks every JSON fixture against the contract types', () => {
  expect(
    execFileSync(process.execPath, ['scripts/check-fixtures.mjs'], {
      encoding: 'utf8',
    }),
  ).toContain('Type-checked all 43 fixtures');
});
it('preserves the section 5 TypeScript block verbatim', () => {
  const contract = readFileSync('../00_SHARED_CONTRACT.md', 'utf8');
  const block = contract
    .split('## 5. Data shapes')[1]!
    .split('## 6. REST API')[0]!
    .match(/```ts\r?\n([\s\S]*?)```/)![1]!;
  expect(readFileSync('../contract/types.ts', 'utf8').startsWith(block)).toBe(
    true,
  );
  expect(readFileSync('../contract/CONTRACT_VERSION', 'utf8').trim()).toBe(
    '1.1.0',
  );
});
