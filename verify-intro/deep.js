// ---------- Q tabs ----------
(function () {
  const btns = document.querySelectorAll('#qTabs button');
  btns.forEach(b => b.addEventListener('click', () => {
    btns.forEach(x => x.classList.toggle('active', x === b));
    document.querySelectorAll('.qpane').forEach(p => (p.hidden = p.id !== b.dataset.q));
  }));
})();

// ---------- Q3: one history, three views ----------
(function () {
  const H = [
    { t: 'image', c: '#22d3ee', body: 'base64List:[登录页.jpg]  screenSize:[1260,2720]' },
    { t: 'status', c: '#22c55e', body: 'status:"normal" progress:1 total:3 reason:"已启动，位于登录页"' },
    { t: 'log', c: '#94a3b8', body: 'content:"I/Ability onForeground ..."' },
    { t: 'action', c: '#4f8cff', body: 'name:"tap" point:[500,880] reason:"点击登录按钮"' },
    { t: 'image', c: '#22d3ee', body: 'base64List:[首页-帧1.jpg, 首页-帧2.jpg]' },
  ];
  const PLAN = '待测试应用bundleName：com.example.verifydemo\n测试开始时是否重新启动应用：true\n测试计划：1.点击登录进入首页 2.…';
  // each msg: [role, text, fromIndex|null, skip?]
  const V = {
    action: {
      note: 'ActionAgent 负责"做"：自己做过的 tap 记为 assistant 的 tool_calls，后面跟一条 tool 返回；状态判断是别人给的反馈，记为 user 文本。最后一条 user 是最新截图，模型据此决定下一步。',
      msgs: [
        ['system', '操作提示词（按手机/平板/2in1 区分）…\n屏幕宽高为999x999，坐标原点在左上角', null],
        ['user', PLAN, null],
        ['user', '[image_url] data:image/jpeg;base64,登录页…', 0],
        ['user', '当前状态：normal 原因：已启动，位于登录页', 1],
        ['log', '（log 被跳过）', 2, true],
        ['assistant', '点击登录按钮\ntool_calls: tap({"point":[500,880]})', 3],
        ['tool', 'Action executed', 3],
        ['user', '[image_url] 首页-帧1  [image_url] 首页-帧2', 4],
      ],
    },
    status: {
      note: 'StatusAgent 负责"判"：自己以前的判断记为 assistant 的 returnStatus 工具调用，后跟 tool "received"；别人做的点击变成 user 纯文本"思考…；执行操作…"。它看着最新的多帧截图判断这一步是否符合预期。',
      msgs: [
        ['system', '状态判断提示词（normal/abnormal/completed/error 的定义）…', null],
        ['user', '用户计划：' + PLAN, null],
        ['user', '[image_url] data:image/jpeg;base64,登录页…', 0],
        ['assistant', 'tool_calls: returnStatus({"status":"normal","progress":1,"total":3,"reason":"已启动，位于登录页"})', 1],
        ['tool', 'received', 1],
        ['log', '（log 被跳过）', 2, true],
        ['user', '思考：点击登录按钮；执行操作：点击坐标(500, 880)', 3],
        ['user', '[image_url] 首页-帧1  [image_url] 首页-帧2', 4],
      ],
    },
    summary: {
      note: 'SummaryAgent 只在结束时调用一次，不需要多轮工具对话：连续的文字合并进同一条 user，每张图片单独作为一条 user。它通读全过程，写出 successPart / failPart。',
      msgs: [
        ['system', '总结规则：输出 successPart 与 failPart…', null],
        ['user', '[image_url] 登录页', 0],
        ['user', '当前状态：normal 原因：已启动，位于登录页\n执行操作：点击坐标(500, 880)，原因：点击登录按钮', 1],
        ['log', '（log 被跳过）', 2, true],
        ['user', '[image_url] 首页-帧1', 4],
        ['user', '[image_url] 首页-帧2', 4],
      ],
    },
  };
  const hBox = document.getElementById('histItems');
  const mBox = document.getElementById('viewMsgs');
  const note = document.getElementById('viewNote');
  H.forEach((h, i) => {
    const d = document.createElement('div');
    d.className = 'hitem'; d.dataset.i = i;
    d.innerHTML = `<span class="idx">[${i}]</span><span class="ty" style="color:${h.c}">${h.t}</span><span class="body">${h.body}</span>`;
    hBox.appendChild(d);
  });
  function hl(i) {
    hBox.querySelectorAll('.hitem').forEach(x => x.classList.toggle('hl', i !== null && +x.dataset.i === i));
    mBox.querySelectorAll('.msg').forEach(x => x.classList.toggle('hl', i !== null && x.dataset.f === String(i)));
  }
  function render(v) {
    mBox.innerHTML = '';
    V[v].msgs.forEach(([role, txt, f, skip]) => {
      const d = document.createElement('div');
      d.className = 'msg' + (skip ? ' skip' : '');
      d.dataset.f = f === null ? '' : String(f);
      const cls = role === 'log' ? 'r-system' : 'r-' + role;
      d.innerHTML = `<span class="role ${cls}">${role}</span><div><div class="txt"></div><div class="from">${f === null ? '固定前缀' : '← 来自 history[' + f + ']'}</div></div>`;
      d.querySelector('.txt').textContent = txt;
      d.addEventListener('mouseenter', () => f !== null && hl(f));
      d.addEventListener('mouseleave', () => hl(null));
      mBox.appendChild(d);
    });
    note.textContent = V[v].note + '（鼠标悬停在消息或历史元素上，可以看到对应关系）';
  }
  hBox.querySelectorAll('.hitem').forEach(x => {
    x.addEventListener('mouseenter', () => hl(+x.dataset.i));
    x.addEventListener('mouseleave', () => hl(null));
  });
  const tabs = document.querySelectorAll('#viewTabs button');
  tabs.forEach(b => b.addEventListener('click', () => {
    tabs.forEach(x => x.classList.toggle('active', x === b));
    render(b.dataset.v);
  }));
  render('action');
})();

