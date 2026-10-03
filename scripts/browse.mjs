#!/usr/bin/env node
// 无桌面环境下的浏览器：headless Chromium（Playwright），零 sudo
// 用法: browse [--proxy|--direct] [--mobile] [--wait ms] [--full|--viewport] <模式> <URL> [输出文件]
//   模式: shot(截图,默认) | text(正文文本) | dom(HTML) | pdf
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
const opts = { proxy: null, wait: 1500, full: true, mobile: false };
const rest = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === '--proxy') opts.proxy = 'http://127.0.0.1:7890';
  else if (a === '--direct') opts.proxy = null;
  else if (a === '--mobile') opts.mobile = true;
  else if (a === '--viewport') opts.full = false;
  else if (a === '--wait') opts.wait = parseInt(argv[++i], 10) || 1500;
  else rest.push(a);
}
let mode = rest[0] || 'shot';
let url = rest[1];
let out = rest[2];
if (!url && /^https?:\/\//.test(mode)) { url = mode; mode = 'shot'; }
if (!url) { console.error('用法: browse [--proxy] [--mobile] [--wait ms] shot|text|dom|pdf <URL> [输出]'); process.exit(2); }
if (!/^https?:\/\//.test(url)) url = 'https://' + url;

const UA_DESKTOP = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36';
const UA_MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';

const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
// 产物默认落进 T2 默认打开的目录（~/trimum/tmp/browse-out），手机在 vscode web 里可直接预览
const home = process.env.HOME || '.';
const repo = path.join(home, 'trimum', 'tmp', 'browse-out');
const dir = fs.existsSync(path.join(home, 'trimum')) ? repo : path.join(home, 'browse-out');
fs.mkdirSync(dir, { recursive: true });
if (!out || out === '-') out = path.join(dir, stamp + '-' + mode + '.' + ({ shot: 'png', pdf: 'pdf', text: 'txt', dom: 'html' }[mode] || 'txt'));

const browser = await chromium.launch({
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--hide-scrollbars'],
  ...(opts.proxy ? { proxy: { server: opts.proxy } } : {}),
});
const ctx = await browser.newContext({
  userAgent: opts.mobile ? UA_MOBILE : UA_DESKTOP,
  viewport: opts.mobile ? { width: 414, height: 896 } : { width: 1440, height: 900 },
  locale: 'zh-CN',
  ignoreHTTPSErrors: true,
});
const page = await ctx.newPage();
let resp = null;
try {
  resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  try { await page.waitForLoadState('networkidle', { timeout: 12000 }); } catch {}
  await page.waitForTimeout(opts.wait);
  const title = await page.title();
  console.log('URL   : ' + page.url());
  console.log('状态  : ' + (resp ? resp.status() : '?'));
  console.log('标题  : ' + title);
  if (mode === 'shot') { await page.screenshot({ path: out, fullPage: opts.full }); }
  else if (mode === 'pdf') { await page.pdf({ path: out, format: 'A4', printBackground: true }); }
  else if (mode === 'text') {
    const t = await page.evaluate(() => {
      document.querySelectorAll('script,style,noscript,svg').forEach(e => e.remove());
      return document.body ? document.body.innerText.replace(/\n{3,}/g, '\n\n').trim() : '';
    });
    fs.writeFileSync(out, t + '\n', 'utf8');
    console.log('字数  : ' + t.length);
  } else if (mode === 'dom') { fs.writeFileSync(out, await page.content(), 'utf8'); }
  else { console.error('未知模式: ' + mode); process.exit(2); }
  console.log('输出  : ' + out + '  (' + fs.statSync(out).size + ' B)');
} catch (e) {
  console.error('失败: ' + (e && e.message ? e.message : e));
  await browser.close();
  process.exit(1);
}
await browser.close();
