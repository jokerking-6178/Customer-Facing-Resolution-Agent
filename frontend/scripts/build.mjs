/**
 * Production build using esbuild directly (the same transform engine Vite
 * uses). Chosen over `vite build` because it runs in constrained CI
 * environments too — no WebAssembly involved.
 *
 * Output: dist/index.html + dist/assets/app.js + dist/assets/app.css
 */
import { build } from "esbuild";
import { cp, mkdir, rm, writeFile } from "node:fs/promises";

await rm("dist", { recursive: true, force: true });
await mkdir("dist/assets", { recursive: true });

const result = await build({
  entryPoints: ["src/main.jsx"],
  bundle: true,
  minify: true,
  format: "esm",
  jsx: "automatic",
  outfile: "dist/assets/app.js",
  loader: { ".css": "css" },
  define: { "process.env.NODE_ENV": '"production"' },
  metafile: true,
  logLevel: "info",
});

const html = `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>SkyAssist — Airline Disruption Support</title>
    <link rel="stylesheet" href="/assets/app.css" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/assets/app.js"></script>
  </body>
</html>
`;
await writeFile("dist/index.html", html, "utf-8");

const kb = (n) => `${(n / 1024).toFixed(1)} kB`;
for (const [path, out] of Object.entries(result.metafile.outputs)) {
  console.log(`  built ${path} (${kb(out.bytes)})`);
}
console.log("BUILD DONE -> dist/");