// ---------- Q4: filmstrip ----------
(function () {
  const film = document.getElementById('film');
  const text = document.getElementById('fsText');
  const clock = document.getElementById('fsClock');
  // frame: [label, kind, diff, time]
  const OLD = [['登录页', 'old', '0.0000', 0.4], ['登录页', 'old', '0.0003', 1.1], ['登录页', 'old', '0.0001', 1.8], ['登录页', 'old', '0.0002', 2.5]];
  const AFTER = [['登录页', 'old', '0.0002', 3.2], ['过渡动画', 'new', '0.3512', 3.6]];
  const MORE = [['首页+Toast', 'toast', '0.0820', 4.1], ['首页+Toast', 'toast', '0.0004', 4.5], ['首页', 'new', '0.0310', 5.0], ['首页', 'new', '0.0002', 5.4], ['首页', 'new', '0.0001', 5.9]];
  const steps = [
    { t: 0, frames: [], cls: {},
      txt: '<b>起点</b>：上一轮刚结束，历史末尾是登录页截图。StatusAgent ∥ ActionAgent 开始向模型提问。cache 为空，但后台截图循环一直在运行。' },
    { t: 2.9, frames: OLD, cls: {},
      txt: '<b>模型思考中（约 3 秒）</b>：后台循环继续拍照，cache 中堆积了 4 张<b>点击之前</b>的登录页，diff 都接近 0。此时它们没有用处。' },
    { t: 3.0, frames: OLD, cls: { 0: 'drop', 1: 'drop', 2: 'drop', 3: 'drop' },
      txt: '<b>动作前清缓存</b>：ActionAgent 决定 tap 登录，执行前先调用一次 <code>screenshot()</code>，把这 4 张旧帧<b>全部取走并丢弃</b>（不写入历史）。cache 从"点击前最后一张"之后重新开始。<br/>⚠️ 如果不清，下一轮取图会混入这些旧帧，模型可能误以为"点击后界面没有变化"。' },
    { t: 3.6, frames: AFTER, cls: { 1: 'key' }, clear: true,
      txt: '<b>执行点击 + waitUntilChange(4000)</b>：<code>uitest uiInput click 645 2397</code>。第 1 张新帧还是登录页（渲染有延迟，diff 0.0002）；第 2 张出现过渡动画，diff 0.35 超过阈值 → 等待提前结束，不必等满 4 秒。' },
    { t: 5.9, frames: AFTER.concat(MORE), cls: {},
      txt: '<b>下一轮：3 秒稳定采集</b>：反复 <code>screenshot()</code> 取帧。依次拍到 Toast"登录成功"、首页……最后 3 帧 diff 都小于 0.01，并且持续 ≥800ms → 判定稳定，提前停止。' },
    { t: 5.9, frames: AFTER.concat(MORE), cls: { 0: 'drop', 1: 'key', 2: 'key', 3: 'drop', 4: 'key', 5: 'drop', 6: 'key' },
      txt: '<b>挑关键帧</b>：① 去掉开头 diff&lt;0.001 的"尚未变化"帧（第 1 张登录页）② 按 ≥500ms 抽样 ③ 去掉静止的重复帧 ④ 最多保留 6 帧。<br/>最终 <b>过渡 → Toast → 首页 → 首页(最后一帧)</b> 作为一条 image 写入历史。模型能看到 Toast 出现过，并据此判断 normal。' },
  ];
  let cur = 0, timer = null;
  function render() {
    const s = steps[cur];
    clock.textContent = 't = ' + s.t.toFixed(1) + 's';
    film.innerHTML = '';
    if (!s.frames.length) film.innerHTML = '<span style="color:var(--muted);font-size:13px">(cache 为空)</span>';
    s.frames.forEach((f, i) => {
      const d = document.createElement('div');
      d.className = 'frame ' + f[1] + (s.cls[i] ? ' ' + s.cls[i] : '');
      d.innerHTML = `<div class="scr">${f[0]}</div><div class="d">diff ${f[2]}</div><div class="d">${f[3]}s</div>`;
      film.appendChild(d);
    });
    text.innerHTML = `<span style="color:var(--muted)">步骤 ${cur + 1}/${steps.length}</span>　` + s.txt;
  }
  function next() { cur = (cur + 1) % steps.length; render(); }
  document.getElementById('fsNext').onclick = () => { clearInterval(timer); timer = null; next(); };
  document.getElementById('fsReset').onclick = () => { clearInterval(timer); timer = null; cur = 0; render(); };
  document.getElementById('fsAuto').onclick = () => { clearInterval(timer); timer = setInterval(next, 4200); };
  render();
})();

