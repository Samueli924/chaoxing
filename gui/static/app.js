'use strict';

/* ======================= 基础工具 ======================= */
const TOKEN = new URLSearchParams(location.search).get('t') || '';
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const enc = encodeURIComponent;

/* 连接中断处理：电脑睡眠唤醒、网络切换等会让进行中的请求失败。
   读取类请求自动重试；持续失败时显示「正在重连」横幅而不是报错；恢复后把失败情况记到后台日志。 */
const NET = { since: 0, failures: [], lastTick: Date.now() };

function noteNetFailure(path, e) {
  if (!NET.since) NET.since = Date.now();
  if (NET.failures.length < 20) NET.failures.push({ path, err: String(e), at: new Date().toLocaleTimeString() });
  updateNetBanner();
}

function noteNetSuccess() {
  if (!NET.since) return;
  const report = { seconds: (Date.now() - NET.since) / 1000, failures: NET.failures, slept: NET.slept || false };
  NET.since = 0; NET.failures = []; NET.slept = false;
  updateNetBanner();
  fetch('/api/client_log', { method: 'POST', headers: { 'X-Token': TOKEN, 'Content-Type': 'application/json' }, body: JSON.stringify(report) }).catch(() => {});
}

function updateNetBanner() {
  let el = document.getElementById('net-banner');
  const down = NET.since ? (Date.now() - NET.since) / 1000 : 0;
  if (down < 4) { el?.remove(); return; }
  if (!el) { el = document.createElement('div'); el.id = 'net-banner'; document.body.appendChild(el); }
  el.innerHTML = down < 30
    ? '<span class="spinner sm"></span> 与后台的连接中断，正在重连…'
    : '后台服务长时间没有响应，可以尝试退出后重新打开应用';
}

// 定时检查：横幅计时；计时器明显"迟到"说明电脑刚从睡眠中唤醒，立即刷新状态
setInterval(() => {
  const now = Date.now();
  if (now - NET.lastTick > 15000) {
    NET.slept = true;
    if (S.accounts.some((a) => ACTIVE.includes(a.status))) {
      toast(`电脑睡眠了约 ${fmtDuration((now - NET.lastTick) / 1000)}，期间学习暂停，现在继续进行。合上盖子会让电脑睡眠`);
    }
    if (S.view !== 'welcome' && S.accounts.length) {
      api('/state').then((st) => { applyState(st); renderSidebar(); renderTopActions(); route(false); }).catch(() => {});
    }
  }
  NET.lastTick = now;
  updateNetBanner();
}, 1000);

async function api(path, body) {
  const isGet = body === undefined;
  const opts = { method: isGet ? 'GET' : 'POST', headers: { 'X-Token': TOKEN } };
  if (!isGet) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let r;
  for (let attempt = 0; ; attempt++) {
    try {
      r = await fetch('/api' + path, opts);
      break;
    } catch (e) {
      noteNetFailure(path, e);
      // 只自动重试读取类请求；提交类请求可能已经被后台执行，交给用户决定是否重试
      if (isGet && attempt < 2) { await sleep(attempt ? 1500 : 500); continue; }
      const err = new Error('与后台的连接暂时中断了，请稍后再试');
      err.network = true;
      throw err;
    }
  }
  noteNetSuccess();
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) {
    const err = new Error(j.msg || `请求失败（${r.status}）`);
    err.status = r.status;
    throw err;
  }
  return j;
}
const acctApi = (phone, path, body) => api(`/accounts/${enc(phone)}${path}`, body);

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

