// 极简 CDP 客户端：本机 chromium + Node 22 自带 WebSocket，不依赖 playwright/ws
export async function connect(port = 9222) {
  const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = list.find(t => t.type === 'page' && t.webSocketDebuggerUrl);
  if (!page) throw new Error('no page target');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map();
  const events = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id); pending.delete(m.id);
      m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
    } else events.push(m);
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const _id = ++id; pending.set(_id, { res, rej });
    ws.send(JSON.stringify({ id: _id, method, params }));
  });
  const evaluate = async (expr, awaitPromise = true) => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + ' ' + JSON.stringify(r.exceptionDetails.exception?.description || ''));
    return r.result.value;
  };
  const goto = async (url) => {
    await send('Page.navigate', { url });
    for (let i = 0; i < 100; i++) {
      await new Promise(r => setTimeout(r, 200));
      try { const st = await evaluate('document.readyState'); if (st === 'complete') return; } catch (e) {}
    }
    throw new Error('page load timeout');
  };
  return { ws, send, evaluate, goto, events, close: () => ws.close() };
}
