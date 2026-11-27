import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
const dir = new URL('../src/components/ui/', import.meta.url);
for (const file of readdirSync(dir)) {
  const path = new URL(file, dir);
  writeFileSync(
    path,
    readFileSync(path, 'utf8').replaceAll('from "cn"', 'from "@/lib/utils"'),
  );
}