function modal(html, { onOpen } = {}) {
  return new Promise((resolve) => {
    const root = $('#modal-root');
    root.innerHTML = `<div class="modal-backdrop"><div class="modal card" role="dialog">${html}</div></div>`;
    const done = (v) => { root.innerHTML = ''; document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') done(false); };
    document.addEventListener('keydown', onKey);
    $('.modal-backdrop', root).addEventListener('click', (e) => { if (e.target === e.currentTarget) done(false); });
    onOpen && onOpen($('.modal', root), done);
  });
}

function confirmBox({ title, message, ok = '确定', cancel = '取消', danger = false }) {
  return modal(`
    <h3>${esc(title)}</h3>
    ${message ? `<p>${message}</p>` : ''}
    <div class="btns">
      ${cancel ? `<button class="btn" data-r="0">${esc(cancel)}</button>` : ''}
      <button class="btn ${danger ? 'danger solid' : 'primary'}" data-r="1">${esc(ok)}</button>
    </div>`, {
    onOpen(m, done) {
      $$('[data-r]', m).forEach((b) => b.addEventListener('click', () => done(b.dataset.r === '1')));
      m.addEventListener('keydown', (e) => { if (e.key === 'Enter') done(true); });
      $('.btn.primary, .btn.solid', m)?.focus();
    },
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
const fmtClock = (ts) => { const d = new Date(ts * 1000); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };
const maskPhone = (p) => (p && p.length >= 7 ? p.slice(0, 3) + '****' + p.slice(-4) : p || '');
const ACTIVE = ['starting', 'running', 'counting'];
const BUSY = [...ACTIVE, 'queued'];

/* ======================= 图标 ======================= */
const I = {
  logo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 10 12 5 2 10l10 5 10-5Z"/><path d="M6 12v5c3 2 9 2 12 0v-5"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.9l10-6.5a1 1 0 0 0 0-1.7l-10-6.5A1 1 0 0 0 8 5.5Z"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  done: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9.5"/><path d="m8 12 3 3 5-6"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9.5"/><path d="M12 7.5v5.5"/><path d="M12 16.5h.01"/></svg>',
  pause: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9.5"/><path d="M10 9v6M14 9v6"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9.5"/><path d="M12 7v5l3 2"/></svg>',
  chev: '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m9 6 6 6-6 6"/></svg>',
  eye: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.5 3.4-5.5 6.5-5.5s5.7 2 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18.5 14.8c1.6.8 2.6 2.6 3 5.2"/></svg>',
};

/* ======================= 全局状态 ======================= */
const S = {
  accounts: [],
  scheduler: {},
  canRemember: true,
  current: store.get('current', ''),
  per: {}, // phone -> { courses, selected:Set, filter, loading, logs, logSeq, open:Set, run }
  settings: null,
  view: '',
  viewKey: '',
  viewToken: 0,
  logFilter: store.get('logFilter', 'all'),
};
const cur = () => S.accounts.find((a) => a.phone === S.current);
function per(phone) {
  if (!S.per[phone]) S.per[phone] = { courses: [], selected: new Set(), filter: '', logs: [], logSeq: 0, open: new Set(), run: null, loaded: false };
  return S.per[phone];
}

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
  app.innerHTML = '<div class="splash"><div class="spinner"></div><p>正在启动…</p></div>';
  try {
    const [st, set] = await Promise.all([api('/state'), api('/settings')]);
    applyState(st);
    S.settings = set.settings;
  } catch (e) {
    app.innerHTML = `<div class="splash"><p>${esc(e.message)}</p><button class="btn" onclick="boot()">重试</button></div>`;
    return;
  }
  if (!S.accounts.length) return renderWelcome();
  renderShell();
  route(true);
  stateLoop();
}

function applyState(st) {
  S.accounts = st.accounts;
  S.scheduler = st.scheduler;
  S.canRemember = st.can_remember;
  if (!S.accounts.some((a) => a.phone === S.current)) S.current = S.accounts[0]?.phone || '';
}

let stateLoopRunning = false;
async function stateLoop() {
  if (stateLoopRunning) return;
  stateLoopRunning = true;
  while (S.accounts.length || S.view !== 'welcome') {
    await sleep(S.accounts.some((a) => BUSY.includes(a.status) || a.auth === 'checking') ? 1500 : 3000);
    if (S.view === 'welcome') continue;
    try {
      applyState(await api('/state'));
      renderSidebar();
      renderTopActions();
      route(false);
    } catch { /* 下次再试 */ }
  }
  stateLoopRunning = false;
}

/** 根据当前账号的状态决定主区域显示什么；状态类别没变时不重建页面 */
function route(force) {
  const a = cur();
  if (!a) { if (!S.accounts.length) renderWelcome(); return; }
  let key;
  if (a.auth === 'checking' || a.auth === 'unknown') key = 'checking';
  else if (a.auth !== 'ok') key = 'login';
  else if (a.status !== 'idle') key = 'run';
  else key = 'courses';
  const viewKey = a.phone + ':' + key;
  if (!force && viewKey === S.viewKey) {
    if (key === 'courses') renderActionbar();
    return;
  }
  S.viewKey = viewKey;
  if (key === 'checking') showChecking(a);
  else if (key === 'login') showRelogin(a);
  else if (key === 'run') showRun(a);
  else showCourses(a);
}

function selectAccount(phone) {
  S.current = phone;
  store.set('current', phone);
  renderSidebar();
  route(true);
}

/* ======================= 登录表单 ======================= */
function loginFormHTML({ phone = '', err = '', submit = '登录', lockPhone = false }) {
  return `
    ${err ? `<div class="err">${esc(err)}</div>` : ''}
    <div class="field">
      <label for="f-phone">手机号</label>
      <input class="input" id="f-phone" name="username" inputmode="numeric" autocomplete="username" placeholder="学习通绑定的手机号" value="${esc(phone)}" ${lockPhone ? 'readonly' : ''}>
    </div>
    <div class="field">
      <label for="f-pwd">密码</label>
      <div class="pwd-wrap">
        <input class="input" id="f-pwd" type="password" name="password" autocomplete="current-password" placeholder="学习通登录密码">
        <button type="button" class="btn ghost icon" id="f-toggle" title="显示密码">${I.eye}</button>
      </div>
    </div>
    ${S.canRemember ? `<label class="row"><span>记住密码，下次自动登录<br><span class="hint">密码保存在系统钥匙串中</span></span>
      <span class="switch"><input type="checkbox" id="f-remember" checked><span></span></span></label>`
      : '<p class="hint" style="margin:0">登录状态会保存在本机，过期后需要重新输入密码</p>'}
    <button class="btn primary lg" type="submit" id="f-submit">${esc(submit)}</button>`;
}

function bindLoginForm(form, onSuccess) {
  const phoneEl = $('#f-phone', form), pwdEl = $('#f-pwd', form);
  (phoneEl.value ? pwdEl : phoneEl).focus();
  $('#f-toggle', form).onclick = () => { pwdEl.type = pwdEl.type === 'password' ? 'text' : 'password'; };
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = $('#f-submit', form);
    const body = { phone: phoneEl.value.trim(), password: pwdEl.value, remember: $('#f-remember', form)?.checked ?? false };
    if (!body.phone || !body.password) return toast('请填写手机号和密码', 'error');
    const label = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner sm"></span> 正在登录…';
    try {
      const j = await api('/accounts', body);
      onSuccess(j.account);
    } catch (err) {
      btn.disabled = false;
      btn.innerHTML = label;
      let box = $('.err', form);
      if (!box) { box = document.createElement('div'); box.className = 'err'; form.prepend(box); }
      box.textContent = err.message;
      pwdEl.select();
    }
  };
}

function renderWelcome() {
  S.view = 'welcome';
  S.viewKey = '';
  $('#app').innerHTML = `
    <div class="login-wrap">
      <form class="login card" autocomplete="on">
        <div class="logo">${I.logo}</div>
        <h1>刷课助手</h1>
        <p class="sub">登录你的超星学习通账号</p>
        ${loginFormHTML({})}
        <p class="hint" style="text-align:center;margin:0">密码只用于登录学习通，不会上传到别处</p>
      </form>
    </div>`;
  bindLoginForm($('.login'), async (acct) => {
    toast(`登录成功${acct.name ? '，欢迎 ' + acct.name : ''}`);
    S.current = acct.phone;
    store.set('current', acct.phone);
    applyState(await api('/state'));
    renderShell();
    route(true);
    stateLoop();
  });
}

function addAccountDialog() {
  return modal(`
    <h3>添加账号</h3>
    <p>添加多个账号后，可以一键按顺序排队学习。</p>
    <form class="login-inline" autocomplete="on">${loginFormHTML({ submit: '登录并添加' })}</form>
    <div class="btns"><button class="btn" data-cancel>取消</button></div>`, {
    onOpen(m, done) {
      $('[data-cancel]', m).onclick = () => done(false);
      bindLoginForm($('form', m), async (acct) => {
        done(true);
        toast(`已添加 ${acct.name || maskPhone(acct.phone)}`);
        applyState(await api('/state'));
        selectAccount(acct.phone);
      });
    },
  });
}

/* ======================= 主框架 ======================= */
function renderShell() {
  S.view = 'shell';
  $('#app').innerHTML = `
    <div class="topbar">
      <div class="brand"><i>${I.logo}</i>刷课助手</div>
      <div class="spacer"></div>
      <div id="top-actions" class="tools"></div>
      <button class="btn ghost" id="btn-settings">${I.gear}设置</button>
    </div>
    <div class="body">
      <aside class="sidebar">
        <div class="side-head">账号 <span class="hint" id="acct-count"></span></div>
        <div class="acct-list" id="acct-list"></div>
        <button class="btn ghost add-acct" id="btn-add">${I.plus}添加账号</button>
        <div class="side-foot" id="side-foot"></div>
      </aside>
      <div class="main" id="main"></div>
    </div>`;
  $('#btn-settings').onclick = () => openSettings();
  $('#btn-add').onclick = () => addAccountDialog();
  renderSidebar();
  renderTopActions();
}

function acctStatus(a) {
  if (a.auth === 'checking' || a.auth === 'unknown') return ['', '正在登录…'];
  if (a.auth !== 'ok') return ['red', '需要重新登录'];
  const pct = a.total ? Math.round((a.finished / a.total) * 100) : 0;
  switch (a.status) {
    case 'queued':
      if (a.queue?.eta) return ['amber', a.queue.eta - Date.now() / 1000 < 30 ? '排队中 · 即将开始' : `排队中 · 约 ${fmtClock(a.queue.eta)} 开始`];
      return ['amber', `排队中 · 第 ${a.queue?.position || '?'} 位，等待空位`];
    case 'starting': return ['blue', '正在启动…'];
    case 'running': return ['blue', `学习中 · ${pct}%`];
    case 'counting': return ['blue', '刷学习次数中'];
    case 'done': return ['green', '已完成'];
    case 'stopped': return ['', '已停止'];
    case 'error': return ['red', '出错了'];
    default: return ['', a.selected_count ? `空闲 · 已选 ${a.selected_count} 门课` : '空闲 · 未选课'];
  }
}

function renderSidebar() {
  const list = $('#acct-list');
  if (!list) return;
  $('#acct-count').textContent = S.accounts.length > 1 ? `${S.accounts.length} 个` : '';
  list.innerHTML = S.accounts.map((a) => {
    const [cls, text] = acctStatus(a);
    const name = a.name || '未知姓名';
    const pct = a.total ? Math.round((a.finished / a.total) * 100) : 0;
    return `
      <div class="acct ${a.phone === S.current ? 'on' : ''}" data-phone="${esc(a.phone)}" tabindex="0">
        <span class="avatar ${ACTIVE.includes(a.status) ? 'live' : ''}">${esc(name.slice(-1))}</span>
        <div class="info">
          <div class="nm">${esc(name)} <span class="ph">${esc(maskPhone(a.phone))}</span></div>
          <div class="st ${cls}">${esc(text)}</div>
          ${ACTIVE.includes(a.status) && a.total ? `<div class="bar mini"><i style="width:${pct}%"></i></div>` : ''}
        </div>
      </div>`;
  }).join('');
  $$('.acct', list).forEach((el) => {
    el.onclick = () => selectAccount(el.dataset.phone);
    el.onkeydown = (e) => { if (e.key === 'Enter') selectAccount(el.dataset.phone); };
  });
  const sc = S.scheduler;
  $('#side-foot').innerHTML = `
    <div class="sched" title="点击修改">${I.users}<span>最多同时 <b>${sc.max_parallel}</b> 个账号<br>启动间隔 ${sc.stagger_min}~${sc.stagger_max} 分钟随机</span></div>`;
  $('#side-foot .sched').onclick = () => openSettings('gui');
}

function renderTopActions() {
  const box = $('#top-actions');
  if (!box) return;
  if (S.accounts.length < 2) { box.innerHTML = ''; return; }
  const busy = S.accounts.filter((a) => BUSY.includes(a.status)).length;
  box.innerHTML = `
    <button class="btn" id="btn-start-all">${I.play}全部开始</button>
    ${busy ? `<button class="btn danger" id="btn-stop-all">${I.stop}全部停止</button>` : ''}`;
  $('#btn-start-all').onclick = startAll;
  $('#btn-stop-all') && ($('#btn-stop-all').onclick = stopAll);
}

async function startAll() {
  const sc = S.scheduler;
  const ready = S.accounts.filter((a) => !BUSY.includes(a.status) && a.auth === 'ok' && a.selected_count);
  const noSel = S.accounts.filter((a) => !BUSY.includes(a.status) && a.auth === 'ok' && !a.selected_count);
  const noAuth = S.accounts.filter((a) => a.auth !== 'ok');
  if (!ready.length) return toast('没有可以开始的账号：请先给账号选好课程', 'error');
  const lines = ready.map((a) => `· ${esc(a.name || maskPhone(a.phone))}：${a.selected_count} 门课`).join('<br>');
  const skip = [...noSel.map((a) => `${a.name || maskPhone(a.phone)}（未选课）`), ...noAuth.map((a) => `${a.name || maskPhone(a.phone)}（未登录）`)];
  const go = await confirmBox({
    title: `开始 ${ready.length} 个账号？`,
    message: `${lines}<br><br>最多同时运行 ${sc.max_parallel} 个，每个账号启动间隔 ${sc.stagger_min}~${sc.stagger_max} 分钟随机，其余排队等待。${skip.length ? `<br><br>跳过：${esc(skip.join('、'))}` : ''}`,
    ok: '开始排队',
  });
  if (!go) return;
  try {
    const j = await api('/start_all', {});
    toast(`已加入排队：${j.started.length} 个账号`);
    if (j.skipped.length) setTimeout(() => toast('未能开始：' + j.skipped.join('、'), 'error'), 400);
    applyState(await api('/state'));
    renderSidebar(); renderTopActions(); route(false);
  } catch (e) { toast(e.message, 'error'); }
}

async function stopAll() {
  const go = await confirmBox({ title: '停止所有账号？', message: '正在学习的账号会停止，排队中的账号会取消排队。已完成的进度会保存在学习通。', ok: '全部停止', danger: true });
  if (!go) return;
  try { await api('/stop_all', {}); toast('已全部停止'); } catch (e) { toast(e.message, 'error'); }
}

/* ======================= 账号头部 ======================= */
function acctHeaderHTML(a) {
  return `
    <div class="acct-head">
      <span class="avatar lg">${esc((a.name || '学').slice(-1))}</span>
      <div class="grow"><div class="nm">${esc(a.name || '未知姓名')}</div><div class="hint">${esc(maskPhone(a.phone))}</div></div>
      <button class="btn ghost" data-relogin>重新登录</button>
      <button class="btn ghost icon danger" data-delete title="删除这个账号">${I.trash}</button>
    </div>`;
}

function bindAcctHeader(root, a) {
  $('[data-relogin]', root) && ($('[data-relogin]', root).onclick = () => {
    if (BUSY.includes(a.status)) return toast('请先停止这个账号的学习', 'error');
    S.viewKey = a.phone + ':login';
    showRelogin(a, '');
  });
  $('[data-delete]', root).onclick = async () => {
    if (BUSY.includes(a.status)) return toast('请先停止这个账号的学习', 'error');
    const yes = await confirmBox({ title: `删除账号 ${a.name || maskPhone(a.phone)}？`, message: '会从列表移除，并清除保存的登录状态和密码。学习通里的进度不受影响。', ok: '删除', danger: true });
    if (!yes) return;
    try {
      await acctApi(a.phone, '/delete', {});
      delete S.per[a.phone];
      applyState(await api('/state'));
      if (!S.accounts.length) return renderWelcome();
      renderSidebar(); renderTopActions(); route(true);
    } catch (e) { toast(e.message, 'error'); }
  };
}

function showChecking(a) {
  S.viewToken++;
  $('#main').innerHTML = `<div class="page">${acctHeaderHTML(a)}<div class="splash" style="padding:80px 0"><div class="spinner"></div><p>正在登录 ${esc(a.name || maskPhone(a.phone))}…</p></div></div>`;
  bindAcctHeader($('#main'), a);
}

function showRelogin(a, msg) {
  S.viewToken++;
  const err = msg ?? (a.auth_msg && a.auth_msg !== '需要重新登录' ? a.auth_msg : '');
  $('#main').innerHTML = `
    <div class="page">
      ${acctHeaderHTML(a)}
      <div class="relogin card">
        <h3>${a.auth === 'ok' ? '重新登录' : '登录已失效'}</h3>
        <p class="hint">${a.auth === 'ok' ? '用新密码重新登录这个账号。' : '保存的登录状态过期了，请重新输入密码。'}</p>
        <form class="login-inline">${loginFormHTML({ phone: a.phone, err, lockPhone: true })}</form>
      </div>
    </div>`;
  bindAcctHeader($('#main'), a);
  bindLoginForm($('#main form'), async () => {
    toast('登录成功');
    applyState(await api('/state'));
    renderSidebar();
    route(true);
  });
}

/* ======================= 课程列表 ======================= */
async function showCourses(a, refresh = false) {
  S.view = 'courses';
  const token = ++S.viewToken;
  const P = per(a.phone);
  $('#main').innerHTML = `
    <div class="page">
      ${acctHeaderHTML(a)}
      <div class="page-head">
        <h2>课程</h2><span class="count" id="course-count"></span>
        <div class="spacer" style="flex:1"></div>
        <div class="search">${I.search}<input class="input" id="search" placeholder="搜索课程或老师" value="${esc(P.filter)}"></div>
        <div class="tools">
          <button class="btn" data-sel="unfinished">选择未完成</button>
          <button class="btn" data-sel="all">全选</button>
          <button class="btn" data-sel="none">清空</button>
          <button class="btn icon" id="btn-refresh" title="重新读取课程">${I.refresh}</button>
        </div>
      </div>
      <div id="course-list"></div>
      <div class="actionbar" id="actionbar"></div>
    </div>`;
  bindAcctHeader($('#main'), a);
  $('#search').oninput = (e) => { P.filter = e.target.value; renderCourseList(a); };
  $$('[data-sel]').forEach((b) => (b.onclick = () => {
    const vis = visibleCourses(P);
    if (b.dataset.sel === 'none') vis.forEach((c) => P.selected.delete(c.key));
    else vis.forEach((c) => {
      if (b.dataset.sel === 'all' || !isComplete(c)) P.selected.add(c.key);
      else P.selected.delete(c.key);
    });
    saveSelection(a);
    renderCourseList(a);
  }));
  $('#btn-refresh').onclick = () => loadCourses(a, true, token);
  if (P.loaded && !refresh) renderCourseList(a);
  await loadCourses(a, refresh, token);
}

function isComplete(c) { return c.progress && c.progress.total > 0 && c.progress.done >= c.progress.total; }

function visibleCourses(P) {
  const q = P.filter.trim().toLowerCase();
  if (!q) return P.courses;
  return P.courses.filter((c) => (c.title + ' ' + c.teacher).toLowerCase().includes(q));
}

let selTimer = null;
function saveSelection(a) {
  const P = per(a.phone);
  const keys = [...P.selected].filter((k) => P.courses.some((c) => c.key === k));
  const local = S.accounts.find((x) => x.phone === a.phone);
  if (local) local.selected_count = keys.length;
  renderSidebar();
  clearTimeout(selTimer);
  selTimer = setTimeout(() => acctApi(a.phone, '/selection', { keys }).catch(() => {}), 400);
}

async function loadCourses(a, refresh, token) {
  const P = per(a.phone);
  if (!P.loaded || refresh) {
    $('#course-list').innerHTML = `<div class="course-grid">${'<div class="card course"><div class="shimmer" style="height:18px;width:80%"></div><div class="shimmer" style="height:12px;width:40%"></div><div class="prog"><div class="shimmer" style="height:6px"></div></div></div>'.repeat(4)}</div>`;
    renderActionbar();
  }
  try {
    let j = await acctApi(a.phone, '/courses' + (refresh ? '?refresh=1' : ''));
    if (token !== S.viewToken) return;
    P.courses = j.courses;
    if (!P.loaded) P.selected = new Set(j.selected || []);
    P.loaded = true;
    renderCourseList(a);
    while (j.loading && token === S.viewToken) {
      await sleep(1500);
      if (token !== S.viewToken) return;
      j = await acctApi(a.phone, '/courses');
      if (token !== S.viewToken) return;
      P.courses = j.courses;
      renderCourseList(a);
    }
  } catch (e) {
    if (token !== S.viewToken) return;
    if (e.status === 401) { applyState(await api('/state')); return route(true); }
    $('#course-list').innerHTML = `<div class="empty"><div class="big">课程读取失败</div><div>${esc(e.message)}</div><br><button class="btn" id="retry-courses">重试</button></div>`;
    $('#retry-courses').onclick = () => loadCourses(a, true, token);
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

function renderCourseList(a) {
  const list = $('#course-list');
  if (!list) return;
  const P = per(a.phone);
  const cs = visibleCourses(P);
  $('#course-count').textContent = P.courses.length ? `共 ${P.courses.length} 门` : '';
  if (!P.courses.length) {
    list.innerHTML = '<div class="empty"><div class="big">没有找到课程</div><div>学习通里还没有可学习的课程，或课程尚未开放</div></div>';
  } else if (!cs.length) {
    list.innerHTML = '<div class="empty"><div class="big">没有匹配的课程</div><div>换个关键词试试</div></div>';
  } else {
    list.innerHTML = `<div class="course-grid">${cs.map((c) => `
      <div class="card course ${P.selected.has(c.key) ? 'sel' : ''}" data-key="${esc(c.key)}" tabindex="0">
        <span class="check">${I.check}</span>
        <div class="title" title="${esc(c.title)}">${esc(c.title)}</div>
        <div class="meta">${esc(c.teacher || '未知教师')}${c.desc ? ' · ' + esc(c.desc) : ''}</div>
        <div class="prog">${progressHTML(c.progress)}</div>
      </div>`).join('')}</div>`;
    $$('.course', list).forEach((el) => {
      const toggle = () => {
        const k = el.dataset.key;
        P.selected.has(k) ? P.selected.delete(k) : P.selected.add(k);
        el.classList.toggle('sel', P.selected.has(k));
        saveSelection(a);
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
  const needToken = { TikuYanxi: 'tokens', TikuLike: 'tokens', AI: 'key', SiliconFlow: 'siliconflow_key', TikuAdapter: 'url' }[prov];
  const missing = needToken && !(t[needToken] || '').trim();
  return `
    <span class="badge blue" data-open-settings>${speed}x 倍速</span>
    <span class="badge" data-open-settings>${parseInt(c.jobs) || 4} 个章节同时进行</span>
    <span class="badge ${prov && !missing ? 'green' : 'amber'}" data-open-settings>题库：${prov ? esc(providerName(prov)) + (missing ? '（还没填 Token / Key）' : '') : '未配置（跳过章节检测）'}</span>
    ${prov ? `<span class="badge" data-open-settings>${t.submit === 'true' ? '自动提交答案' : '只保存答案不提交'}</span>` : ''}`;
}

function willQueue() {
  const sc = S.scheduler;
  return sc.active >= sc.max_parallel || sc.queued > 0;
}

function renderActionbar() {
  const bar = $('#actionbar');
  const a = cur();
  if (!bar || !a) return;
  const P = per(a.phone);
  const n = [...P.selected].filter((k) => P.courses.some((c) => c.key === k)).length;
  bar.innerHTML = `
    <div class="info">
      <b>${n ? `已选 ${n} 门课程` : '点击课程卡片选择要学习的课程'}</b>
      <div class="chips">${settingsChips()}</div>
    </div>
    <button class="btn primary lg" id="btn-start" ${n ? '' : 'disabled'}>${willQueue() ? I.clock + '加入排队' : I.play + '开始学习'}</button>`;
  $$('[data-open-settings]', bar).forEach((b) => (b.onclick = () => openSettings()));
  $('#btn-start').onclick = () => startRun(a);
}

async function startRun(a) {
  const P = per(a.phone);
  const chosen = P.courses.filter((c) => P.selected.has(c.key));
  if (!chosen.length) return;
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
  if (chosen.every(isComplete)) {
    const go = await confirmBox({ title: '选中的课程都已完成', message: '这些课程的章节已经全部完成，再跑一遍只会快速检查一遍。', ok: '仍然开始' });
    if (!go) return;
  }
  const btn = $('#btn-start');
  btn.disabled = true;
  try {
    await acctApi(a.phone, '/start', { keys: chosen.map((c) => c.key) });
    P.logs = []; P.logSeq = 0; P.open = new Set();
    applyState(await api('/state'));
    renderSidebar(); renderTopActions(); route(true);
  } catch (e) {
    toast(e.message, 'error');
    btn.disabled = false;
  }
}

/* ======================= 运行页 ======================= */
const CH_LABEL = {
  done: '之前已完成', success: '本次完成', running: '进行中', pending: '等待中',
  waiting: '未开放，等待重试', retry: '出错，重试中', skipped: '未开放，已跳过', failed: '失败',
  manual: '检测需手动完成', redoing: '检测重做中',
};
const MANUAL_CODE = {
  last_chance: '只剩最后 1 次机会', no_redo: '没有重做机会了', rounds_exhausted: '已达最大重做轮数',
  uncertain: '成绩无法确认', retest_failed: '申请重做失败', redo_disabled: '未开启自动重做', no_score: '无法获取成绩',
};

function manualHTML(run) {
  const items = run.manual || [];
  if (!items.length) return '';
  return `<div class="card section manual-sec">
    <h3>需手动完成的章节检测 <span class="badge amber">${items.length}</span>
      <span class="right hint">低于目标分数且无法自动重做，请到学习通手动处理</span></h3>
    <div class="manual-list">${items.map((m) => `
      <div class="manual-item">
        <div class="mi-main">
          <div class="mi-title">${esc(m.course_title)} · ${esc(m.chapter_title || m.name || '章节检测')}</div>
          <div class="hint">${esc(m.reason || '')}</div>
        </div>
        <div class="mi-meta">
          <span class="badge amber">${esc((m.reason || '').startsWith('自动重做后') ? '重做后仍未达标' : (MANUAL_CODE[m.code] || '需手动完成'))}</span>
          <span class="mi-score">${m.score == null ? '—' : `${m.score} 分`}<span class="hint"> / 目标 ${m.target ?? '—'}</span></span>
          ${m.remaining != null ? `<span class="hint">剩余 ${m.remaining} 次</span>` : ''}
        </div>
      </div>`).join('')}</div>
  </div>`;
}

function showRun(a) {
  S.view = 'run';
  const token = ++S.viewToken;
  const P = per(a.phone);
  $('#main').innerHTML = `
    <div class="page">
      ${acctHeaderHTML(a)}
      <div class="card run-head" id="run-head"></div>
      <div id="manual-sec"></div>
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
              <button class="btn ghost" id="reveal-log" title="在文件管理器中显示这个账号的完整日志">日志文件</button>
            </span>
          </h3>
          <div class="log-list" id="log-list"></div>
        </div>
      </div>
    </div>`;
  bindAcctHeader($('#main'), a);
  const seg = $('#log-seg');
  const syncSeg = () => $$('button', seg).forEach((b) => b.classList.toggle('on', b.dataset.f === S.logFilter));
  syncSeg();
  $$('button', seg).forEach((b) => (b.onclick = () => { S.logFilter = b.dataset.f; store.set('logFilter', S.logFilter); syncSeg(); renderLogs(P, true); }));
  $('#reveal-log').onclick = () => api('/reveal', { what: 'worker_log', phone: a.phone }).catch(() => {});
  if (P.run) renderRun(a);
  renderLogs(P, true);
  pollRun(a, token);
}

async function pollRun(a, token) {
  const P = per(a.phone);
  let fails = 0;
  while (token === S.viewToken) {
    try {
      const j = await acctApi(a.phone, '/run?since=' + P.logSeq);
      if (token !== S.viewToken) return;
      fails = 0;
      const run = j.run;
      const newRun = P.run && P.run.started && run.started !== P.run.started && run.status !== 'queued';
      if (run.seq < P.logSeq || newRun) {
        // 后台重启或开始了新的一轮：清空日志后从头拉取。先记下这一轮的状态，否则下次请求会再次判定为新的一轮而反复重拉
        P.run = run;
        P.logs = []; P.logSeq = 0; renderLogs(P, true);
        if (run.seq) continue;
      }
      P.run = run;
      if (run.logs.length) {
        P.logs.push(...run.logs);
        if (P.logs.length > 3000) P.logs.splice(0, P.logs.length - 3000);
        P.logSeq = run.seq;
        appendLogs(run.logs);
      }
      renderRun(a);
      if (run.status === 'idle') { S.viewKey = ''; return route(true); }
    } catch (e) {
      // 连接中断由顶部横幅提示；其他错误连续出现时才弹出
      if (!e.network && ++fails === 3) toast(e.message, 'error');
    }
    await sleep(P.run && BUSY.includes(P.run.status) ? 1000 : 3000);
  }
}

function countChapters(run) {
  const n = { done: 0, success: 0, running: 0, pending: 0, waiting: 0, retry: 0, skipped: 0, failed: 0, total: 0 };
  for (const c of run.courses) for (const ch of c.chapters) {
    // 「需手动完成」「重做中」按原来的状态计数（任务点已完成的仍算已完成）
    const st = ['manual', 'redoing'].includes(ch.status) ? (ch.prev_status || 'pending') : ch.status;
    n[st] = (n[st] || 0) + 1; n.total++;
  }
  return n;
}

function renderRun(a) {
  const P = per(a.phone);
  const run = P.run;
  if (!run || S.view !== 'run') return;
  const n = countChapters(run);
  const finished = n.done + n.success;
  const pct = n.total ? Math.round((finished / n.total) * 100) : 0;
  const active = ACTIVE.includes(run.status);
  const busy = BUSY.includes(run.status);
  const elapsed = (run.ended || run.now) - (run.started || run.now);
  const sel = run.selected?.length ? ' · ' + (run.selected.length > 2 ? `${run.selected.slice(0, 2).join('、')} 等 ${run.selected.length} 门课程` : run.selected.join('、')) : '';

  let queueText = '';
  if (run.status === 'queued') {
    const q = run.queue;
    if (q?.eta) {
      const left = q.eta - run.now;
      queueText = left < 30 ? '马上开始' : `预计 ${fmtClock(q.eta)} 开始（约 ${fmtDuration(left)} 后），错开启动可以避免多个账号同时开始`;
    } else {
      queueText = `排在第 ${q?.position || '?'} 位，正在等其他账号学完腾出位置（最多同时 ${S.scheduler.max_parallel} 个）`;
    }
  }

  const rechecking = run.status === 'running' && (run.phase || '').startsWith('回查');
  const st = {
    queued: ['queued', I.clock, '排队中', queueText],
    starting: ['running', I.play, run.phase || '正在准备…', '马上就好，正在登录并读取章节'],
    running: rechecking
      ? ['running', I.play, '正在回查章节检测', `${run.phase.replace(/^回查章节检测：/, '')} · 低于目标分数的检测会开启思考和联网搜索重做，查完后开始刷课`]
      : ['running', I.play, '正在学习', `已运行 ${fmtDuration(elapsed)} · ${run.speed}x 倍速 · 期间电脑不会自动休眠`],
    counting: ['running', I.play, '正在增加章节学习次数', `已运行 ${fmtDuration(elapsed)}`],
    done: ['done', I.done, '学习完成', `用时 ${fmtDuration(elapsed)}`],
    stopped: ['stopped', I.pause, '已停止', run.started ? `运行了 ${fmtDuration(elapsed)}，已完成的进度会保存在学习通` : '已取消排队'],
    error: ['error', I.alert, '出错了', run.started ? `运行了 ${fmtDuration(elapsed)}` : ''],
  }[run.status] || ['stopped', I.pause, run.phase || '空闲', ''];

  const stopLabel = run.status === 'queued' ? '取消排队' : run.phase === '正在停止…' ? '正在停止…' : '停止';
  $('#run-head').innerHTML = `
    <div class="top">
      <div class="state-icon ${st[0]}">${st[1]}</div>
      <div class="grow">
        <h2>${esc(st[2])}${run.status === 'starting' ? ' <span class="spinner sm" style="display:inline-block;vertical-align:-2px"></span>' : ''}</h2>
        <div class="sub">${esc(st[3])}${esc(sel)}</div>
      </div>
      ${busy
        ? `<button class="btn danger" id="btn-stop" ${run.phase === '正在停止…' ? 'disabled' : ''}>${I.stop}${stopLabel}</button>`
        : `<button class="btn" id="btn-again">${I.refresh}再来一次</button><button class="btn primary" id="btn-back">返回课程列表</button>`}
    </div>
    ${run.status === 'error' ? `<div class="err-box selectable">${esc(run.error)}${/login|登录|密码|cookie/i.test(run.error) ? '<br>可以点右上角「重新登录」后再试。' : ''}</div>` : ''}
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
  $('#btn-stop') && ($('#btn-stop').onclick = () => stopRun(a, run.status === 'queued'));
  $('#btn-back') && ($('#btn-back').onclick = async () => {
    await acctApi(a.phone, '/clear', {}).catch(() => {});
    P.run = null;
    applyState(await api('/state'));
    renderSidebar(); renderTopActions(); S.viewKey = a.phone + ':courses'; showCourses(a, true);
  });
  $('#btn-again') && ($('#btn-again').onclick = async () => {
    await acctApi(a.phone, '/clear', {}).catch(() => {});
    try {
      await acctApi(a.phone, '/start', { keys: run.selected_keys || [] });
      P.logs = []; P.logSeq = 0; P.run = null;
      applyState(await api('/state'));
      renderSidebar(); renderTopActions(); route(true);
    } catch (e) { toast(e.message, 'error'); route(true); }
  });

  const manualBox = $('#manual-sec');
  if (manualBox) manualBox.innerHTML = manualHTML(run);

  const jobs = run.jobs;
  $('#jobs-sec').innerHTML = `
    <h3>正在进行 ${jobs.length ? `<span class="badge blue">${jobs.length}</span>` : ''}</h3>
    ${jobs.length ? jobs.map((j) => jobHTML(j, run.speed)).join('') :
      `<div class="hint">${run.status === 'queued' ? '排队结束后自动开始' : active ? (run.status === 'starting' ? esc(run.phase) : '正在检查章节…') : '没有正在进行的任务'}</div>`}
    ${run.recent.length ? `<h3 style="margin-top:14px">刚刚完成</h3>${run.recent.slice(0, 5).map((j) => `
      <div class="job small"><div class="head">
        <span class="badge ${j.result === 'SUCCESS' ? 'green' : 'red'}">${esc(j.kind)}</span>
        <span class="name" title="${esc(j.name)}">${esc(j.name)}</span>
        <span class="hint">${j.result === 'SUCCESS' ? '完成' : '未成功'}</span>
      </div></div>`).join('')}` : ''}`;

  const sec = $('#courses-sec');
  if (!run.courses.length) {
    sec.innerHTML = `<h3>课程进度</h3><div class="hint">${run.status === 'queued' ? esc(run.selected.join('、')) : '正在读取章节…'}</div>`;
    return;
  }
  if (run.courses.length === 1 && !P.open.size) P.open.add(run.courses[0].key);
  sec.innerHTML = `<h3>课程进度</h3>${run.courses.map((c) => {
    const total = c.chapters.length;
    const fin = c.chapters.filter((ch) => ['done', 'success'].includes(ch.status) || ['done', 'success'].includes(ch.prev_status)).length;
    const p = total ? Math.round((fin / total) * 100) : 100;
    return `
      <div class="course-prog ${P.open.has(c.key) ? 'open' : ''}" data-key="${esc(c.key)}">
        <div class="head">${I.chev}<span class="t" title="${esc(c.title)}">${esc(c.title)}</span>
          <span class="num">${fin}/${total}</span><div class="bar ${fin === total ? 'green' : ''}"><i style="width:${p}%"></i></div></div>
        <div class="chapters">${c.chapters.map((ch) => `
          <div class="chapter ${ch.status}" title="${esc(CH_LABEL[ch.status] || '')}"><span class="dot ${ch.status}"></span><span class="t">${esc(ch.title)}</span>
          ${['running', 'waiting', 'retry', 'skipped', 'failed', 'success'].includes(ch.status) ? `<span class="hint">${esc(CH_LABEL[ch.status])}</span>` : ''}${['manual', 'redoing'].includes(ch.status) ? `<span class="badge ${ch.status === 'manual' ? 'amber' : 'blue'}">${esc(CH_LABEL[ch.status])}</span>` : ''}</div>`).join('')}
        </div>
      </div>`;
  }).join('')}
  <div class="legend">
    <span><i class="dot success"></i>本次完成</span><span><i class="dot done"></i>之前已完成</span>
    <span><i class="dot running"></i>进行中</span><span><i class="dot waiting"></i>未开放/重试中</span>
    <span><i class="dot skipped"></i>已跳过</span><span><i class="dot failed"></i>失败</span>
    <span><i class="dot manual"></i>检测需手动完成</span>
  </div>`;
  $$('.course-prog > .head', sec).forEach((h) => (h.onclick = () => {
    const el = h.parentElement, k = el.dataset.key;
    P.open.has(k) ? P.open.delete(k) : P.open.add(k);
    el.classList.toggle('open');
  }));
}

function jobHTML(j, speed) {
  const where = [j.course_title, j.chapter_title].filter(Boolean).join(' · ');
  let body;
  if (j.unit === '题') {
    const pct = j.total ? Math.min(100, Math.round((j.n / j.total) * 100)) : 0;
    body = j.waiting
      ? '<div class="hint">排队中：等前一个章节检测答完再开始，避免互相拖慢</div>'
      : `<div class="bar"><i style="width:${pct}%"></i></div>
        <div class="time"><span>查题作答 ${j.n} / ${j.total} 题</span><span>${j.n >= j.total ? '正在提交…' : ''}</span></div>`;
  } else if (j.total > 0) {
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

async function stopRun(a, queued) {
  if (!queued) {
    const yes = await confirmBox({ title: '停止学习？', message: '已经完成的章节进度会保存在学习通，正在播放的视频会从当前进度继续，下次可以接着学。', ok: '停止', danger: true });
    if (!yes) return;
  }
  try {
    await acctApi(a.phone, '/stop', {});
    if (queued) {
      per(a.phone).run = null;
      applyState(await api('/state'));
      renderSidebar(); renderTopActions(); route(true);
    }
  } catch (e) { toast(e.message, 'error'); }
}

const isWarn = (l) => ['WARNING', 'ERROR', 'CRITICAL'].includes(l.level);

function logLine(l) {
  const d = document.createElement('div');
  d.className = 'l ' + l.level;
  d.innerHTML = `<span class="ts">${esc(l.ts)}</span><span>${esc(l.msg)}</span>`;
  return d;
}

function renderLogs(P, reset) {
  const box = $('#log-list');
  if (!box) return;
  if (reset) box.innerHTML = '';
  const items = P.logs.filter((l) => S.logFilter === 'all' || isWarn(l)).slice(-800);
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
const val = (sec, key, def = '') => {
  const v = S.settings?.[sec]?.[key];
  return v === undefined || v === '' ? String(def) : v;
};
const F = {
  range: (sec, key, label, { min, max, step, fmt, hint, def }) => `
    <div class="row-item"><div class="lbl"><b>${label}</b>${hint ? `<span class="hint ${hint.warn ? 'warn' : ''}">${hint.text}</span>` : ''}</div>
    <div class="range-wrap"><input type="range" min="${min}" max="${max}" step="${step}" data-sec="${sec}" data-key="${key}" data-fmt="${fmt}" value="${esc(val(sec, key, def))}"><output></output></div></div>`,
  number: (sec, key, label, { min, max, hint, def, step = 1 }) => `
    <div class="row-item"><div class="lbl"><b>${label}</b>${hint ? `<span class="hint">${hint}</span>` : ''}</div>
    <input class="input num-input" type="number" min="${min}" max="${max}" step="${step}" data-sec="${sec}" data-key="${key}" value="${esc(val(sec, key, def))}"></div>`,
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
      + F.text('tiku', 'http_proxy', '代理（可选）', { placeholder: 'http://127.0.0.1:7890' })
      + F.toggle('tiku', 'ai_vision', '识别题目图片', '把题目里的图片一起发给模型（需要模型支持识图，不支持时自动改为纯文字）')
      + F.toggle('tiku', 'ai_disable_thinking', '关闭思考', '适用于 Qwen3 等思考型本地模型，答题更快；在线大模型一般不用开')
      + F.number('tiku', 'ai_timeout', '单题最长等待（秒）', { min: 10, max: 600, def: 120, hint: '超时就跳过这道题，避免一道题卡住整个章节检测' })
      + F.text('tiku', 'ai_search_url', '联网搜索（SearXNG 地址）', { placeholder: 'http://127.0.0.1:8888', hint: `每道题先搜索题干，把搜到的资料交给模型参考，每题多花几秒。需要 ${link('https://docs.searxng.org/', 'SearXNG')} 并开启 JSON 格式；留空则不搜索` })
      + F.text('gui', 'searxng_command', 'SearXNG 启动脚本（可选）', { placeholder: '/path/to/searxng/start.sh', hint: '填写后，搜索服务没开时会自动启动，退出应用时一起关闭' })
      + F.toggle('gui', 'auto_manage_local_model', '自动加载 / 卸载本地模型',
        `API 地址是本机的 ${link('https://lmstudio.ai/', 'LM Studio')} 时生效：开始学习前自动加载模型，所有账号学完或停止后自动卸载，释放内存`),
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
  const running = S.accounts.some((a) => BUSY.includes(a.status));

  $('#sheet-root').innerHTML = `
    <div class="sheet-backdrop"></div>
    <div class="sheet" role="dialog">
      <header><h2>设置</h2><button class="btn ghost icon" id="sheet-close">${I.close}</button></header>
      <div class="body">
        ${running ? '<div class="badge amber" style="padding:6px 10px;border-radius:8px;white-space:normal">有账号正在学习，学习设置会在下次开始时生效；多账号设置立即生效</div>' : ''}
        <div class="group"><h4>学习</h4><div class="card">
          ${F.range('common', 'speed', '视频倍速', { min: 1, max: 2, step: 0.25, fmt: 'x', def: 1, hint: { text: '倍速越高越容易被平台检测到异常，建议 1 ~ 1.5 倍', warn: true } })}
          ${F.number('common', 'jobs', '同时进行的章节数', { min: 1, max: 8, def: 4, hint: '数量越多越快，但请求也更频繁' })}
          ${F.seg('common', 'notopen_action', '遇到未开放的章节', [['retry', '等待重试'], ['continue', '直接跳过']], '需要按顺序解锁的课程选「等待重试」', 'retry')}
          ${F.toggle('common', 'add_learning_count', '学完后刷章节学习次数', '有些课程会考核章节访问次数')}
          <div data-lc>${F.number('common', 'target_count', '目标学习次数', { min: 1, max: 10000, def: 100 })}</div>
        </div></div>

        <div class="group" id="grp-gui"><h4>多账号</h4><div class="card">
          ${F.number('gui', 'max_parallel_accounts', '最多同时运行的账号数', { min: 1, max: 10, def: 2, hint: '超出的账号会排队，前面的学完后自动开始' })}
          <div class="row-item"><div class="lbl"><b>启动间隔（分钟）</b><span class="hint">相邻两个账号开始学习之间，在这个范围内随机等待，避免同时开始</span></div>
            <div class="range-wrap">
              <input class="input num-input" type="number" min="0" max="120" step="0.5" data-sec="gui" data-key="stagger_min_minutes" value="${esc(val('gui', 'stagger_min_minutes', 2))}">
              <span class="hint">到</span>
              <input class="input num-input" type="number" min="0" max="240" step="0.5" data-sec="gui" data-key="stagger_max_minutes" value="${esc(val('gui', 'stagger_max_minutes', 5))}">
            </div></div>
        </div></div>

        <div class="group" id="grp-tiku"><h4>题库（用于章节检测答题）</h4><div class="card">
          ${F.select('tiku', 'provider', '使用的题库', provOptions, '不配置题库时，章节检测会被跳过')}
          ${Object.entries(blocks).map(([id, html]) => `<div data-prov="${id}">${html}</div>`).join('')}
          <div data-prov-any>
            ${F.toggle('tiku', 'submit', '答完自动提交', '关闭时只保存答案，你可以去学习通检查后再手动提交；需要解锁下一章的课程建议开启')}
            ${F.range('tiku', 'cover_rate', '最低题库覆盖率', { min: 0.5, max: 1, step: 0.05, fmt: '%', def: 0.9, hint: { text: '搜到答案的题目比例达到这个值才会自动提交' } })}
            ${F.number('common', 'work_min_score', '章节检测目标分数', { min: 0, max: 100, def: 100, hint: '提交后低于这个分数算不达标' })}
            ${F.toggle('common', 'work_redo_enabled', '不达标时自动重做', '开启 AI 思考，并参考上次的错题和正确答案重新作答；页面显示只剩最后 1 次重做机会时不再自动重做')}
            ${F.number('common', 'work_max_retries', '每个检测最多重做几轮', { min: 1, max: 5, def: 3 })}
            ${F.toggle('common', 'work_recheck_finished', '开始前回查章节检测', '开始刷课前，先查一遍所选课程所有已提交检测的成绩：不达标且还有重做机会的开启思考和联网搜索重做；只剩最后 1 次机会、没有机会、重做后仍未达标或成绩无法确认的列为「需手动完成」。已确认达标的会记住，下次不再重复检查')}
          </div>
        </div></div>

        <div class="group"><h4>完成通知</h4><div class="card">
          ${F.select('notification', 'provider', '推送到手机', [['', '不推送（只弹系统通知）'], ['ServerChan', 'Server 酱（微信）'], ['Qmsg', 'Qmsg 酱（QQ）'], ['Bark', 'Bark（iPhone）'], ['Telegram', 'Telegram']], '学完或出错时推送提醒')}
          <div data-notif>
            ${F.text('notification', 'url', '推送地址', { placeholder: 'https://sctapi.ftqq.com/你的key.send', hint: 'Server 酱、Qmsg 酱、Bark 或 Telegram Bot 的完整推送地址' })}
            <div data-tg>${F.text('notification', 'tg_chat_id', 'Telegram Chat ID')}</div>
          </div>
        </div></div>

        <div class="group"><h4>其他</h4><div class="card">
          <div class="row-item col">
            <div class="lbl"><span class="hint">学习、题库和通知设置保存在项目的 config.ini 中，命令行版也会读取同一份配置。</span></div>
          </div>
          ${F.number('gui', 'log_max_mb', '日志最多占用（MB）', { min: 1, max: 1000, def: 10, hint: '超出时自动删除最旧的日志、裁掉较早的内容，只保留最近的' })}
          ${F.number('gui', 'log_keep_days', '日志保留天数', { min: 1, max: 365, def: 7, hint: '超过这个天数没有更新的日志自动删除' })}
          <div class="row-item col">
            <div class="links">
              <button class="btn" data-reveal="config">显示配置文件</button>
              <button class="btn" data-reveal="logs">显示日志文件夹</button>
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

  $$('input[type=range]', sheet).forEach((r) => {
    const out = r.nextElementSibling;
    const upd = () => { out.textContent = r.dataset.fmt === '%' ? Math.round(r.value * 100) + '%' : r.value + 'x'; };
    r.oninput = upd; upd();
  });
  $$('[data-seg]', sheet).forEach((s) => {
    const sync = () => $$('button', s).forEach((b) => b.classList.toggle('on', b.dataset.v === s.dataset.value));
    $$('button', s).forEach((b) => (b.onclick = () => { s.dataset.value = b.dataset.v; sync(); }));
    sync();
  });
  const provSel = $('select[data-key=provider][data-sec=tiku]', sheet);
  const notifSel = $('select[data-key=provider][data-sec=notification]', sheet);
  const lcBox = $('input[data-key=add_learning_count]', sheet);
  const syncVis = () => {
    $$('[data-prov]', sheet).forEach((el) => (el.style.display = el.dataset.prov === provSel.value ? '' : 'none'));
    $('[data-prov-any]', sheet).style.display = provSel.value ? '' : 'none';
    $('[data-notif]', sheet).style.display = notifSel.value ? '' : 'none';
    $('[data-tg]', sheet).style.display = notifSel.value === 'Telegram' ? '' : 'none';
    $('[data-lc]', sheet).style.display = lcBox.checked ? '' : 'none';
  };
  provSel.onchange = notifSel.onchange = lcBox.onchange = syncVis;
  syncVis();
  $$('[data-reveal]', sheet).forEach((b) => (b.onclick = () => api('/reveal', { what: b.dataset.reveal }).catch(() => {})));
  if (focus) {
    const grp = $('#grp-' + focus);
    grp?.scrollIntoView({ block: 'start' });
    $('select, input', grp)?.focus();
  }

  $('#sheet-save').onclick = async () => {
    const out = { common: {}, tiku: {}, notification: {}, gui: {} };
    $$('[data-key]', sheet).forEach((el) => {
      if (el.closest('[style*="display: none"]')) return; // 隐藏的字段不保存（如两个题库共用 tokens）
      const v = el.matches('[data-seg]') ? el.dataset.value : el.matches('[data-bool]') ? (el.checked ? 'true' : 'false') : el.value.trim();
      out[el.dataset.sec][el.dataset.key] = v;
    });
    const lo = parseFloat(out.gui.stagger_min_minutes), hi = parseFloat(out.gui.stagger_max_minutes);
    if (!(lo >= 0) || !(hi >= 0)) return toast('启动间隔请填写数字', 'error');
    if (lo > hi) [out.gui.stagger_min_minutes, out.gui.stagger_max_minutes] = [out.gui.stagger_max_minutes, out.gui.stagger_min_minutes];
    const speed = parseFloat(out.common.speed);
    if (speed > 1.5) {
      const go = await confirmBox({ title: `确定使用 ${speed} 倍速？`, message: '倍速过高更容易被学习通检测为异常学习，可能被清除进度或记录异常。', ok: '确定' });
      if (!go) return;
    }
    try {
      S.settings = (await api('/settings', out)).settings;
      close();
      toast('设置已保存');
      applyState(await api('/state'));
      renderSidebar();
      renderActionbar();
    } catch (e) { toast(e.message, 'error'); }
  };
}

/* ======================= 快捷键 ======================= */
window.cxOpenSettings = () => { if (S.view !== 'welcome') openSettings(); };
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === ',') { e.preventDefault(); window.cxOpenSettings(); }
  if ((e.metaKey || e.ctrlKey) && e.key === 'r') { e.preventDefault(); const a = cur(); if (S.view === 'courses' && a) showCourses(a, true); }
});

boot();
