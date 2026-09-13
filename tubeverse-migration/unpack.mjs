import { promises as fs } from 'node:fs';
import { spawnSync } from 'node:child_process';

const sourceB64 = await fs.readFile(new URL('./source.b64', import.meta.url), 'utf8');
const tgz = new URL('./source.tgz', import.meta.url);
await fs.writeFile(tgz, Buffer.from(sourceB64.trim(), 'base64'));

await fs.rm('tubeverse-runtime', { recursive: true, force: true });
await fs.rm('tubeverse-netlify', { recursive: true, force: true });
const tar = spawnSync('tar', ['-xzf', tgz.pathname, '-C', '.'], { stdio: 'inherit' });
if (tar.status !== 0) process.exit(tar.status ?? 1);
await fs.rename('tubeverse-netlify', 'tubeverse-runtime');

// Apply portable integrations after reconstructing the runtime but before npm install/build.
const moneyPrinterPatch = spawnSync(
  process.execPath,
  ['tubeverse-overlay/patch-moneyprinter.mjs'],
  { stdio: 'inherit' },
);
if (moneyPrinterPatch.status !== 0) process.exit(moneyPrinterPatch.status ?? 1);

await fs.mkdir('netlify/database', { recursive: true });
await fs.rm('netlify/database/migrations', { recursive: true, force: true });
await fs.cp('tubeverse-runtime/netlify/database/migrations', 'netlify/database/migrations', { recursive: true });
await fs.rm(tgz, { force: true });
console.log('TubeVerse runtime reconstructed with MoneyPrinterTurbo worker integration.');
