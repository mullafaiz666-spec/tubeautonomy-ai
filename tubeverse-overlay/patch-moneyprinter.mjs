import { promises as fs } from 'node:fs';
import path from 'node:path';

const runtime = path.resolve('tubeverse-runtime');
const workerSource = path.resolve('moneyprinter-worker');
let touched = new Set();
let enumReplacements = 0;
let selectorReplacements = 0;

async function walk(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const out = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...await walk(full));
    else out.push(full);
  }
  return out;
}

const files = (await walk(runtime)).filter((file) => /\.(?:ts|tsx|mts|js|jsx)$/.test(file));
for (const file of files) {
  let source = await fs.readFile(file, 'utf8');
  const before = source;

  // API schemas + frontend type unions. Model is TEXT in Postgres, so no DB enum migration is needed.
  source = source.replaceAll('["wan22", "ltx", "cogvideo"]', '["wan22", "ltx", "cogvideo", "moneyprinter"]');
  source = source.replaceAll("['wan22', 'ltx', 'cogvideo']", "['wan22', 'ltx', 'cogvideo', 'moneyprinter']");
  source = source.replaceAll('"wan22" | "ltx" | "cogvideo"', '"wan22" | "ltx" | "cogvideo" | "moneyprinter"');
  source = source.replaceAll("'wan22' | 'ltx' | 'cogvideo'", "'wan22' | 'ltx' | 'cogvideo' | 'moneyprinter'");

  if (source !== before) enumReplacements += 1;

  // Floot-derived Studio selector used by the migrated runtime.
  if (source.includes('<SelectItem value="cogvideo">CogVideoX</SelectItem>') && !source.includes('value="moneyprinter"')) {
    source = source.replace(
      '<SelectItem value="cogvideo">CogVideoX</SelectItem>',
      '<SelectItem value="cogvideo">CogVideoX</SelectItem><SelectItem value="moneyprinter">MoneyPrinter Turbo</SelectItem>',
    );
    selectorReplacements += 1;
  }

  // Support equivalent native option markup if the portable UI uses <option>.
  if (source.includes('<option value="cogvideo">CogVideoX</option>') && !source.includes('value="moneyprinter"')) {
    source = source.replace(
      '<option value="cogvideo">CogVideoX</option>',
      '<option value="cogvideo">CogVideoX</option><option value="moneyprinter">MoneyPrinter Turbo</option>',
    );
    selectorReplacements += 1;
  }

  // When the migrated Studio exposes its existing worker-download CTA, switch it
  // to the CPU/FFmpeg MoneyPrinter bundle for MoneyPrinter jobs while preserving the LTX notebook.
  source = source.replace(
    'href="/_cdn/static/14381064-88b1-42f6-bd16-196238fd38aa-TubeVerse_First_Real_Video_Test.ipynb" download><Download size={16}/> Start GPU worker',
    'href={model === "moneyprinter" ? "/workers/moneyprinter/TubeVerse-MoneyPrinter-Worker.zip" : "/_cdn/static/14381064-88b1-42f6-bd16-196238fd38aa-TubeVerse_First_Real_Video_Test.ipynb"} download><Download size={16}/> {model === "moneyprinter" ? "Get MoneyPrinter worker" : "Start GPU worker"}',
  );
  source = source.replace(
    'the oldest queued LTX job will be claimed automatically.',
    'the oldest queued job matching that worker family will be claimed automatically.',
  );

  // Preserve all existing labels while making the new model explicit.
  source = source.replace(
    /const modelLabel = \(model: string\) => model === "wan22" \? "Wan 2\.2" : model === "ltx" \? "LTX Video" : "CogVideoX";/g,
    'const modelLabel = (model: string) => model === "moneyprinter" ? "MoneyPrinter Turbo" : model === "wan22" ? "Wan 2.2" : model === "ltx" ? "LTX Video" : "CogVideoX";',
  );

  // Make the existing Register Worker button register the currently selected engine.
  source = source.replace(
    /\{ name: `TubeVerse LTX Worker \$\{workerList\.length \+ 1\}`, modelFamilies: \["ltx"\] \}/g,
    '{ name: `TubeVerse ${model === "moneyprinter" ? "MoneyPrinter" : model === "ltx" ? "LTX" : model} Worker ${workerList.length + 1}`, modelFamilies: [model as "wan22" | "ltx" | "cogvideo" | "moneyprinter"] }',
  );

  if (source !== before) {
    await fs.writeFile(file, source);
    touched.add(path.relative(runtime, file));
  }
}

// Ship the external worker and upstream attribution as downloadable production assets.
const publicWorkers = path.join(runtime, 'public', 'workers', 'moneyprinter');
await fs.mkdir(publicWorkers, { recursive: true });
for (const name of ['worker.py', 'install_moneyprinter.sh', 'requirements.txt', 'README.md', 'LICENSE.MoneyPrinterTurbo.txt']) {
  await fs.copyFile(path.join(workerSource, name), path.join(publicWorkers, name));
}
const bundleB64 = await fs.readFile(path.join(workerSource, 'TubeVerse-MoneyPrinter-Worker.zip.b64'), 'utf8');
await fs.writeFile(path.join(publicWorkers, 'TubeVerse-MoneyPrinter-Worker.zip'), Buffer.from(bundleB64.trim(), 'base64'));

if (enumReplacements === 0) {
  throw new Error('MoneyPrinter patch could not find TubeVerse model enums/unions; refusing a silent partial merge.');
}
if (selectorReplacements === 0) {
  console.warn('MoneyPrinter model is enabled in API schemas, but the current UI selector pattern was not found.');
}
console.log('MoneyPrinter integration applied:', JSON.stringify({
  enumReplacements,
  selectorReplacements,
  touched: [...touched].sort(),
}));
