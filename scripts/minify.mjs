// scripts/minify.mjs — P2-6 轻量前端构建链路（建议项，不接入 CI，避免破坏演示现场）
//
// 现状：demo/static 下的 ES Module（app.js / render.js / store.js / api.js / i18n.js）
// 由 index.html 以 <script type="module"> 直接加载，浏览器原生解析，无需打包即可运行。
//
// 本脚本提供可选的「压缩产物」能力：把上述源文件用 terser 压缩为 *.min.js 兄弟文件，
// 供生产部署时按需在 index.html 切换引用（演示/评审现场默认仍用未压缩源，便于讲解与调试）。
//
// 用法：
//   npm install        # 安装 terser（devDependency）
//   npm run minify     # 生成 demo/static/*.min.js
//
// 注意：仅做语法级压缩（mangle + compress + 保留 ESM import/export），不做模块合并，
// 因此压缩产物仍为独立 ES Module，可直接替换 index.html 的 src 引用，无需改运行时。

import { minify } from 'terser';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(__dirname, '..', 'demo', 'static');
const ENTRIES = ['app.js', 'render.js', 'store.js', 'api.js', 'i18n.js'];

async function main() {
  for (const f of ENTRIES) {
    const srcPath = join(SRC_DIR, f);
    const outPath = join(SRC_DIR, f.replace(/\.js$/, '.min.js'));
    const code = await readFile(srcPath, 'utf8');
    const result = await minify(code, {
      module: true,          // 保留 import/export，产物仍是 ES Module
      compress: { defaults: true },
      mangle: true,
      format: { comments: false },
    });
    if (result.error) {
      console.error(`✗ ${f} 压缩失败：`, result.error);
      process.exitCode = 1;
      continue;
    }
    await writeFile(outPath, result.code, 'utf8');
    const before = Buffer.byteLength(code, 'utf8');
    const after = Buffer.byteLength(result.code, 'utf8');
    const pct = before ? ((1 - after / before) * 100).toFixed(1) : '0.0';
    console.log(`✓ ${f} → ${f.replace(/\.js$/, '.min.js')}  ${(before / 1024).toFixed(1)}KB → ${(after / 1024).toFixed(1)}KB (-${pct}%)`);
  }
  console.log('\n提示：生产部署如需启用压缩产物，把 index.html 中 <script type="module" src="/static/app.js"> 改为 app.min.js 即可（其余模块由浏览器按 import 解析）。');
}

main().catch((e) => { console.error(e); process.exit(1); });
