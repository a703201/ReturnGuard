// scripts/minify.mjs — 前端构建链路（P2-6 / N4）
//
// 现状：demo/static 下的 ES Module（app.js / render.js / store.js / api.js / i18n.js）
// 由 index.html 以 <script type="module"> 直接加载，浏览器原生解析，**无需打包即可运行**
// （演示/默认用未压缩源，便于讲解与调试）。
//
// 本脚本提供**可用的生产压缩产物**：
//   1) 用 terser 压缩每个源文件 → demo/static/dist/*.min.js（保留 ESM，不做模块合并）；
//   2) **重写相对导入**：`./render.js` → `./render.min.js`，保证 dist 内部自洽
//      （否则压缩后的 app.min.js 仍会 import 未压缩的 render.js，压缩形同虚设）；
//   3) 复制 index.html → dist/index.html 并把入口脚本指向 `/static/dist/app.min.js`。
//
// 用法：
//   npm install        # 安装 terser（devDependency）
//   npm run build      # 生成 demo/static/dist/（压缩产物，已 gitignore）
//
// 启用压缩产物：设环境变量 SERVE_MINIFIED=1 重启服务，`/` 路由将改发 dist/index.html
// （默认 0，仍发未压缩源，确保演示现场零风险）。
//
// 注意：仅做语法级压缩（mangle + compress + 保留 import/export），不做模块合并。

import { minify } from 'terser';
import { readFile, writeFile, mkdir, rm } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(__dirname, '..', 'demo', 'static');
const OUT_DIR = join(SRC_DIR, 'dist');
const ENTRIES = ['app.js', 'render.js', 'store.js', 'api.js', 'i18n.js'];

// 把 ESM 相对导入指向压缩兄弟文件：'./x.js' → './x.min.js'
function rewriteImports(code) {
  return code.replace(
    /(\bfrom\s*['"]\.\/[A-Za-z0-9_]+)\.js(['"])/g,
    '$1.min.js$2',
  ).replace(
    /(\bimport\s*['"]\.\/[A-Za-z0-9_]+)\.js(['"])/g,
    '$1.min.js$2',
  );
}

async function main() {
  await rm(OUT_DIR, { recursive: true, force: true });
  await mkdir(OUT_DIR, { recursive: true });

  let totalBefore = 0;
  let totalAfter = 0;
  for (const f of ENTRIES) {
    const srcPath = join(SRC_DIR, f);
    const outPath = join(OUT_DIR, f.replace(/\.js$/, '.min.js'));
    const code = await readFile(srcPath, 'utf8');
    const result = await minify(code, {
      module: true, // 保留 import/export，产物仍是 ES Module
      compress: { defaults: true },
      mangle: true,
      format: { comments: false },
    });
    if (result.error) {
      console.error(`✗ ${f} 压缩失败：`, result.error);
      process.exitCode = 1;
      continue;
    }
    await writeFile(outPath, rewriteImports(result.code), 'utf8');
    const before = Buffer.byteLength(code, 'utf8');
    const after = Buffer.byteLength(result.code, 'utf8');
    totalBefore += before;
    totalAfter += after;
    const pct = before ? ((1 - after / before) * 100).toFixed(1) : '0.0';
    console.log(
      `✓ ${f} → dist/${f.replace(/\.js$/, '.min.js')}  ` +
        `${(before / 1024).toFixed(1)}KB → ${(after / 1024).toFixed(1)}KB (-${pct}%)`,
    );
  }

  // index.html → dist/index.html（入口指向压缩产物；CSP nonce 占位符原样保留）
  const html = await readFile(join(SRC_DIR, 'index.html'), 'utf8');
  const htmlOut = html.replace(/\/static\/app\.js/g, '/static/dist/app.min.js');
  await writeFile(join(OUT_DIR, 'index.html'), htmlOut, 'utf8');

  const pctAll = totalBefore ? ((1 - totalAfter / totalBefore) * 100).toFixed(1) : '0.0';
  console.log(
    `\n✓ 构建完成：dist/ 共 ${(totalAfter / 1024).toFixed(1)}KB（源 ${(totalBefore / 1024).toFixed(1)}KB，-${pctAll}%）`,
  );
  console.log('启用方式：设 SERVE_MINIFIED=1 重启服务（默认发未压缩源，演示现场零风险）。');
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
