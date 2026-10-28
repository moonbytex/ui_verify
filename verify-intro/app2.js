// ---------- Main loop simulation ----------
(function () {
  const ids = ['s-cap', 's-cap2', 's-st', 's-act', 's-act2', 's-exe', 's-sum'];
  const $ = id => document.getElementById(id);
  const log = $('loopLog');
  let timers = [], autoTimer = null;
  function reset() {
    timers.forEach(clearTimeout); timers = [];
    ids.forEach(i => $(i).classList.remove('on', 'dead'));
    log.innerHTML = '';
  }
  function at(ms, fn) { timers.push(setTimeout(fn, ms)); }
  function say(t, c) { const d = document.createElement('div'); d.innerHTML = t; if (c) d.style.color = c; log.appendChild(d); log.scrollTop = log.scrollHeight; }
  function on(id) { $(id).classList.add('on'); }

  const plays = {
    normal() {
      at(0, () => { on('s-cap'); say('[capture] 取帧直到稳定（800ms 内 diff&lt;1%）→ 写入 image'); });
      at(700, () => { on('s-st'); on('s-act'); say('[parallel] StatusAgent ∥ ActionAgent 同时请求模型'); });
      at(1600, () => say('[action] 预取：tap([512, 880]) "点击登录按钮"', '#93c5fd'));
      at(2100, () => say('[status] normal 2/4 "已在登录页，按钮可见"', '#86efac'));
      at(2400, () => { on('s-exe'); say('[exec] 清缓存 → uitest uiInput click 645 2397 → waitUntilChange(4000)'); });
      at(3300, () => { on('s-cap2'); say('[next] 下一轮：取动作之后的稳定帧'); });
    },
    abnormal() {
      at(0, () => { on('s-cap'); say('[capture] 写入 image'); });
      at(700, () => { on('s-st'); on('s-act'); say('[parallel] StatusAgent ∥ ActionAgent'); });
      at(1600, () => say('[action] 预取：tap([300, 400])', '#93c5fd'));
      at(2100, () => { say('[status] abnormal "出现权限弹窗挡住了目标" retry 1/3', '#fcd34d'); $('s-act').classList.add('dead'); $('s-act').classList.remove('on'); });
      at(2400, () => say('[discard] 预取动作作废，异常原因写入历史', '#fcd34d'));
      at(2700, () => { on('s-act2'); say('[replan] ActionAgent 基于最新截图重新规划 → tap([500, 720]) "点击允许"'); });
      at(3500, () => { on('s-cap2'); say('[exec] 执行新动作 → 下一轮'); });
    },
    completed() {
      at(0, () => { on('s-cap'); say('[capture] 写入 image'); });
      at(700, () => { on('s-st'); on('s-act'); say('[parallel] StatusAgent ∥ ActionAgent'); });
      at(2100, () => { say('[status] completed 4/4 "详情页显示 Mate 70，价格正确"', '#93c5fd'); $('s-act').classList.add('dead'); });
      at(2500, () => { on('s-sum'); say('[summary] SummaryAgent → successPart / failPart'); });
      at(3100, () => say('[checkError] hidumper faultlogger 对比任务前后：无新增'));
      at(3500, () => say('→ { success: true, id: "a3f9c2e1" }', '#86efac'));
    },
    error() {
      at(0, () => { on('s-cap'); say('[capture] 写入 image'); });
      at(700, () => { on('s-st'); on('s-act'); say('[parallel] StatusAgent ∥ ActionAgent'); });
      at(2100, () => { say('[status] error "页面上没有【已发货】标签，与计划不符"', '#fca5a5'); $('s-act').classList.add('dead'); });
      at(2500, () => { on('s-sum'); say('[summary] 写入成功步骤和失败步骤'); });
      at(3000, () => say('[checkError] 发现新增 jscrash → 拉取到 faultlogs/，路径拼进 reason', '#fca5a5'));
      at(3400, () => say('[memory] 无 abnormal 且首步为 startApp → 保存 stepMemory', '#c4b5fd'));
      at(3800, () => say('→ { success: false, failPart: "第4步…" }', '#fca5a5'));
    },
  };
  function play(k) { reset(); plays[k](); }
  document.querySelectorAll('[data-b]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('[data-b]').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    clearInterval(autoTimer); autoTimer = null;
    if (b.dataset.b === 'auto') {
      const seq = ['normal', 'abnormal', 'normal', 'completed']; let i = 0;
      play(seq[i]);
      autoTimer = setInterval(() => { i = (i + 1) % seq.length; play(seq[i]); }, 4800);
    } else play(b.dataset.b);
  }));
  document.querySelector('[data-b="auto"]').click();
})();

// ---------- Coordinate demo ----------
(function () {
  const phone = document.getElementById('phone');
  const dot = document.getElementById('dot');
  const out = document.getElementById('coordOut');
  const W = 1260, H = 2720;
  const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
  phone.addEventListener('click', e => {
    const r = phone.getBoundingClientRect();
    const fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
    dot.style.display = 'block';
    dot.style.left = (fx * 100) + '%'; dot.style.top = (fy * 100) + '%';
    const mx = Math.round(fx * 999), my = Math.round(fy * 999);
    const px = clamp(Math.round(mx * W / 999), 1, W), py = clamp(Math.round(my * H / 999), 1, H);
    out.textContent =
`物理屏幕     W×H = ${W}×${H}
送给模型的图 floor(W×2/3)×floor(H×2/3) = ${Math.floor(W * 2 / 3)}×${Math.floor(H * 2 / 3)}
系统提示     "屏幕宽高为999x999，坐标原点在左上角"

① 模型输出   tap({ point: [${mx}, ${my}] })     ← 写入历史时保持模型坐标
② 换算       x = clamp(round(${mx}×${W}/999), 1, ${W}) = ${px}
             y = clamp(round(${my}×${H}/999), 1, ${H}) = ${py}
③ 执行       hdc -t 127.0.0.1:5555 shell uitest uiInput click ${px} ${py}
④ 校验       下一轮 StatusAgent 看新截图；点偏了就 abnormal 后重新定位`;
  });
})();

// ---------- History flow ----------
(function () {
  const flow = document.getElementById('histFlow');
  const items = [['image', '#22d3ee'], ['status', '#22c55e'], ['log', '#94a3b8'], ['action', '#4f8cff'], ['image', '#22d3ee'], ['status', '#22c55e'], ['log', '#94a3b8'], ['action', '#4f8cff'], ['…', '#64748b']];
  items.forEach(([t, c], i) => {
    const s = document.createElement('span');
    s.textContent = t;
    s.style.cssText = `padding:6px 14px;border-radius:99px;border:1px solid ${c};color:${c};background:rgba(255,255,255,.03);opacity:0;transition:opacity .4s`;
    flow.appendChild(s);
    if (i < items.length - 1) { const a = document.createElement('span'); a.textContent = '→'; a.style.color = '#475569'; flow.appendChild(a); }
    setTimeout(() => (s.style.opacity = 1), 250 * i);
  });
})();