// ---------- Q8: limitImages demo ----------
(function () {
  const box = document.getElementById('limBox');
  const note = document.getElementById('limNote');
  if (!box) return;
  // each case: list of image-message sizes (number of frames), in time order
  const cases = {
    a: { imgs: [1, 2, 1, 2, 1], desc: '5 条带图消息，共 7 张图。<b>图片数 ≤ 12，但消息数 5 &gt; 3</b> → 保留最近 <b>3</b> 条消息中的图片，前 2 条的图片替换成文字。' },
    b: { imgs: [6, 4, 4], desc: '3 条带图消息，共 14 张图。<b>消息数没有超过上限，但图片数 14 &gt; 12</b> → 只保留最近 <b>2</b> 条（keep = 3−1），第 1 条的 6 张图替换成文字。' },
    c: { imgs: [3, 4, 2], desc: '3 条带图消息，共 9 张图。<b>两个条件都满足</b> → 原样发送，不省略。' },
  };
  function render(k) {
    const c = cases[k];
    const total = c.imgs.reduce((a, b) => a + b, 0);
    const n = c.imgs.length;
    let keep = n;
    if (!(total <= 12 && n <= 3)) keep = total > 12 ? 2 : 3;
    const dropUntil = n - keep;
    box.innerHTML = '';
    const sys = document.createElement('div');
    sys.className = 'msg';
    sys.innerHTML = '<span class="role r-system">system</span><div class="txt">提示词…</div>';
    box.appendChild(sys);
    c.imgs.forEach((cnt, i) => {
      const dropped = i < dropUntil;
      const d = document.createElement('div');
      d.className = 'msg';
      const parts = [];
      for (let j = 0; j < cnt; j++) parts.push(dropped ? '<span style="color:#64748b">"已省略历史截图"</span>' : '<span style="background:#1d4ed8;color:#fff;padding:0 6px;border-radius:4px">🖼 图</span>');
      d.innerHTML = `<span class="role r-user">user</span><div><div class="txt">第 ${i + 1} 轮截图：${parts.join(' ')}</div><div class="from">${dropped ? '✂ 图片被替换（文字保留）' : '✔ 保留图片'}</div></div>`;
      box.appendChild(d);
      const t = document.createElement('div');
      t.className = 'msg';
      t.innerHTML = `<span class="role r-assistant">assistant</span><div class="txt">第 ${i + 1} 轮动作 / 状态（文字始终保留）</div>`;
      box.appendChild(t);
    });
    note.innerHTML = c.desc + `<br/><span style="color:var(--muted)">实际发送的图片数：${c.imgs.slice(dropUntil).reduce((a, b) => a + b, 0)} 张</span>`;
  }
  const btns = document.querySelectorAll('#limTabs button');
  btns.forEach(b => b.addEventListener('click', () => {
    btns.forEach(x => x.classList.toggle('active', x === b));
    render(b.dataset.l);
  }));
  render('a');
})();

(function(){
  const $=id=>document.getElementById(id); if(!$('qwOut')) return;
  function q25([W,H]){let w=Math.round(W/28)*28,h=Math.round(H/28)*28;
    if(w>1424||h>1424){const s=Math.max(w,h)/1424;w=Math.floor(w/s/28)*28;h=Math.floor(h/s/28)*28;}
    if(w<480||h<480){const s=480/Math.min(w,h);w=Math.ceil(w*s/28)*28;h=Math.ceil(h*s/28)*28;}return [w,h];}
  const cl=(v,m)=>Math.min(m,Math.max(1,Math.round(v)));
  function run(){const W=+$('qwW').value,H=+$('qwH').value,x=+$('qwX').value,y=+$('qwY').value;
    const [Iw,Ih]=q25([W,H]);
    $('qwOut').textContent=
`[Qwen2.5]  送给模型的位图 = ${Iw} × ${Ih}（${Iw/28}×${Ih/28} 个 28px 格子）
           模型输出 (${x}, ${y}) 指的是这张位图上的像素
           实际点击 = (${cl(x*W/Iw,W)}, ${cl(y*H/Ih,H)})

[通用模型]  送给模型的位图 = ${Math.floor(W*2/3)} × ${Math.floor(H*2/3)}，并告诉它"屏幕是 999×999"
           同样输出 (${x}, ${y}) 会被当成千分比坐标
           实际点击 = (${cl(x*W/999,W)}, ${cl(y*H/999,H)})   ← 坐标语义不同，位置完全不一样`;}
  ['qwW','qwH','qwX','qwY'].forEach(i=>$(i).addEventListener('input',run)); run();
})();

