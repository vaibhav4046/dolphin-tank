// Lets `node --test jstest` work on every Node version: newer ones treat the bare directory as a
// module path, so this entry point loads each *.test.mjs file next to it.
import { readdirSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
for (const f of readdirSync(here).filter((n) => n.endsWith('.test.mjs')).sort()) {
  await import(pathToFileURL(join(here, f)).href);
}
