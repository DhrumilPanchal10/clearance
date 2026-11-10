// Copies the ground-truth checklists into public/ so the static (GitHub Pages)
// build can fetch them client-side. Runs before `dev` and `build`.
import { mkdirSync, copyFileSync, existsSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "..", "..", "data", "policies", "parsed");
const dest = join(here, "..", "public", "checklists");

if (!existsSync(src)) {
  console.warn(`[copy-checklists] source not found: ${src} — skipping`);
  process.exit(0);
}
mkdirSync(dest, { recursive: true });
let n = 0;
for (const f of readdirSync(src)) {
  if (f.endsWith(".json")) {
    copyFileSync(join(src, f), join(dest, f));
    n++;
  }
}
console.log(`[copy-checklists] copied ${n} checklist(s) → public/checklists`);
