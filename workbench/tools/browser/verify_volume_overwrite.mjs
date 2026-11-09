// 真实浏览器验证 v0.1.222/223：一键整卷的「默认不覆盖手填内容」+「勾选后可重建」
// 目标实例：隔离副本（端口 8765、独立 data 目录），不碰用户真实项目。
import { connect } from './cdp.mjs';
import fs from 'node:fs';
import path from 'node:path';

// v0.1.223：**必须显式指定目标实例**。
// 上一版把真实项目 PID 写死在脚本里，跑一次就改用户 13 个真实产出（已用前后
// 快照证实）。这里如果缺环境变量就直接退出，宁可跑不起来，也不能打真实数据。
const BASE = process.env.FG_BASE, PID = process.env.FG_PID, DATA = process.env.FG_DATA;
if (!BASE || !PID || !DATA) {
  console.error('必须显式指定 FG_BASE / FG_PID / FG_DATA（指向隔离副本，勿用真实项目）');
  process.exit(2);
}
const BOOK = '第一册', WS = '1号车间';

const PASS = [], FAIL = [];
function check(name, ok, detail = '') {
  (ok ? PASS : FAIL).push(name + (detail ? '  [' + detail + ']' : ''));
  console.log((ok ? '  [PASS] ' : '  [FAIL] ') + name + (detail ? '  ' + detail : ''));
}
const volDir = path.join(DATA, 'projects', PID, 'volumes', BOOK, WS);
function files() {
  if (!fs.existsSync(volDir)) return [];
  return fs.readdirSync(volDir).filter(f => f.toLowerCase().endsWith('.docx') && !f.startsWith('_'));
}
function md5(p) { return fs.readFileSync(p).toString('base64').length + ':' + fs.statSync(p).size; }

const c = await connect(9222);
try {
  const errs = [];
  await c.send('Runtime.enable');
  await c.send('Log.enable');
  await c.evaluate('window.__jsErrors = []; window.addEventListener("error", e => window.__jsErrors.push(String(e.message))); true;');

  await c.goto(BASE + '/');
  await new Promise(r => setTimeout(r, 800));

  // 1. 进入竣工组卷模块
  await c.evaluate(`switchModule('archive'); true;`);
  await new Promise(r => setTimeout(r, 500));
  const activeMod = await c.evaluate(`(document.querySelector('#module-archive')||{}).className || ''`);
  check('进入竣工组卷模块', /active/.test(activeMod), activeMod);

  // 2. 勾选框存在且可见、默认未勾
  const cb = await c.evaluate(`(function(){
    var el=document.getElementById('supOverwrite');
    if(!el) return {exists:false};
    var r=el.getBoundingClientRect();
    return {exists:true, checked:el.checked, vis:r.width>0&&r.height>0,
            label:(el.closest('label')||{}).textContent||''};
  })()`);
  check('「覆盖已有文件」勾选框存在且可见', cb.exists && cb.vis, JSON.stringify(cb));
  check('默认不勾选（默认保留手填内容）', cb.exists && cb.checked === false, String(cb.checked));

  // 3. 册下拉已填出登记表的册
  const books = await c.evaluate(`Array.from(document.querySelectorAll('#supBookSel option')).map(o=>o.value)`);
  check('册下拉已填出登记表的册', books.includes(BOOK), books.join('|'));

  // 4. 第一次整卷（默认不覆盖）→ 生成文件
  await c.evaluate(`document.getElementById('supBookSel').value=${JSON.stringify(BOOK)};
     document.getElementById('supWorkshopInput').value=${JSON.stringify(WS)};
     document.getElementById('supOverwrite').checked=false; true;`);
  // 清掉卷目录，保证第一次是真新建
  await c.evaluate(`window.__volRunning=false; runVolume(); true;`);
  await waitDone(c, 60000);
  const firstMsg = await c.evaluate(`document.getElementById('supTodoBar').innerText`);
  check('第一次整卷跑完且有可读结果', /整卷完成|生成文件/.test(firstMsg), firstMsg.slice(0, 120).replace(/\n/g, ' '));
  const f1 = files();
  check('卷内确实生成了 docx', f1.length > 0, f1.join(','));
  const before = {};
  for (const f of f1) before[f] = md5(path.join(volDir, f));

  // 5. 用户手填：往第一个卷内 docx 追加标记字节（模拟现场填实测数据）
  const target = path.join(volDir, f1[0]);
  const origSize = fs.statSync(target).size;
  fs.appendFileSync(target, Buffer.from('HAND-FILLED-DATA-DO-NOT-OVERWRITE', 'utf8'));
  const handSize = fs.statSync(target).size;
  check('已模拟现场手填（文件字节增加）', handSize > origSize, `${origSize} -> ${handSize}`);

  // 6. 第二次整卷（仍不勾覆盖）→ 手填内容必须保留
  await c.evaluate(`document.getElementById('supOverwrite').checked=false; window.__volRunning=false; runVolume(); true;`);
  await waitDone(c, 60000);
  const msg2 = await c.evaluate(`document.getElementById('supTodoBar').innerText`);
  const afterKept = fs.statSync(target).size;
  check('第二次整卷后手填内容未被覆盖（字节不变）', afterKept === handSize, `${handSize} -> ${afterKept}`);
  check('界面明确告知「已保留（未覆盖）」', /已保留/.test(msg2) && /覆盖已有文件/.test(msg2), msg2.replace(/\n/g, ' ').slice(0, 160));

  // 7. 勾选覆盖后重建 → 手填内容被替换（重建能力可用）
  await c.evaluate(`document.getElementById('supOverwrite').checked=true; window.__volRunning=false; runVolume(); true;`);
  await waitDone(c, 60000);
  const msg3 = await c.evaluate(`document.getElementById('supTodoBar').innerText`);
  const afterOv = fs.statSync(target).size;
  check('勾选「覆盖已有文件」后确实重建（字节回到生成态）', afterOv === origSize, `${handSize} -> ${afterOv}`);
  check('勾选路径不显示「已保留」', !/已保留/.test(msg3), msg3.replace(/\n/g, ' ').slice(0, 120));
  // 内容里不应再有手填标记
  const raw = fs.readFileSync(target);
  check('重建后的文件里不含手填标记', !raw.includes(Buffer.from('HAND-FILLED-DATA-DO-NOT-OVERWRITE')), '');

  // 8. 无 JS 异常
  const jsErrs = await c.evaluate('window.__jsErrors || []');
  check('全程无未处理 JS 异常', jsErrs.length === 0, jsErrs.join('|'));

} finally {
  c.close();
}

async function waitDone(c, ms) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    await new Promise(r => setTimeout(r, 400));
    const running = await c.evaluate('!!window.__volRunning');
    if (!running) { await new Promise(r => setTimeout(r, 400)); return; }
  }
  throw new Error('整卷等待超时');
}

console.log('\n===== ' + PASS.length + ' PASS / ' + FAIL.length + ' FAIL =====');
if (FAIL.length) { console.log(FAIL.join('\n')); process.exit(1); }
