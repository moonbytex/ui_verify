// ---------- Hero typing ----------
(function () {
  const lines = [
    ['c-dim', 'PS> '],
    ['c-cmd', 'devecocli verify '],
    ['c-key', '--test-plan '],
    ['c-str', '"启动应用，点击登录进入首页；点击商城→手机，看到商品列表；点击 Mate 70 看到详情页"'],
    ['', '\n'],
    ['c-dim', '⠋ 1/4 已启动应用，位于登录页\n'],
    ['c-dim', '⠙ 2/4 点击登录后进入首页，看到商城入口\n'],
    ['c-dim', '⠹ 3/4 进入手机分类，商品列表正常展示\n'],
    ['c-ok', '✔ Verification passed\n'],
    ['', '{\n  '],
    ['c-key', '"success"'], ['', ': '], ['c-ok', 'true'], ['', ',\n  '],
    ['c-key', '"reason"'], ['', ': '], ['c-str', '"所有步骤均符合预期"'], ['', ',\n  '],
    ['c-key', '"successPart"'], ['', ': '], ['c-str', '"1.启动… 2.登录… 3.商城… 4.详情页…"'], ['', ',\n  '],
    ['c-key', '"failPart"'], ['', ': '], ['c-str', '""'], ['', ',\n  '],
    ['c-key', '"id"'], ['', ': '], ['c-str', '"a3f9c2e1"'], ['', '\n}'],
  ];
  const el = document.getElementById('typing');
  let li = 0, ci = 0, span = null;
  function tick() {
    if (li >= lines.length) { setTimeout(() => { el.innerHTML = ''; li = 0; ci = 0; span = null; tick(); }, 4000); return; }
    const [cls, text] = lines[li];
    if (!span) { span = document.createElement('span'); if (cls) span.className = cls; el.appendChild(span); }
    span.textContent += text[ci++];
    if (ci >= text.length) { li++; ci = 0; span = null; }
    setTimeout(tick, text.length > 30 ? 14 : 28);
  }
  tick();
})();

// ---------- MCP messages ----------
(function () {
  const msgs = [
`// CLI: 找到依赖包里的 ui-verification-mcp，用当前 Node 拉起
spawn(process.execPath, ["node_modules/ui-verification-mcp/bin/ui-verification-mcp.cjs"], {
  env: {
    UI_VERIFY_BASE_URL:   "<verify init 里配置的 baseUrl>",
    UI_VERIFY_API_KEY:    "<解密后的 key>",      // 不进 JSON-RPC 报文
    UI_VERIFY_MODEL_NAME: "qwen3-vl-plus",
    UI_VERIFY_HDC_PATH:   "C:/.../toolchains/hdc.exe"
  }
})
// cjs 再启动 dist/uiVerification.mjs，stdio 原样转接`,
`→ stdin
{"jsonrpc":"2.0","id":1,"method":"initialize",
 "params":{"protocolVersion":"2024-11-05",
           "clientInfo":{"name":"devecocli"},"capabilities":{}}}

← stdout
{"jsonrpc":"2.0","id":1,"result":{"serverInfo":{...},"capabilities":{"tools":{}}}}`,
`→ stdin
{"jsonrpc":"2.0","id":2,"method":"tools/call",
 "params":{
   "name":"verifyUI",
   "arguments":{
     "testPlan":"启动应用，点击登录进入首页……",
     "bundleName":"com.example.verifydemo",
     "freshStart":true,
     "device":"127.0.0.1:5555"      // CLI 已解析成序列号
   },
   "_meta":{"progressToken":2}
 }}`,
`← stdout（每判一次状态推送一次）
{"jsonrpc":"2.0","method":"notifications/progress",
 "params":{"progressToken":2,"progress":2,"total":4,
           "message":"点击登录后进入首页，看到商城入口"}}

CLI spinner:  ⠙ 2/4 点击登录后进入首页，看到商城入口`,
`← stdout
{"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":
 "{\\"success\\":true,
   \\"reason\\":\\"所有步骤均符合预期\\",
   \\"successPart\\":\\"1.… 2.… 3.… 4.…\\",
   \\"failPart\\":\\"\\",
   \\"id\\":\\"a3f9c2e1\\"}"}]}}`,
`→ tools/call getLog         {"id":"a3f9c2e1","maxLogSize":-1}
→ tools/call saveScreenshot {"id":"a3f9c2e1","dirname":"%TEMP%/ui-verification/cache/a3f9c2e1/screenshots"}

// 只读 MCP 进程内存，不再操作设备
// CLI 写入 cache/<id>/verify.log 后关闭子进程，打印五字段 JSON
// 之后 devecocli verify log/screenshot --id 读的都是本机缓存`,
  ];
  const out = document.getElementById('mcpMsg');
  const btns = document.querySelectorAll('#mcpSteps button');
  function show(i) {
    out.textContent = msgs[i];
    btns.forEach(b => b.classList.toggle('active', +b.dataset.i === i));
  }
  btns.forEach(b => b.addEventListener('click', () => show(+b.dataset.i)));
  show(0);
})();
