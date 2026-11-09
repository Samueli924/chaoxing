'use strict';

/* ======================= 基础工具 ======================= */
const TOKEN = new URLSearchParams(location.search).get('t') || '';
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(path, body) {
  const opts = { method: body === undefined ? 'GET' : 'POST', headers: { 'X-Token': TOKEN } };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch('/api' + path, opts);
  } catch (e) {
    throw new Error('无法连接后台服务，请重新打开应用');
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) {
    const err = new Error(j.msg || `请求失败（${r.status}）`);
    err.status = r.status;
    throw err;
  }
  return j;
}

const store = {
  get(k, d) { try { const v = localStorage.getItem('cx.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('cx.' + k, JSON.stringify(v)); } catch { /* 忽略 */ } },
};

function toast(msg, type = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  $('#toast-root').appendChild(el);
  setTimeout(() => el.remove(), type === 'error' ? 4500 : 2600);
}

function confirmBox({ title, message, ok = '确定', cancel = '取消', danger = false }) {
  return new Promise((resolve) => {
    const root = $('#modal-root');
    root.innerHTML = `
      <div class="modal-backdrop">
        <div class="modal card" role="dialog">
          <h3>${esc(title)}</h3>
          ${message ? `<p>${message}</p>` : ''}
          <div class="btns">
            ${cancel ? `<button class="btn" data-r="0">${esc(cancel)}</button>` : ''}
            <button class="btn ${danger ? 'danger solid' : 'primary'}" data-r="1">${esc(ok)}</button>
          </div>
        </div>
      </div>`;
    const done = (v) => { root.innerHTML = ''; document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') done(false); if (e.key === 'Enter') done(true); };
    document.addEventListener('keydown', onKey);
    $$('[data-r]', root).forEach((b) => b.addEventListener('click', () => done(b.dataset.r === '1')));
    $('.modal-backdrop', root).addEventListener('click', (e) => { if (e.target === e.currentTarget) done(false); });
    $('.btn.primary, .btn.solid', root)?.focus();
  });
}

const fmtTime = (sec) => {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const p = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`;
};
const fmtDuration = (sec) => {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  if (h) return `${h} 小时 ${m} 分`;
  if (m) return `${m} 分钟`;
  return `${sec} 秒`;
};
const maskPhone = (p) => (p && p.length >= 7 ? p.slice(0, 3) + '****' + p.slice(-4) : p || '');

/* ======================= 图标 ======================= */
const I = {
  logo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 10 12 5 2 10l10 5 10-5Z"/><path d="M6 12v5c3 2 9 2 12 0v-5"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>',
  logout: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.9l10-6.5a1 1 0 0 0 0-1.7l-10-6.5A1 1 0 0 0 8 5.5Z"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  done: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9.5"/><path d="m8 12 3 3 5-6"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9.5"/><path d="M12 7.5v5.5"/><path d="M12 16.5h.01"/></svg>',
  pause: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9.5"/><path d="M10 9v6M14 9v6"/></svg>',
  chev: '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 6 6-6 6"/></svg>',
  eye: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
};

/* ======================= 全局状态 ======================= */
const S = {
  session: null,
  courses: [],
  coursesLoading: false,
  selected: new Set(store.get('selected', [])),
  filter: '',
  settings: null,
  run: null,
  logSeq: 0,
  logs: [],
  logFilter: store.get('logFilter', 'all'),
  open: new Set(),
  view: '',
  pollToken: 0,
};

const PROVIDERS = [
  { id: '', name: '不使用题库' },
  { id: 'TikuYanxi', name: '言溪题库' },
  { id: 'TikuLike', name: 'LIKE 知识库' },
  { id: 'TikuGo', name: 'GO 题（网课小工具）' },
  { id: 'TikuAdapter', name: 'TikuAdapter（自建）' },
  { id: 'AI', name: 'AI 大模型（OpenAI 兼容接口）' },
  { id: 'SiliconFlow', name: '硅基流动 AI' },
];
const providerName = (id) => (PROVIDERS.find((p) => p.id === id) || { name: id }).name;

/* ======================= 启动 ======================= */
async function boot() {
  const app = $('#app');
  app.innerHTML = '<div class="splash"><div class="spinner"></div><p>正在检查登录状态…</p></div>';
  try {
    const [sess, set] = await Promise.all([api('/session'), api('/settings')]);
    S.session = sess;
    S.settings = set.settings;
  } catch (e) {
    app.innerHTML = `<div class="splash"><p>${esc(e.message)}</p><button class="btn" onclick="boot()">重试</button></div>`;
    return;
  }
  if (!S.session.logged_in) return renderLogin();
  renderShell();
  if (S.session.run_status && S.session.run_status !== 'idle') showRun();
  else showCourses();
}

/* ======================= 登录页 ======================= */
function renderLogin(errMsg = '') {
  S.view = 'login';
  S.pollToken++;
  const phone = S.session?.phone || '';
  $('#app').innerHTML = `
    <div class="login-wrap">
      <form class="login card" autocomplete="on">
        <div class="logo">${I.logo}</div>
        <h1>刷课助手</h1>
        <p class="sub">登录你的超星学习通账号</p>
        ${errMsg ? `<div class="err">${esc(errMsg)}</div>` : ''}
        <div class="field">
          <label for="phone">手机号</label>
          <input class="input" id="phone" name="username" inputmode="numeric" autocomplete="username" placeholder="学习通绑定的手机号" value="${esc(phone)}">
        </div>
        <div class="field">
          <label for="pwd">密码</label>
          <div class="pwd-wrap">
            <input class="input" id="pwd" type="password" name="password" autocomplete="current-password" placeholder="学习通登录密码">
            <button type="button" class="btn ghost icon" id="toggle-pwd" title="显示密码">${I.eye}</button>
          </div>
        </div>
        <label class="row"><span>记住密码，下次自动登录<br><span class="hint">密码保存在 Mac 钥匙串中</span></span>
          <span class="switch"><input type="checkbox" id="remember" checked><span></span></span></label>
        <button class="btn primary lg" type="submit" id="login-btn">登录</button>
        <p class="hint" style="text-align:center;margin:0">密码只用于登录学习通，不会上传到别处</p>
      </form>
    </div>`;
  const form = $('.login');
  (phone ? $('#pwd') : $('#phone')).focus();
  $('#toggle-pwd').onclick = () => { const p = $('#pwd'); p.type = p.type === 'password' ? 'text' : 'password'; };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = $('#login-btn');
    const body = { phone: $('#phone').value.trim(), password: $('#pwd').value, remember: $('#remember').checked };
    if (!body.phone || !body.password) return toast('请填写手机号和密码', 'error');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner sm"></span> 正在登录…';
    try {
      S.session = await api('/login', body);
      renderShell();
      showCourses(true);
      toast(`欢迎回来${S.session.name ? '，' + S.session.name : ''}`);
    } catch (err) {
      S.session = { ...(S.session || {}), phone: body.phone };
      renderLogin(err.message);
      $('#pwd').focus();
    }
  };
}

/* ======================= 主框架 ======================= */
function renderShell() {
  const name = S.session.name || '同学';
  $('#app').innerHTML = `
    <div class="topbar">
      <div class="brand"><i>${I.logo}</i>刷课助手</div>
      <div class="spacer"></div>
      <div class="user-chip" title="${esc(S.session.phone)}">
        <span class="avatar">${esc(name.slice(-1))}</span>
        <span>${esc(name)}</span><span class="phone">${esc(maskPhone(S.session.phone))}</span>
      </div>
      <button class="btn ghost" id="btn-settings">${I.gear}设置</button>
      <button class="btn ghost icon" id="btn-logout" title="退出登录 / 切换账号">${I.logout}</button>
    </div>
    <div class="main" id="main"></div>`;
  $('#btn-settings').onclick = () => openSettings();
  $('#btn-logout').onclick = async () => {
    if (S.run && ['starting', 'running', 'counting'].includes(S.run.status)) return toast('正在学习中，请先停止', 'error');
    const yes = await confirmBox({ title: '退出登录？', message: '会清除保存的登录状态和钥匙串里的密码，之后可以换一个账号登录。', ok: '退出登录', danger: true });
    if (!yes) return;
    try {
      S.session = await api('/logout', {});
      S.courses = [];
      renderLogin();
    } catch (e) { toast(e.message, 'error'); }
  };
}

/* ======================= 课程列表 ======================= */
async function showCourses(refresh = false) {
  S.view = 'courses';
  const token = ++S.pollToken;
  const main = $('#main');
  main.innerHTML = `
    <div class="page">
      <div class="page-head">
        <h2>我的课程</h2><span class="count" id="course-count"></span>
        <div class="spacer" style="flex:1"></div>
        <div class="search">${I.search}<input class="input" id="search" placeholder="搜索课程或老师" value="${esc(S.filter)}"></div>
        <div class="tools">
          <button class="btn" data-sel="unfinished">选择未完成</button>
          <button class="btn" data-sel="all">全选</button>
          <button class="btn" data-sel="none">清空</button>
          <button class="btn icon" id="btn-refresh" title="重新读取课程">${I.refresh}</button>
        </div>
      </div>
      <div id="course-list"></div>
    </div>
    <div class="actionbar" id="actionbar"></div>`;

  $('#search').oninput = (e) => { S.filter = e.target.value; renderCourseList(); };
  $$('[data-sel]').forEach((b) => (b.onclick = () => {
    const vis = visibleCourses();
    if (b.dataset.sel === 'none') vis.forEach((c) => S.selected.delete(c.key));
    else vis.forEach((c) => {
      if (b.dataset.sel === 'all' || !isComplete(c)) S.selected.add(c.key);
      else S.selected.delete(c.key);
    });
    saveSelection();
    renderCourseList();
  }));
  $('#btn-refresh').onclick = () => loadCourses(true, token);

  if (S.courses.length && !refresh) renderCourseList();
  await loadCourses(refresh, token);
}

function isComplete(c) { return c.progress && c.progress.total > 0 && c.progress.done >= c.progress.total; }

function visibleCourses() {
  const q = S.filter.trim().toLowerCase();
  if (!q) return S.courses;
  return S.courses.filter((c) => (c.title + ' ' + c.teacher).toLowerCase().includes(q));
}

function saveSelection() {
  const keys = new Set(S.courses.map((c) => c.key));
  store.set('selected', [...S.selected].filter((k) => !S.courses.length || keys.has(k)));
}

async function loadCourses(refresh, token) {
  S.coursesLoading = true;
  if (!S.courses.length || refresh) {
    $('#course-list').innerHTML = `<div class="course-grid">${'<div class="card course"><div class="shimmer" style="height:18px;width:80%"></div><div class="shimmer" style="height:12px;width:40%"></div><div class="prog"><div class="shimmer" style="height:6px"></div></div></div>'.repeat(6)}</div>`;
    renderActionbar();
  }
  try {
    let j = await api('/courses' + (refresh ? '?refresh=1' : ''));
    S.courses = j.courses;
    renderCourseList();
    // 进度在后台逐个读取，读完前定时刷新卡片
    while (j.loading && token === S.pollToken && S.view === 'courses') {
      await sleep(1500);
      if (token !== S.pollToken) return;
      j = await api('/courses');
      S.courses = j.courses;
      renderCourseList();
    }
  } catch (e) {
    if (e.status === 401) { S.session.logged_in = false; return renderLogin('登录已失效，请重新登录'); }
    $('#course-list').innerHTML = `<div class="empty"><div class="big">课程读取失败</div><div>${esc(e.message)}</div><br><button class="btn" id="retry-courses">重试</button></div>`;
    $('#retry-courses').onclick = () => loadCourses(true, token);
  } finally {
    S.coursesLoading = false;
  }
}

function progressHTML(p) {
  if (!p) return '<div class="line"><span>正在读取进度…</span></div><div class="shimmer" style="height:6px"></div>';
  if (p.error) return '<div class="line"><span>进度读取失败</span></div><div class="bar"><i style="width:0"></i></div>';
  if (!p.total) return '<div class="line"><span>这门课没有章节</span></div>';
  const pct = Math.round((p.done / p.total) * 100);
  const complete = p.done >= p.total;
  return `<div class="line"><span>${complete ? '<span class="badge green">已全部完成</span>' : `已完成 ${p.done} / ${p.total} 章节`}${p.locked && !complete ? ' · <span title="有章节需要完成章节检测才能解锁，建议配置题库">需解锁</span>' : ''}</span><span>${pct}%</span></div>
    <div class="bar ${complete ? 'green' : ''}"><i style="width:${pct}%"></i></div>`;
}

function renderCourseList() {
  const list = $('#course-list');
  if (!list) return;
  const cs = visibleCourses();
  $('#course-count').textContent = S.courses.length ? `共 ${S.courses.length} 门` : '';
  if (!S.courses.length) {
    list.innerHTML = '<div class="empty"><div class="big">没有找到课程</div><div>学习通里还没有可学习的课程，或课程尚未开放</div></div>';
  } else if (!cs.length) {
    list.innerHTML = '<div class="empty"><div class="big">没有匹配的课程</div><div>换个关键词试试</div></div>';
  } else {
    list.innerHTML = `<div class="course-grid">${cs.map((c) => `
      <div class="card course ${S.selected.has(c.key) ? 'sel' : ''}" data-key="${esc(c.key)}" tabindex="0">
        <span class="check">${I.check}</span>
        <div class="title" title="${esc(c.title)}">${esc(c.title)}</div>
        <div class="meta">${esc(c.teacher || '未知教师')}${c.desc ? ' · ' + esc(c.desc) : ''}</div>
        <div class="prog">${progressHTML(c.progress)}</div>
      </div>`).join('')}</div>`;
    $$('.course', list).forEach((el) => {
      const toggle = () => {
        const k = el.dataset.key;
        S.selected.has(k) ? S.selected.delete(k) : S.selected.add(k);
        el.classList.toggle('sel', S.selected.has(k));
        saveSelection();
        renderActionbar();
      };
      el.onclick = toggle;
      el.onkeydown = (e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(); } };
    });
  }
  renderActionbar();
}

function settingsChips() {
  const st = S.settings || {};
  const c = st.common || {}, t = st.tiku || {};
  const speed = parseFloat(c.speed) || 1;
  const prov = (t.provider || '').trim();
  return `
    <span class="badge blue" data-open-settings>${speed}x 倍速</span>
    <span class="badge" data-open-settings>${parseInt(c.jobs) || 4} 个章节同时进行</span>
    <span class="badge ${prov ? 'green' : 'amber'}" data-open-settings>题库：${prov ? esc(providerName(prov)) : '未配置（跳过章节检测）'}</span>
    ${prov ? `<span class="badge" data-open-settings>${t.submit === 'true' ? '自动提交答案' : '只保存答案不提交'}</span>` : ''}`;
}

function renderActionbar() {
  const bar = $('#actionbar');
  if (!bar) return;
  const keys = new Set(S.courses.map((c) => c.key));
  const n = [...S.selected].filter((k) => keys.has(k)).length;
  bar.innerHTML = `
    <div class="info">
      <b>${n ? `已选 ${n} 门课程` : '点击课程卡片选择要学习的课程'}</b>
      <div class="chips">${settingsChips()}</div>
    </div>
    <button class="btn primary lg" id="btn-start" ${n ? '' : 'disabled'}>${I.play}开始学习</button>`;
  $$('[data-open-settings]', bar).forEach((b) => (b.onclick = () => openSettings()));
  $('#btn-start').onclick = startRun;
}

async function startRun() {
  const keys = S.courses.filter((c) => S.selected.has(c.key)).map((c) => c.key);
  if (!keys.length) return;
  const chosen = S.courses.filter((c) => S.selected.has(c.key));
  const prov = (S.settings?.tiku?.provider || '').trim();
  const locked = chosen.filter((c) => c.progress?.locked && !isComplete(c));
  if (!prov && locked.length) {
    const go = await confirmBox({
      title: '这些课程需要答题解锁',
      message: `「${esc(locked.map((c) => c.title).join('」「'))}」有章节需要先完成章节检测才能解锁后面的内容。没有配置题库时，程序会跳过答题，后面的章节可能学不了。`,
      ok: '仍然开始', cancel: '去配置题库',
    });
    if (!go) return openSettings('tiku');
  }
  const allDone = chosen.every(isComplete);
  if (allDone) {
    const go = await confirmBox({ title: '选中的课程都已完成', message: '这些课程的章节已经全部完成，再跑一遍只会快速检查一遍。', ok: '仍然开始' });
    if (!go) return;
  }
  const btn = $('#btn-start');
  btn.disabled = true;
  try {
    await api('/run', { keys });
    S.logs = []; S.logSeq = 0; S.open = new Set();
    showRun();
  } catch (e) {
    toast(e.message, 'error');
    btn.disabled = false;
  }
}

/* ======================= 运行页 ======================= */
const CH_LABEL = {
  done: '之前已完成', success: '本次完成', running: '进行中', pending: '等待中',
  waiting: '未开放，等待重试', retry: '出错，重试中', skipped: '未开放，已跳过', failed: '失败',
};

function showRun() {
  S.view = 'run';
  const token = ++S.pollToken;
  $('#main').innerHTML = `
    <div class="page">
      <div class="card run-head" id="run-head"></div>
      <div class="run-grid">
        <div>
          <div class="card section" id="jobs-sec"></div>
          <div class="card section" id="courses-sec"></div>
        </div>
        <div class="card section">
          <h3>运行日志
            <span class="right">
              <span class="seg" id="log-seg">
                <button data-f="all">全部</button><button data-f="warn">警告和错误</button>
              </span>
              <button class="btn ghost" id="reveal-log" title="在访达中显示完整日志文件">日志文件</button>
            </span>
          </h3>
          <div class="log-list" id="log-list"></div>
        </div>
      </div>
    </div>`;
  const seg = $('#log-seg');
  const syncSeg = () => $$('button', seg).forEach((b) => b.classList.toggle('on', b.dataset.f === S.logFilter));
  syncSeg();
  $$('button', seg).forEach((b) => (b.onclick = () => { S.logFilter = b.dataset.f; store.set('logFilter', S.logFilter); syncSeg(); renderLogs(true); }));
  $('#reveal-log').onclick = () => api('/reveal', { what: 'log' }).catch(() => {});
  renderLogs(true);
  pollRun(token);
}

async function pollRun(token) {
  let fails = 0;
  while (token === S.pollToken) {
    try {
      const j = await api('/run?since=' + S.logSeq);
      fails = 0;
      S.run = j.run;
      if (j.run.logs.length) {
        S.logs.push(...j.run.logs);
        if (S.logs.length > 3000) S.logs.splice(0, S.logs.length - 3000);
        S.logSeq = j.run.seq;
        appendLogs(j.run.logs);
      } else if (j.run.seq < S.logSeq) { // 后台重启过
        S.logs = []; S.logSeq = 0; renderLogs(true);
      }
      renderRun();
      if (j.run.status === 'idle') return showCourses();
    } catch (e) {
      if (++fails === 3) toast(e.message, 'error');
    }
    const active = S.run && ['starting', 'running', 'counting'].includes(S.run.status);
    await sleep(active ? 1000 : 3000);
  }
}

function countChapters(run) {
  const n = { done: 0, success: 0, running: 0, pending: 0, waiting: 0, retry: 0, skipped: 0, failed: 0, total: 0 };
  for (const c of run.courses) for (const ch of c.chapters) { n[ch.status] = (n[ch.status] || 0) + 1; n.total++; }
  return n;
}

function renderRun() {
  const run = S.run;
  if (!run || S.view !== 'run') return;
  const n = countChapters(run);
  const finished = n.done + n.success;
  const pct = n.total ? Math.round((finished / n.total) * 100) : 0;
  const active = ['starting', 'running', 'counting'].includes(run.status);
  const elapsed = (run.ended || run.now) - (run.started || run.now);

  const st = {
    starting: ['running', I.play, run.phase || '正在准备…', '马上就好，正在登录并读取章节'],
    running: ['running', I.play, '正在学习', `已运行 ${fmtDuration(elapsed)} · ${run.speed}x 倍速 · 期间电脑不会自动休眠`],
    counting: ['running', I.play, '正在增加章节学习次数', `已运行 ${fmtDuration(elapsed)}`],
    done: ['done', I.done, '学习完成', `用时 ${fmtDuration(elapsed)}`],
    stopped: ['stopped', I.pause, '已停止', `运行了 ${fmtDuration(elapsed)}，已完成的进度会保留在学习通`],
    error: ['error', I.alert, '出错了', `运行了 ${fmtDuration(elapsed)}`],
  }[run.status] || ['stopped', I.pause, run.phase || '空闲', ''];

  const head = $('#run-head');
  head.innerHTML = `
    <div class="top">
      <div class="state-icon ${st[0]}">${st[1]}</div>
      <div class="grow">
        <h2>${esc(st[2])}${run.status === 'starting' ? ' <span class="spinner sm" style="display:inline-block;vertical-align:-2px"></span>' : ''}</h2>
        <div class="sub">${esc(st[3])}${run.selected?.length ? ' · ' + esc(run.selected.length > 2 ? `${run.selected.slice(0, 2).join('、')} 等 ${run.selected.length} 门课程` : run.selected.join('、')) : ''}</div>
      </div>
      ${active
        ? `<button class="btn danger" id="btn-stop" ${run.phase === '正在停止…' ? 'disabled' : ''}>${I.stop}${run.phase === '正在停止…' ? '正在停止…' : '停止'}</button>`
        : `<button class="btn" id="btn-again">${I.refresh}再来一次</button><button class="btn primary" id="btn-back">返回课程列表</button>`}
    </div>
    ${run.status === 'error' ? `<div class="err-box selectable">${esc(run.error)}${/login|登录|密码/i.test(run.error) ? '<br>可以尝试退出登录后重新登录。' : ''}</div>` : ''}
    ${n.total ? `
      <div class="overall">
        <div class="line"><span>总进度：已完成 ${finished} / ${n.total} 个章节</span><span>${pct}%</span></div>
        <div class="bar lg ${run.status === 'done' ? 'green' : ''}"><i style="width:${pct}%"></i></div>
      </div>
      <div class="stats">
        <div class="stat green"><div class="n">${n.success}</div><div class="l">本次完成</div></div>
        <div class="stat"><div class="n">${n.done}</div><div class="l">之前已完成</div></div>
        <div class="stat"><div class="n">${n.running + n.pending + n.waiting + n.retry}</div><div class="l">${active ? '进行中 / 等待' : '未处理'}</div></div>
        <div class="stat ${n.failed ? 'red' : n.skipped ? 'amber' : ''}"><div class="n">${n.skipped + n.failed}</div><div class="l">跳过 / 失败</div></div>
      </div>` : ''}`;
  $('#btn-stop') && ($('#btn-stop').onclick = stopRun);
  $('#btn-back') && ($('#btn-back').onclick = async () => { await api('/run/clear', {}).catch(() => {}); S.run = null; showCourses(true); });
  $('#btn-again') && ($('#btn-again').onclick = async () => {
    await api('/run/clear', {}).catch(() => {});
    try {
      await api('/run', { keys: run.selected_keys || [] });
      S.logs = []; S.logSeq = 0; renderLogs(true); showRun();
    } catch (e) { toast(e.message, 'error'); showCourses(); }
  });

  // 正在进行的任务
  const jobs = run.jobs;
  $('#jobs-sec').innerHTML = `
    <h3>正在进行 ${jobs.length ? `<span class="badge blue">${jobs.length}</span>` : ''}</h3>
    ${jobs.length ? jobs.map((j) => jobHTML(j, run.speed)).join('') :
      `<div class="hint">${active ? (run.status === 'starting' ? esc(run.phase) : '正在检查章节…') : '没有正在进行的任务'}</div>`}
    ${run.recent.length ? `<h3 style="margin-top:14px">刚刚完成</h3>${run.recent.slice(0, 5).map((j) => `
      <div class="job small"><div class="head">
        <span class="badge ${j.result === 'SUCCESS' ? 'green' : 'red'}">${esc(j.kind)}</span>
        <span class="name" title="${esc(j.name)}">${esc(j.name)}</span>
        <span class="hint">${j.result === 'SUCCESS' ? '完成' : '未成功'}</span>
      </div></div>`).join('')}` : ''}`;

  // 各课程进度
  const sec = $('#courses-sec');
  if (!run.courses.length) { sec.innerHTML = '<h3>课程进度</h3><div class="hint">正在读取章节…</div>'; return; }
  if (run.courses.length === 1 && !S.open.size) S.open.add(run.courses[0].key);
  sec.innerHTML = `<h3>课程进度</h3>${run.courses.map((c) => {
    const total = c.chapters.length;
    const fin = c.chapters.filter((ch) => ch.status === 'done' || ch.status === 'success').length;
    const p = total ? Math.round((fin / total) * 100) : 100;
    return `
      <div class="course-prog ${S.open.has(c.key) ? 'open' : ''}" data-key="${esc(c.key)}">
        <div class="head">${I.chev}<span class="t" title="${esc(c.title)}">${esc(c.title)}</span>
          <span class="num">${fin}/${total}</span><div class="bar ${fin === total ? 'green' : ''}"><i style="width:${p}%"></i></div></div>
        <div class="chapters">${c.chapters.map((ch) => `
          <div class="chapter ${ch.status}" title="${esc(CH_LABEL[ch.status] || '')}"><span class="dot ${ch.status}"></span><span class="t">${esc(ch.title)}</span>
          ${['running', 'waiting', 'retry', 'skipped', 'failed', 'success'].includes(ch.status) ? `<span class="hint">${esc(CH_LABEL[ch.status])}</span>` : ''}</div>`).join('')}
        </div>
      </div>`;
  }).join('')}
  <div class="legend">
    <span><i class="dot success"></i>本次完成</span><span><i class="dot done"></i>之前已完成</span>
    <span><i class="dot running"></i>进行中</span><span><i class="dot waiting"></i>未开放/重试中</span>
    <span><i class="dot skipped"></i>已跳过</span><span><i class="dot failed"></i>失败</span>
  </div>`;
  $$('.course-prog > .head', sec).forEach((h) => (h.onclick = () => {
    const el = h.parentElement, k = el.dataset.key;
    S.open.has(k) ? S.open.delete(k) : S.open.add(k);
    el.classList.toggle('open');
  }));
}

function jobHTML(j, speed) {
  const where = [j.course_title, j.chapter_title].filter(Boolean).join(' · ');
  let body = '';
  if (j.total > 0) {
    const pct = Math.min(100, Math.round((j.n / j.total) * 100));
    body = `<div class="bar"><i style="width:${pct}%"></i></div>
      <div class="time"><span>${fmtTime(j.n)} / ${fmtTime(j.total)}</span><span>还需约 ${fmtDuration((j.total - j.n) / (speed || 1))}</span></div>`;
  } else {
    body = `<div class="hint">${j.kind === '章节检测' ? '正在查题作答…' : '处理中…'}</div>`;
  }
  return `<div class="job">
    <div class="head"><span class="badge blue">${esc(j.kind)}</span><span class="name" title="${esc(j.name)}">${esc(j.name)}</span></div>
    ${where ? `<div class="where" title="${esc(where)}">${esc(where)}</div>` : ''}
    ${body}
  </div>`;
}

async function stopRun() {
  const yes = await confirmBox({ title: '停止学习？', message: '已经完成的章节进度会保存在学习通，正在播放的视频会从当前进度继续，下次可以接着学。', ok: '停止', danger: true });
  if (!yes) return;
  try { await api('/stop', {}); } catch (e) { toast(e.message, 'error'); }
}

const isWarn = (l) => ['WARNING', 'ERROR', 'CRITICAL'].includes(l.level);

function logLine(l) {
  const d = document.createElement('div');
  d.className = 'l ' + l.level;
  d.innerHTML = `<span class="ts">${esc(l.ts)}</span><span>${esc(l.msg)}</span>`;
  return d;
}

function renderLogs(reset) {
  const box = $('#log-list');
  if (!box) return;
  if (reset) box.innerHTML = '';
  const items = S.logs.filter((l) => S.logFilter === 'all' || isWarn(l)).slice(-800);
  const frag = document.createDocumentFragment();
  items.forEach((l) => frag.appendChild(logLine(l)));
  box.appendChild(frag);
  if (!items.length) box.innerHTML = `<div class="hint">${S.logFilter === 'all' ? '暂无日志' : '没有警告或错误'}</div>`;
  box.scrollTop = box.scrollHeight;
}

function appendLogs(entries) {
  const box = $('#log-list');
  if (!box) return;
  const show = entries.filter((l) => S.logFilter === 'all' || isWarn(l));
  if (!show.length) return;
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  if (box.firstElementChild?.classList.contains('hint')) box.innerHTML = '';
  show.forEach((l) => box.appendChild(logLine(l)));
  while (box.childElementCount > 800) box.firstElementChild.remove();
  if (nearBottom) box.scrollTop = box.scrollHeight;
}

/* ======================= 设置 ======================= */
const F = {
  range: (sec, key, label, { min, max, step, fmt, hint, def }) => `
    <div class="row-item"><div class="lbl"><b>${label}</b>${hint ? `<span class="hint ${hint.warn ? 'warn' : ''}">${hint.text}</span>` : ''}</div>
    <div class="range-wrap"><input type="range" min="${min}" max="${max}" step="${step}" data-sec="${sec}" data-key="${key}" data-fmt="${fmt}" value="${esc(val(sec, key, def))}"><output></output></div></div>`,
  number: (sec, key, label, { min, max, hint, def }) => `
    <div class="row-item"><div class="lbl"><b>${label}</b>${hint ? `<span class="hint">${hint}</span>` : ''}</div>
    <input class="input num-input" type="number" min="${min}" max="${max}" data-sec="${sec}" data-key="${key}" value="${esc(val(sec, key, def))}"></div>`,
  toggle: (sec, key, label, hint) => `
    <div class="row-item"><div class="lbl"><b>${label}</b>${hint ? `<span class="hint">${hint}</span>` : ''}</div>
    <label class="switch"><input type="checkbox" data-sec="${sec}" data-key="${key}" data-bool ${val(sec, key) === 'true' ? 'checked' : ''}><span></span></label></div>`,
  text: (sec, key, label, { placeholder = '', hint = '', secret = false } = {}) => `
    <div class="row-item col"><div class="lbl"><b>${label}</b>${hint ? `<span class="hint">${hint}</span>` : ''}</div>
    <input class="input" type="${secret ? 'password' : 'text'}" spellcheck="false" autocomplete="off" placeholder="${esc(placeholder)}" data-sec="${sec}" data-key="${key}" value="${esc(val(sec, key))}"></div>`,
  seg: (sec, key, label, options, hint, def) => `
    <div class="row-item"><div class="lbl"><b>${label}</b>${hint ? `<span class="hint">${hint}</span>` : ''}</div>
    <span class="seg" data-seg data-sec="${sec}" data-key="${key}" data-value="${esc(val(sec, key, def))}">
      ${options.map(([v, t]) => `<button type="button" data-v="${v}">${t}</button>`).join('')}</span></div>`,
  select: (sec, key, label, options, hint) => `
    <div class="row-item col"><div class="lbl"><b>${label}</b>${hint ? `<span class="hint">${hint}</span>` : ''}</div>
    <select class="input" data-sec="${sec}" data-key="${key}">${options.map(([v, t]) => `<option value="${esc(v)}" ${val(sec, key) === v ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></div>`,
};
const val = (sec, key, def = '') => {
  const v = S.settings?.[sec]?.[key];
  return v === undefined || v === '' ? String(def) : v;
};
const link = (url, text) => `<a href="${url}" target="_blank" rel="noopener" style="color:var(--accent)">${text}</a>`;

function tikuBlocks() {
  return {
    TikuYanxi: F.text('tiku', 'tokens', '言溪题库 Token', { placeholder: '多个 Token 用英文逗号分隔', hint: `在 ${link('https://tk.enncy.cn/', 'tk.enncy.cn')} 获取` }),
    TikuLike: F.text('tiku', 'tokens', 'LIKE 知识库 Token', { placeholder: '多个 Token 用英文逗号分隔', hint: `在 ${link('https://www.datam.site/', 'datam.site')} 获取` })
      + F.text('tiku', 'likeapi_model', '模型', { placeholder: 'glm-4.5-air' })
      + F.toggle('tiku', 'likeapi_search', '联网搜索')
      + F.toggle('tiku', 'likeapi_vision', '识别图片题'),
    TikuGo: F.text('tiku', 'go_authorization', '解除限流 Token（可选）', { hint: `不填也能用，只是有频率限制。题库地址 ${link('https://q.icodef.com/', 'q.icodef.com')}` }),
    TikuAdapter: F.text('tiku', 'url', 'TikuAdapter 服务地址', { placeholder: 'http://127.0.0.1:8060/adapter-service/search', hint: `开源项目 ${link('https://github.com/DokiDoki1103/tikuAdapter', 'tikuAdapter')}` }),
    AI: F.text('tiku', 'endpoint', 'API 地址', { placeholder: 'https://api.example.com/v1', hint: '兼容 OpenAI 格式的接口，通常要以 /v1 结尾' })
      + F.text('tiku', 'key', 'API Key', { secret: true, placeholder: 'sk-…' })
      + F.text('tiku', 'model', '模型名称', { placeholder: '例如 deepseek-chat、gpt-4o-mini' })
      + F.number('tiku', 'min_interval_seconds', '请求间隔（秒）', { min: 0, max: 60, def: 3 })
      + F.text('tiku', 'http_proxy', '代理（可选）', { placeholder: 'http://127.0.0.1:7890' }),
    SiliconFlow: F.text('tiku', 'siliconflow_key', '硅基流动 API Key', { secret: true, hint: `在 ${link('https://cloud.siliconflow.cn/account/ak', '硅基流动控制台')} 获取` })
      + F.text('tiku', 'siliconflow_model', '模型', { placeholder: 'deepseek-ai/DeepSeek-V3' })
      + F.text('tiku', 'siliconflow_endpoint', '接口地址', { placeholder: 'https://api.siliconflow.cn/v1/chat/completions' }),
  };
}

async function openSettings(focus) {
  try { S.settings = (await api('/settings')).settings; } catch (e) { return toast(e.message, 'error'); }
  const curProv = (val('tiku', 'provider') || '').trim();
  const provOptions = PROVIDERS.map((p) => [p.id, p.name]);
  if (curProv && !PROVIDERS.some((p) => p.id === curProv)) provOptions.push([curProv, `多个题库：${curProv}`]);
  const blocks = tikuBlocks();
  const running = S.run && ['starting', 'running', 'counting'].includes(S.run.status);

  $('#sheet-root').innerHTML = `
    <div class="sheet-backdrop"></div>
    <div class="sheet" role="dialog">
      <header><h2>设置</h2><button class="btn ghost icon" id="sheet-close">${I.close}</button></header>
      <div class="body">
        ${running ? '<div class="badge amber" style="padding:6px 10px;border-radius:8px">正在学习中，修改会在下次开始时生效</div>' : ''}
        <div class="group"><h4>学习</h4><div class="card">
          ${F.range('common', 'speed', '视频倍速', { min: 1, max: 2, step: 0.25, fmt: 'x', def: 1, hint: { text: '倍速越高越容易被平台检测到异常，建议 1 ~ 1.5 倍', warn: true } })}
          ${F.number('common', 'jobs', '同时进行的章节数', { min: 1, max: 8, def: 4, hint: '数量越多越快，但请求也更频繁' })}
          ${F.seg('common', 'notopen_action', '遇到未开放的章节', [['retry', '等待重试'], ['continue', '直接跳过']], '需要按顺序解锁的课程选「等待重试」', 'retry')}
          ${F.toggle('common', 'add_learning_count', '学完后刷章节学习次数', '有些课程会考核章节访问次数')}
          <div data-lc>${F.number('common', 'target_count', '目标学习次数', { min: 1, max: 10000, def: 100 })}</div>
        </div></div>

        <div class="group" id="grp-tiku"><h4>题库（用于章节检测答题）</h4><div class="card">
          ${F.select('tiku', 'provider', '使用的题库', provOptions, '不配置题库时，章节检测会被跳过')}
          ${Object.entries(blocks).map(([id, html]) => `<div data-prov="${id}">${html}</div>`).join('')}
          <div data-prov-any>
            ${F.toggle('tiku', 'submit', '答完自动提交', '关闭时只保存答案，你可以去学习通检查后再手动提交；需要解锁下一章的课程建议开启')}
            ${F.range('tiku', 'cover_rate', '最低题库覆盖率', { min: 0.5, max: 1, step: 0.05, fmt: '%', def: 0.9, hint: { text: '搜到答案的题目比例达到这个值才会自动提交' } })}
            ${F.toggle('common', 'work_redo_enabled', '答错后自动重做', '只对 AI 题库有用；只允许作答一次的课程不要开')}
          </div>
        </div></div>

        <div class="group"><h4>完成通知</h4><div class="card">
          ${F.select('notification', 'provider', '推送到手机', [['', '不推送（只在 Mac 上弹通知）'], ['ServerChan', 'Server 酱（微信）'], ['Qmsg', 'Qmsg 酱（QQ）'], ['Bark', 'Bark（iPhone）'], ['Telegram', 'Telegram']], '学完或出错时推送提醒')}
          <div data-notif>
            ${F.text('notification', 'url', '推送地址', { placeholder: 'https://sctapi.ftqq.com/你的key.send', hint: 'Server 酱、Qmsg 酱、Bark 或 Telegram Bot 的完整推送地址' })}
            <div data-tg>${F.text('notification', 'tg_chat_id', 'Telegram Chat ID')}</div>
          </div>
        </div></div>

        <div class="group"><h4>其他</h4><div class="card">
          <div class="row-item col">
            <div class="lbl"><span class="hint">设置保存在项目的 config.ini 中，命令行版也会读取同一份配置。</span></div>
            <div class="links">
              <button class="btn" data-reveal="config">显示配置文件</button>
              <button class="btn" data-reveal="log">显示日志文件</button>
              <button class="btn" data-reveal="folder">打开项目文件夹</button>
            </div>
          </div>
        </div></div>
      </div>
      <footer><button class="btn" id="sheet-cancel">取消</button><button class="btn primary" id="sheet-save">保存</button></footer>
    </div>`;

  const sheet = $('.sheet');
  const close = () => { $('#sheet-root').innerHTML = ''; document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape' && !$('#modal-root').innerHTML) close(); };
  document.addEventListener('keydown', onKey);
  $('.sheet-backdrop').onclick = close;
  $('#sheet-close').onclick = close;
  $('#sheet-cancel').onclick = close;

  // 滑块显示数值
  $$('input[type=range]', sheet).forEach((r) => {
    const out = r.nextElementSibling;
    const upd = () => { out.textContent = r.dataset.fmt === '%' ? Math.round(r.value * 100) + '%' : r.value + 'x'; };
    r.oninput = upd; upd();
  });
  // 分段选择
  $$('[data-seg]', sheet).forEach((s) => {
    const sync = () => $$('button', s).forEach((b) => b.classList.toggle('on', b.dataset.v === s.dataset.value));
    $$('button', s).forEach((b) => (b.onclick = () => { s.dataset.value = b.dataset.v; sync(); }));
    sync();
  });
  // 题库 / 通知联动显示
  const provSel = $('select[data-key=provider][data-sec=tiku]', sheet);
  const notifSel = $('select[data-key=provider][data-sec=notification]', sheet);
  const syncVis = () => {
    $$('[data-prov]', sheet).forEach((el) => (el.style.display = el.dataset.prov === provSel.value ? '' : 'none'));
    $('[data-prov-any]', sheet).style.display = provSel.value ? '' : 'none';
    $('[data-notif]', sheet).style.display = notifSel.value ? '' : 'none';
    $('[data-tg]', sheet).style.display = notifSel.value === 'Telegram' ? '' : 'none';
  };
  const lcBox = $('input[data-key=add_learning_count]', sheet);
  const syncLc = () => ($('[data-lc]', sheet).style.display = lcBox.checked ? '' : 'none');
  lcBox.onchange = syncLc; syncLc();
  provSel.onchange = syncVis; notifSel.onchange = syncVis; syncVis();
  $$('[data-reveal]', sheet).forEach((b) => (b.onclick = () => api('/reveal', { what: b.dataset.reveal }).catch(() => {})));
  if (focus === 'tiku') { $('#grp-tiku').scrollIntoView({ block: 'start' }); provSel.focus(); }

  $('#sheet-save').onclick = async () => {
    const out = { common: {}, tiku: {}, notification: {} };
    $$('[data-key]', sheet).forEach((el) => {
      if (el.closest('[style*="display: none"]')) return; // 隐藏的题库字段不保存（如两个题库共用 tokens）
      const v = el.matches('[data-seg]') ? el.dataset.value : el.matches('[data-bool]') ? (el.checked ? 'true' : 'false') : el.value.trim();
      out[el.dataset.sec][el.dataset.key] = v;
    });
    const speed = parseFloat(out.common.speed);
    if (speed > 1.5) {
      const go = await confirmBox({ title: `确定使用 ${speed} 倍速？`, message: '倍速过高更容易被学习通检测为异常学习，可能被清除进度或记录异常。', ok: '确定' });
      if (!go) return;
    }
    try {
      S.settings = (await api('/settings', out)).settings;
      close();
      toast('设置已保存');
      renderActionbar();
    } catch (e) { toast(e.message, 'error'); }
  };
}

/* ======================= 杂项 ======================= */
// 外部链接用系统浏览器打开（在 Mac 应用里由外壳处理 target=_blank）
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === ',') { e.preventDefault(); if (S.session?.logged_in) openSettings(); }
  if ((e.metaKey || e.ctrlKey) && e.key === 'r') { e.preventDefault(); if (S.view === 'courses') showCourses(true); }
});

boot();
