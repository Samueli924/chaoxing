let currentFullConfig = {};
let currentPendingPromptId = null;
let currentSelectedAnswers = [];
let qrPollTimer = null;

function pushToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const card = document.createElement('div');
  card.className = `toast-card toast-${type}`;
  card.textContent = message;
  container.appendChild(card);
  setTimeout(() => card.classList.add('show'), 10);
  setTimeout(() => {
    card.classList.remove('show');
    setTimeout(() => card.remove(), 300);
  }, 3500);
}

let isLogPinnedToBottom = true;

function initLogScrollHandler() {
  const consoleEl = document.getElementById('logConsole');
  const scrollBtn = document.getElementById('btnScrollBottom');
  if (!consoleEl) return;

  consoleEl.addEventListener('scroll', () => {
    const distanceFromBottom = consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight;
    if (distanceFromBottom <= 30) {
      isLogPinnedToBottom = true;
      if (scrollBtn) scrollBtn.classList.remove('visible');
    } else {
      isLogPinnedToBottom = false;
      if (distanceFromBottom > 80) {
        if (scrollBtn) scrollBtn.classList.add('visible');
      } else {
        if (scrollBtn) scrollBtn.classList.remove('visible');
      }
    }
  });
}

function scrollToLogBottom() {
  const consoleEl = document.getElementById('logConsole');
  const scrollBtn = document.getElementById('btnScrollBottom');
  if (!consoleEl) return;
  consoleEl.scrollTop = consoleEl.scrollHeight;
  isLogPinnedToBottom = true;
  if (scrollBtn) scrollBtn.classList.remove('visible');
}

function appendLog(timestamp, level, message) {
  const consoleEl = document.getElementById('logConsole');
  if (!consoleEl) return;
  const line = document.createElement('div');
  line.className = 'log-line';
  const timeSpan = document.createElement('span');
  timeSpan.className = 'log-time';
  timeSpan.textContent = `[${timestamp}]`;
  const levelSpan = document.createElement('span');
  levelSpan.className = `log-level-${level.toLowerCase()}`;
  levelSpan.textContent = `[${level}] `;
  const msgSpan = document.createElement('span');
  msgSpan.textContent = message;

  line.appendChild(timeSpan);
  line.appendChild(levelSpan);
  line.appendChild(msgSpan);
  consoleEl.appendChild(line);
  if (consoleEl.children.length > 500) {
    consoleEl.removeChild(consoleEl.firstChild);
  }
  if (isLogPinnedToBottom) {
    consoleEl.scrollTop = consoleEl.scrollHeight;
  }
}

async function loadAccounts() {
  try {
    const data = await API.fetchAccounts();
    const dropdown = document.getElementById('accountDropdownList');
    if (!dropdown) return;
    dropdown.innerHTML = '';

    const accounts = data.accounts || [];
    const activeAcc = accounts.find(a => a.active) || accounts[0];
    const currentNameEl = document.getElementById('currentAccountName');
    if (currentNameEl) {
      currentNameEl.textContent = activeAcc ? (activeAcc.display_name || activeAcc.uid || activeAcc.id) : '未登录账号';
    }

    if (accounts.length === 0) {
      dropdown.innerHTML = '<div style="padding: 0.75rem 1rem; color: var(--text-dim); font-size: 0.8rem;">暂无已保存账号，请添加登录</div>';
      return;
    }

    accounts.forEach(acc => {
      const item = document.createElement('div');
      item.className = `dropdown-item ${acc.active ? 'active' : ''}`;
      item.style.cssText = 'display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;';

      const textWrap = document.createElement('div');
      textWrap.style.cssText = 'flex: 1; min-width: 0; cursor: pointer;';
      const uEl = document.createElement('div');
      uEl.style.fontWeight = '600';
      uEl.style.cssText = 'overflow: hidden; text-overflow: ellipsis; white-space: nowrap;';
      uEl.textContent = acc.display_name || acc.uid || acc.id;
      const fEl = document.createElement('div');
      fEl.style.fontSize = '0.7rem';
      fEl.style.color = 'var(--text-dim)';
      fEl.textContent = acc.alias ? (acc.uid ? `UID: ${acc.uid}` : acc.file) : acc.file;
      textWrap.appendChild(uEl);
      textWrap.appendChild(fEl);

      textWrap.onclick = async () => {
        if (!acc.active) {
          await API.switchAccount(acc.id);
          toggleAccountDropdown(false);
          pushToast(`已切换至账号: ${acc.display_name || acc.uid || acc.id}`);
          await loadAccounts();
          await loadCourses(false);
        } else {
          toggleAccountDropdown(false);
        }
      };
      item.appendChild(textWrap);

      const actionWrap = document.createElement('div');
      actionWrap.style.cssText = 'display: flex; align-items: center; gap: 0.4rem;';

      if (acc.active) {
        const badge = document.createElement('span');
        badge.className = 'badge badge-blue';
        badge.textContent = '当前';
        actionWrap.appendChild(badge);
      }

      const editBtn = document.createElement('button');
      editBtn.className = 'btn-icon';
      editBtn.title = '设置昵称';
      editBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"></path></svg>';
      editBtn.onclick = async (e) => {
        e.stopPropagation();
        const input = prompt('输入账号昵称，留空恢复默认', acc.alias || '');
        if (input === null) return;
        try {
          const res = await API.setAccountAlias(acc.id, input);
          if (res.status === 'success') {
            pushToast('昵称已更新');
            await loadAccounts();
          } else {
            pushToast(res.msg || '昵称更新失败', 'error');
          }
        } catch (err) {
          pushToast('昵称更新异常', 'error');
        }
      };
      actionWrap.appendChild(editBtn);

      const delBtn = document.createElement('button');
      delBtn.className = 'btn-icon-danger';
      delBtn.title = '删除此账号';
      delBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>';
      delBtn.onclick = async (e) => {
        e.stopPropagation();
        const accName = acc.display_name || acc.uid || acc.id;
        if (!confirm(`确认删除本地账号配置 [${accName}] 吗？`)) return;
        try {
          const res = await API.deleteAccount(acc.id);
          if (res.status === 'success') {
            pushToast(`已删除账号 ${accName}`);
            await loadAccounts();
            await loadCourses(false);
          } else {
            pushToast(res.msg || '删除失败', 'error');
          }
        } catch (err) {
          pushToast('删除账号异常', 'error');
        }
      };
      actionWrap.appendChild(delBtn);

      item.appendChild(actionWrap);
      dropdown.appendChild(item);
    });
  } catch (e) {
    console.error('加载账号失败', e);
  }
}

function toggleAccountDropdown(show) {
  const el = document.getElementById('accountDropdown');
  if (!el) return;
  if (typeof show === 'boolean') {
    el.classList.toggle('show', show);
  } else {
    el.classList.toggle('show');
  }
}

function openLoginModal() {
  toggleAccountDropdown(false);
  const modal = document.getElementById('loginModalOverlay');
  if (modal) modal.classList.add('show');
  startQrSession();
}

function closeLoginModal() {
  const modal = document.getElementById('loginModalOverlay');
  if (modal) modal.classList.remove('show');
  if (qrPollTimer) {
    clearInterval(qrPollTimer);
    qrPollTimer = null;
  }
}

function switchLoginTab(tab) {
  // 左右分栏并存模式保留接口兼容
}

async function startQrSession() {
  if (qrPollTimer) clearInterval(qrPollTimer);
  const qrBox = document.getElementById('loginQrBox');
  const imgEl = document.getElementById('loginQrImage');
  const tipEl = document.getElementById('loginQrTip');
  if (qrBox) qrBox.classList.add('loading');
  if (imgEl) imgEl.src = '';
  if (tipEl) tipEl.textContent = '正在拉取二维码...';

  try {
    const res = await API.createQrSession();
    if (res.status && res.session_id) {
      if (imgEl) {
        imgEl.onload = () => {
          if (qrBox) qrBox.classList.remove('loading');
        };
        imgEl.src = res.qr_url;
      }
      if (tipEl) tipEl.textContent = '请打开学习通 APP 扫码登录';
      qrPollTimer = setInterval(async () => {
        const poll = await API.pollQrStatus(res.session_id);
        if (poll.status === 'CONFIRMED' && tipEl) {
          tipEl.textContent = '已扫码，请在手机端点击确认登录';
        } else if (poll.status === 'SUCCESS') {
          clearInterval(qrPollTimer);
          if (qrBox) qrBox.classList.remove('loading');
          pushToast('扫码登录成功');
          closeLoginModal();
          await loadAccounts();
          await loadCourses(false);
        } else if (poll.status === 'EXPIRED') {
          clearInterval(qrPollTimer);
          if (qrBox) qrBox.classList.remove('loading');
          if (tipEl) tipEl.textContent = '二维码已失效，点击重新加载';
        }
      }, 1500);
    } else {
      if (qrBox) qrBox.classList.remove('loading');
      if (tipEl) tipEl.textContent = res.msg || '获取二维码失败，点击刷新';
    }
  } catch (e) {
    if (qrBox) qrBox.classList.remove('loading');
    if (tipEl) tipEl.textContent = '生成二维码失败，请检查网络';
  }
}

async function handlePasswordLogin(e) {
  e.preventDefault();
  const u = document.getElementById('pwdUsername')?.value;
  const p = document.getElementById('pwdPassword')?.value;
  if (!u || !p) return;
  try {
    const res = await API.loginWithPassword(u, p);
    if (res.status === 'success') {
      pushToast('密码登录成功');
      closeLoginModal();
      await loadAccounts();
      await loadCourses(false);
    } else {
      pushToast(`登录失败: ${res.msg || '凭据错误'}`, 'error');
    }
  } catch (err) {
    pushToast('密码登录异常', 'error');
  }
}

async function loadCourses(isManual = false) {
  const tbody = document.getElementById('courseTableBody');
  if (!tbody) return;
  if (isManual) pushToast('正在刷新课程列表...', 'info');
  tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 2rem;">加载中...</td></tr>';
  try {
    const res = await API.fetchCourses(isManual);
    const courses = res.courses || [];
    const selected = new Set(res.selected_ids || []);
    if (courses.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 2rem;">暂无课程或尚未载入会话凭据</td></tr>';
      if (isManual) pushToast('未获取到课程，请检查账号是否已登录', 'warning');
      return;
    }
    tbody.innerHTML = '';
    courses.forEach(c => {
      const isChecked = selected.has(String(c.courseId));
      const tr = document.createElement('tr');

      const tdCb = document.createElement('td');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'course-cb';
      cb.value = c.courseId;
      cb.checked = isChecked;
      cb.onchange = updateSelectedCount;
      tdCb.appendChild(cb);

      tr.dataset.status = c.is_ended ? 'ENDED' : 'ACTIVE';

      const tdTitle = document.createElement('td');
      tdTitle.style.fontWeight = '500';
      const titleSpan = document.createElement('span');
      titleSpan.textContent = c.title || '-';
      tdTitle.appendChild(titleSpan);

      const statusBadge = document.createElement('span');
      statusBadge.className = `badge ${c.is_ended ? 'badge-gray' : 'badge-blue'}`;
      statusBadge.style.marginLeft = '0.5rem';
      statusBadge.style.fontSize = '0.65rem';
      statusBadge.textContent = c.status || (c.is_ended ? '已结课' : '进行中');
      tdTitle.appendChild(statusBadge);

      const tdId = document.createElement('td');
      tdId.style.fontFamily = 'var(--font-mono)';
      tdId.style.color = 'var(--text-muted)';
      tdId.textContent = c.courseId;

      const tdClazz = document.createElement('td');
      tdClazz.textContent = c.clazzId || '-';

      const tdTeacher = document.createElement('td');
      tdTeacher.textContent = c.teacher || '-';

      const tdProg = document.createElement('td');
      const badge = document.createElement('span');
      const progKey = c.clazzId ? `${c.courseId}_${c.clazzId}` : String(c.courseId);
      badge.id = `course_prog_${progKey}`;
      badge.dataset.progKey = progKey;
      badge.dataset.courseId = String(c.courseId);
      const pct = c.progress;
      const text = c.progress_text || (pct !== null && pct !== undefined ? `${pct}%` : '读取中...');
      if (pct !== null && pct !== undefined) {
        badge.className = `badge ${pct >= 100 ? 'badge-green' : (pct > 0 ? 'badge-blue' : 'badge-gray')}`;
      } else {
        badge.className = 'badge badge-gray';
      }
      badge.textContent = text;
      tdProg.appendChild(badge);

      tr.appendChild(tdCb);
      tr.appendChild(tdTitle);
      tr.appendChild(tdId);
      tr.appendChild(tdClazz);
      tr.appendChild(tdTeacher);
      tr.appendChild(tdProg);
      tbody.appendChild(tr);
    });
    updateSelectedCount();
    if (isManual) pushToast(`课程列表已加载，共 ${courses.length} 门课程`);
    loadCoursesProgress(isManual);
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--accent-danger); padding: 2rem;">获取课程失败</td></tr>';
    if (isManual) pushToast('刷新课程列表失败，请查看日志', 'error');
  }
}

async function loadCoursesProgress(force = false) {
  try {
    const res = await API.fetchCourseProgress(force);
    const map = res.progress || {};
    document.querySelectorAll('[data-prog-key]').forEach(el => {
      const data = map[el.dataset.progKey] || map[el.dataset.courseId];
      if (!data) return;
      const pct = data.percent || 0;
      el.className = `badge ${pct >= 100 ? 'badge-green' : (pct > 0 ? 'badge-blue' : 'badge-gray')}`;
      el.textContent = data.text || `${pct}%`;
    });
  } catch (err) {
    console.error('加载课程完成度失败', err);
  }
}

let currentStatusFilter = 'ALL';

function filterCourseStatus(status) {
  currentStatusFilter = status;
  document.getElementById('filterStatusAll')?.classList.toggle('active', status === 'ALL');
  document.getElementById('filterStatusActive')?.classList.toggle('active', status === 'ACTIVE');
  document.getElementById('filterStatusEnded')?.classList.toggle('active', status === 'ENDED');
  applyCourseFilters();
}

function applyCourseFilters() {
  const kw = document.getElementById('courseSearchInput')?.value.toLowerCase() || '';
  document.querySelectorAll('#courseTableBody tr').forEach(tr => {
    const matchesKw = tr.textContent.toLowerCase().includes(kw);
    const trStatus = tr.dataset.status;
    const matchesStatus = (currentStatusFilter === 'ALL') || (trStatus === currentStatusFilter);
    tr.style.display = (matchesKw && matchesStatus) ? '' : 'none';
  });
}

function updateSelectedCount() {
  const cbs = document.querySelectorAll('.course-cb:checked');
  const countEl = document.getElementById('selectedCourseCount');
  if (countEl) countEl.textContent = String(cbs.length);
}

function selectAllCourses(checked) {
  document.querySelectorAll('#courseTableBody tr').forEach(tr => {
    if (tr.style.display === 'none') return;
    const cb = tr.querySelector('.course-cb');
    if (cb) cb.checked = checked;
  });
  updateSelectedCount();
}

async function saveSelectedCourses() {
  const cbs = document.querySelectorAll('.course-cb:checked');
  const ids = Array.from(cbs).map(cb => cb.value);
  try {
    await API.saveCourseList(ids);
    pushToast(`已保存 ${ids.length} 门课程至当前账号配置`);
  } catch (e) {
    pushToast('保存课程失败', 'error');
  }
}

async function startStudyTask() {
  const cbs = document.querySelectorAll('.course-cb:checked');
  const checkedIds = Array.from(cbs).map(cb => cb.value);
  try {
    const res = await API.startTask(checkedIds);
    if (res.status === 'success') {
      if (checkedIds.length === 0) {
        pushToast('未单独勾选，默认全选进行中课程并启动任务');
      } else {
        pushToast(`已启动勾选的 ${checkedIds.length} 门课程任务`);
      }
      const btnStart = document.getElementById('btnTaskStart');
      const btnStop = document.getElementById('btnTaskStop');
      if (btnStart) btnStart.style.display = 'none';
      if (btnStop) btnStop.style.display = 'inline-flex';
    } else {
      pushToast(`启动失败: ${res.msg || '未知原因'}`, 'error');
    }
  } catch (e) {
    pushToast('发起任务请求异常', 'error');
  }
}

async function stopStudyTask() {
  try {
    await API.stopTask();
    pushToast('已发送停止任务信号');
    const btnStart = document.getElementById('btnTaskStart');
    const btnStop = document.getElementById('btnTaskStop');
    if (btnStart) btnStart.style.display = 'inline-flex';
    if (btnStop) btnStop.style.display = 'none';
  } catch (e) {
    pushToast('停止任务请求异常', 'error');
  }
}

async function openSettingsModal() {
  const modal = document.getElementById('settingsModalOverlay');
  if (!modal) return;
  modal.classList.add('show');
  switchSettingsTab('common');
  try {
    currentFullConfig = await API.fetchFullConfig();
    populateSettingsForm(currentFullConfig);
  } catch (e) {
    pushToast('读取配置失败', 'error');
  }
}

function closeSettingsModal() {
  const modal = document.getElementById('settingsModalOverlay');
  if (modal) modal.classList.remove('show');
}

function switchSettingsTab(tabName) {
  document.querySelectorAll('.settings-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.settings-tab-pane').forEach(pane => {
    pane.style.display = (pane.dataset.pane === tabName) ? 'block' : 'none';
  });
}

function onTikuProviderChange(provider) {
  const allPanes = ['AI', 'SiliconFlow', 'TikuYanxi', 'TikuLike', 'TikuAdapter', 'TikuGo', 'TikuManual', 'custom'];
  allPanes.forEach(p => {
    const el = document.getElementById(`tiku_pane_${p}`);
    if (el) el.style.display = (p === provider) ? 'block' : 'none';
  });
}

function populateSettingsForm(cfg) {
  const common = cfg.common || {};
  const tiku = cfg.tiku || {};
  const notif = cfg.notification || {};

  setVal('cfg_jobs', common.jobs ?? 4);
  setVal('cfg_notopen_action', common.notopen_action ?? 'retry');
  setVal('cfg_retry_interval', common.retry_interval ?? 1.0);
  setCheck('cfg_work_redo_enabled', !!common.work_redo_enabled);
  setVal('cfg_work_max_retries', common.work_max_retries ?? 3);
  setCheck('cfg_add_learning_count', !!common.add_learning_count);
  setVal('cfg_target_count', common.target_count ?? 100);
  setVal('cfg_daily_watch_limit_minutes', common.daily_watch_limit_minutes ?? 0);
  setCheck('cfg_topic_auto_reply', common.topic_auto_reply !== undefined ? !!common.topic_auto_reply : true);
  setVal('cfg_topic_reply_content', common.topic_reply_content ?? '');

  const knownProviders = ['AI', 'SiliconFlow', 'TikuYanxi', 'TikuLike', 'TikuAdapter', 'TikuGo', 'TikuManual'];
  const rawProvider = tiku.provider || 'TikuYanxi';
  if (knownProviders.includes(rawProvider)) {
    setVal('cfg_provider_select', rawProvider);
    onTikuProviderChange(rawProvider);
  } else {
    setVal('cfg_provider_select', 'custom');
    setVal('cfg_custom_provider_input', rawProvider);
    onTikuProviderChange('custom');
  }

  setCheck('cfg_submit', !!tiku.submit);
  setVal('cfg_cover_rate', tiku.cover_rate ?? 0.9);
  setVal('cfg_delay', tiku.delay ?? 1.0);
  setCheck('cfg_check_llm', !!tiku.check_llm_connection);
  setCheck('cfg_check_llm_sf', !!tiku.check_llm_connection);

  setVal('cfg_tokens_yanxi', tiku.tokens ?? '');
  setVal('cfg_tokens_like', tiku.tokens ?? '');
  setCheck('cfg_like_search', !!tiku.likeapi_search);
  setCheck('cfg_like_vision', !!tiku.likeapi_vision);
  setVal('cfg_like_model', tiku.likeapi_model ?? 'glm-4.5-air');
  setVal('cfg_tiku_url', tiku.url ?? '');
  setVal('cfg_go_auth', tiku.go_authorization ?? '');
  setVal('cfg_go_interval', tiku.go_min_interval ?? 1.0);

  setVal('cfg_ai_endpoint', tiku.endpoint ?? '');
  setVal('cfg_ai_key', tiku.key ?? '');
  setVal('cfg_ai_model', tiku.model ?? '');
  setVal('cfg_sf_key', tiku.siliconflow_key ?? '');
  setVal('cfg_sf_model', tiku.siliconflow_model ?? 'deepseek-ai/DeepSeek-R1');

  setVal('cfg_manual_mode', tiku.manual_mode_default ?? 'batch');
  setVal('cfg_manual_sep', tiku.manual_mode_separator ?? ';');
  setVal('cfg_true_list', tiku.true_list ?? '正确,对,√,是');
  setVal('cfg_false_list', tiku.false_list ?? '错误,错,×,否,不对,不正确');

  setVal('cfg_notif_provider', notif.provider ?? 'ServerChan');
  setVal('cfg_notif_url', notif.url ?? '');
  setVal('cfg_notif_tg_id', notif.tg_chat_id ?? '');
}

function readSettingsForm() {
  const provSelect = getVal('cfg_provider_select');
  const provider = (provSelect === 'custom') ? (getVal('cfg_custom_provider_input') || 'TikuYanxi') : provSelect;

  let activeTokens = '';
  if (provSelect === 'TikuLike') {
    activeTokens = getVal('cfg_tokens_like');
  } else if (provSelect === 'TikuYanxi') {
    activeTokens = getVal('cfg_tokens_yanxi');
  } else {
    activeTokens = getVal('cfg_tokens_yanxi') || getVal('cfg_tokens_like');
  }

  const checkLlm = (provSelect === 'SiliconFlow') ? getCheck('cfg_check_llm_sf') : getCheck('cfg_check_llm');

  return {
    common: {
      ...(currentFullConfig.common || {}),
      jobs: parseInt(getVal('cfg_jobs'), 10) || 4,
      notopen_action: getVal('cfg_notopen_action'),
      retry_interval: parseFloat(getVal('cfg_retry_interval')) || 1.0,
      work_redo_enabled: getCheck('cfg_work_redo_enabled'),
      work_max_retries: parseInt(getVal('cfg_work_max_retries'), 10) || 3,
      add_learning_count: getCheck('cfg_add_learning_count'),
      target_count: parseInt(getVal('cfg_target_count'), 10) || 100,
      daily_watch_limit_minutes: parseInt(getVal('cfg_daily_watch_limit_minutes'), 10) || 0,
      topic_auto_reply: getCheck('cfg_topic_auto_reply'),
      topic_reply_content: getVal('cfg_topic_reply_content')
    },
    tiku: {
      ...(currentFullConfig.tiku || {}),
      provider: provider,
      submit: getCheck('cfg_submit'),
      cover_rate: parseFloat(getVal('cfg_cover_rate')) || 0.9,
      delay: parseFloat(getVal('cfg_delay')) || 1.0,
      check_llm_connection: checkLlm,
      tokens: activeTokens,
      likeapi_search: getCheck('cfg_like_search'),
      likeapi_vision: getCheck('cfg_like_vision'),
      likeapi_model: getVal('cfg_like_model'),
      url: getVal('cfg_tiku_url'),
      go_authorization: getVal('cfg_go_auth'),
      go_min_interval: parseFloat(getVal('cfg_go_interval')) || 1.0,
      endpoint: getVal('cfg_ai_endpoint'),
      key: getVal('cfg_ai_key'),
      model: getVal('cfg_ai_model'),
      siliconflow_key: getVal('cfg_sf_key'),
      siliconflow_model: getVal('cfg_sf_model'),
      manual_mode_default: getVal('cfg_manual_mode'),
      manual_mode_separator: getVal('cfg_manual_sep'),
      true_list: getVal('cfg_true_list'),
      false_list: getVal('cfg_false_list')
    },
    notification: {
      ...(currentFullConfig.notification || {}),
      provider: getVal('cfg_notif_provider'),
      url: getVal('cfg_notif_url'),
      tg_chat_id: getVal('cfg_notif_tg_id')
    }
  };
}

async function saveSettings() {
  const data = readSettingsForm();
  try {
    await API.saveFullConfig(data);
    pushToast('配置已成功保存并生效');
    closeSettingsModal();
  } catch (e) {
    pushToast('保存配置异常', 'error');
  }
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}
function getVal(id) {
  const el = document.getElementById(id);
  return el ? el.value : '';
}
function setCheck(id, val) {
  const el = document.getElementById(id);
  if (el) el.checked = val;
}
function getCheck(id) {
  const el = document.getElementById(id);
  return el ? el.checked : false;
}

function handleManualQuestion(data) {
  if (currentPendingPromptId && currentPendingPromptId !== data.prompt_id) return;
  currentPendingPromptId = data.prompt_id;
  currentSelectedAnswers = [];
  const modal = document.getElementById('manualQuizModalOverlay');
  if (!modal) return;

  const titleEl = document.getElementById('quizQuestionTitle');
  const typeEl = document.getElementById('quizTypeBadge');
  const optionsEl = document.getElementById('quizOptionsContainer');
  const textInputEl = document.getElementById('quizTextInputWrap');
  const answerInput = document.getElementById('quizAnswerInput');

  if (titleEl) titleEl.textContent = data.title || '题目';
  if (typeEl) typeEl.textContent = data.type_display || data.type || '单选题';
  if (optionsEl) optionsEl.innerHTML = '';
  if (answerInput) answerInput.value = '';

  const qType = data.type || 'single';
  const options = data.options || [];

  if (qType === 'judgement') {
    if (textInputEl) textInputEl.style.display = 'none';
    ['正确', '错误'].forEach(opt => {
      const card = document.createElement('div');
      card.className = 'quiz-option-card';
      card.textContent = opt;
      card.onclick = () => {
        document.querySelectorAll('.quiz-option-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        currentSelectedAnswers = [opt];
      };
      optionsEl.appendChild(card);
    });
  } else if (options.length > 0) {
    if (textInputEl) textInputEl.style.display = 'none';
    options.forEach(opt => {
      const card = document.createElement('div');
      card.className = 'quiz-option-card';
      card.textContent = opt;
      const match = opt.trim().match(/^[A-Za-z]/);
      const letter = match ? match[0].toUpperCase() : opt.trim();
      card.onclick = () => {
        if (qType === 'multiple') {
          card.classList.toggle('selected');
          if (card.classList.contains('selected')) {
            currentSelectedAnswers.push(letter);
          } else {
            currentSelectedAnswers = currentSelectedAnswers.filter(x => x !== letter);
          }
        } else {
          document.querySelectorAll('.quiz-option-card').forEach(c => c.classList.remove('selected'));
          card.classList.add('selected');
          currentSelectedAnswers = [letter];
        }
      };
      optionsEl.appendChild(card);
    });
  } else {
    if (textInputEl) textInputEl.style.display = 'block';
  }

  modal.classList.add('show');
}

async function submitCurrentQuizAnswer() {
  if (!currentPendingPromptId) return;
  let ans = '';
  const textInput = document.getElementById('quizAnswerInput');
  if (textInput && textInput.parentElement && textInput.parentElement.style.display !== 'none') {
    ans = textInput.value.trim();
  } else {
    ans = currentSelectedAnswers.join('');
  }

  try {
    await API.submitManualAnswer(currentPendingPromptId, ans);
    closeManualQuizModal();
    pushToast(`已提交答案: ${ans || '[空]'}`);
  } catch (e) {
    pushToast('提交作答失败', 'error');
  }
}

async function skipCurrentQuiz() {
  if (!currentPendingPromptId) return;
  try {
    await API.skipManualAnswer(currentPendingPromptId);
    closeManualQuizModal();
    pushToast('已跳过此题');
  } catch (e) {
    pushToast('跳过操作失败', 'error');
  }
}

function closeManualQuizModal() {
  const modal = document.getElementById('manualQuizModalOverlay');
  if (modal) modal.classList.remove('show');
  currentPendingPromptId = null;
  currentSelectedAnswers = [];
}

function initSSE() {
  const evtSource = new EventSource('/api/events');

  evtSource.addEventListener('STATUS_UPDATE', e => {
    try {
      const data = JSON.parse(e.data);
      updateDashboardStats(data);
    } catch (err) {}
  });

  evtSource.addEventListener('LOG_APPEND', e => {
    try {
      const data = JSON.parse(e.data);
      appendLog(data.timestamp, data.level, data.message);
    } catch (err) {}
  });

  evtSource.addEventListener('WORKER_UPDATE', e => {
    try {
      const w = JSON.parse(e.data);
      if (w.status !== 'PLAYING' && w.type !== 'video') return;
      createOrUpdateWorkerCard(w);
    } catch (err) {}
  });

  evtSource.addEventListener('WORKER_REMOVED', e => {
    try {
      const data = JSON.parse(e.data);
      const card = document.getElementById(`worker_card_${data.id}`);
      if (card) card.remove();
      const wContainer = document.getElementById('workersContainer');
      if (wContainer && wContainer.children.length === 0) {
        wContainer.innerHTML = '<div style="text-align: center; color: var(--text-dim); padding: 1rem;">暂无正在播放的视频</div>';
      }
    } catch (err) {}
  });

  evtSource.addEventListener('SPEED_CHANGE', e => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'GLOBAL' && data.speed !== undefined) {
        const sp = parseFloat(data.speed);
        const speedSlider = document.getElementById('globalSpeedSlider');
        const speedValEl = document.getElementById('globalSpeedVal');
        if (speedSlider && document.activeElement !== speedSlider) speedSlider.value = sp;
        if (speedValEl) speedValEl.textContent = `${sp.toFixed(1)}x`;
      } else if (data.type === 'WORKER' && data.worker_id && data.speed !== undefined) {
        const sp = parseFloat(data.speed);
        const wSlider = document.getElementById(`worker_slider_${data.worker_id}`);
        const wVal = document.getElementById(`worker_speed_val_${data.worker_id}`);
        if (wSlider && document.activeElement !== wSlider) wSlider.value = sp.toFixed(1);
        if (wVal) wVal.textContent = `${sp.toFixed(1)}x`;
      }
    } catch (err) {}
  });

  evtSource.addEventListener('MANUAL_QUESTION_REQUEST', e => {
    try {
      const data = JSON.parse(e.data);
      handleManualQuestion(data);
    } catch (err) {}
  });

  evtSource.addEventListener('MANUAL_QUESTION_RESOLVED', e => {
    try {
      const data = JSON.parse(e.data);
      if (data.prompt_id && currentPendingPromptId && data.prompt_id !== currentPendingPromptId) return;
    } catch (err) {}
    closeManualQuizModal();
    API.fetchPendingQuestions().then(res => {
      const list = res && res.questions;
      if (Array.isArray(list) && list.length > 0) {
        handleManualQuestion(list[0]);
      }
    }).catch(() => {});
  });

  evtSource.addEventListener('TASK_FINISHED', e => {
    const btnStart = document.getElementById('btnTaskStart');
    const btnStop = document.getElementById('btnTaskStop');
    if (btnStart) btnStart.style.display = 'inline-flex';
    if (btnStop) btnStop.style.display = 'none';
    let status = 'finished';
    try {
      const payload = JSON.parse(e.data);
      status = payload.status || 'finished';
    } catch (err) {}
    if (status !== 'stopped') {
      pushToast('所有课程学习任务已完成');
    }
    loadCoursesProgress(true);
  });
}

function createOrUpdateWorkerCard(w) {
  const wContainer = document.getElementById('workersContainer');
  if (!wContainer) return;
  if (wContainer.textContent.includes('暂无正在播放的视频') || wContainer.textContent.includes('暂无活动工作线程')) {
    wContainer.innerHTML = '';
  }
  let card = document.getElementById(`worker_card_${w.id}`);
  const pct = w.duration > 0 ? Math.min(100, Math.round((w.position / w.duration) * 100)) : 0;
  const currentSpeed = parseFloat(w.speed || 1.0);

  if (!card) {
    card = document.createElement('div');
    card.id = `worker_card_${w.id}`;
    card.className = 'worker-card';

    const header = document.createElement('div');
    header.className = 'worker-header';

    const title = document.createElement('div');
    title.className = 'worker-title';
    title.id = `worker_title_${w.id}`;

    const speedWrap = document.createElement('div');
    speedWrap.style.cssText = 'display: flex; align-items: center; gap: 0.35rem;';

    const spLabel = document.createElement('span');
    spLabel.style.cssText = 'font-size: 0.7rem; color: var(--text-dim);';
    spLabel.textContent = '倍速:';

    const slider = document.createElement('input');
    slider.type = 'range';
    slider.min = '1.0';
    slider.max = '2.0';
    slider.step = '0.1';
    slider.id = `worker_slider_${w.id}`;
    slider.style.cssText = 'width: 60px; height: 3px; accent-color: var(--accent-primary); cursor: pointer;';

    const speedVal = document.createElement('span');
    speedVal.id = `worker_speed_val_${w.id}`;
    speedVal.style.cssText = 'font-size: 0.72rem; font-family: var(--font-mono); color: var(--accent-primary); width: 28px; text-align: right;';

    slider.addEventListener('input', e => {
      const v = parseFloat(e.target.value);
      speedVal.textContent = `${v.toFixed(1)}x`;
    });
    slider.addEventListener('change', async e => {
      const newSp = parseFloat(e.target.value);
      speedVal.textContent = `${newSp.toFixed(1)}x`;
      await API.setWorkerSpeed(w.id, newSp);
      pushToast(`${w.id} 视频倍速已设为 ${newSp.toFixed(1)}x`);
    });

    speedWrap.appendChild(spLabel);
    speedWrap.appendChild(slider);
    speedWrap.appendChild(speedVal);
    header.appendChild(title);
    header.appendChild(speedWrap);

    const pbWrap = document.createElement('div');
    pbWrap.className = 'progress-bar-wrap';
    const pbFill = document.createElement('div');
    pbFill.className = 'progress-fill';
    pbFill.id = `worker_fill_${w.id}`;
    pbWrap.appendChild(pbFill);

    const footer = document.createElement('div');
    footer.style.cssText = 'font-size: 0.7rem; color: var(--text-dim); display: flex; justify-content: space-between;';
    const timeSpan = document.createElement('span');
    timeSpan.id = `worker_time_${w.id}`;
    const pctSpan = document.createElement('span');
    pctSpan.id = `worker_pct_${w.id}`;
    footer.appendChild(timeSpan);
    footer.appendChild(pctSpan);

    card.appendChild(header);
    card.appendChild(pbWrap);
    card.appendChild(footer);
    wContainer.appendChild(card);
  }

  const titleEl = document.getElementById(`worker_title_${w.id}`);
  if (titleEl) {
    titleEl.title = w.chapter || '视频播放中';
    titleEl.textContent = `${w.id}: ${w.chapter || '视频播放中'}`;
  }

  const sliderEl = document.getElementById(`worker_slider_${w.id}`);
  const speedValEl = document.getElementById(`worker_speed_val_${w.id}`);
  if (sliderEl && document.activeElement !== sliderEl) {
    sliderEl.value = currentSpeed.toFixed(1);
    if (speedValEl) speedValEl.textContent = `${currentSpeed.toFixed(1)}x`;
  }

  const fillEl = document.getElementById(`worker_fill_${w.id}`);
  if (fillEl) fillEl.style.width = `${pct}%`;

  const unit = w.unit || 's';
  const timeEl = document.getElementById(`worker_time_${w.id}`);
  if (timeEl) timeEl.textContent = `${w.position || 0}${unit} / ${w.duration || 0}${unit}`;

  const pctEl = document.getElementById(`worker_pct_${w.id}`);
  if (pctEl) pctEl.textContent = `${pct}%`;
}

function updateDashboardStats(data) {
  const pEl = document.getElementById('statProgress');
  const tEl = document.getElementById('statTasks');
  const qEl = document.getElementById('statQuiz');
  const wContainer = document.getElementById('workersContainer');
  const speedSlider = document.getElementById('globalSpeedSlider');
  const speedValEl = document.getElementById('globalSpeedVal');
  const btnStart = document.getElementById('btnTaskStart');
  const btnStop = document.getElementById('btnTaskStop');

  if (data.is_running !== undefined) {
    if (data.is_running) {
      if (btnStart) btnStart.style.display = 'none';
      if (btnStop) btnStop.style.display = 'inline-flex';
    } else {
      if (btnStart) btnStart.style.display = 'inline-flex';
      if (btnStop) btnStop.style.display = 'none';
    }
  }

  if (pEl) pEl.textContent = `${data.overall_progress || 0}%`;
  if (tEl) tEl.textContent = `${data.completed_jobs || 0} / ${data.total_jobs || 0}`;
  if (qEl) qEl.textContent = `${data.passed_tests || 0}`;

  if (data.global_speed !== undefined) {
    const sp = parseFloat(data.global_speed);
    if (speedSlider && document.activeElement !== speedSlider) {
      speedSlider.value = sp;
    }
    if (speedValEl) {
      speedValEl.textContent = `${sp.toFixed(1)}x`;
    }
  }

  if (wContainer) {
    const activeVideos = (data.workers || []).filter(w => w.status === 'PLAYING' || w.type === 'video');
    if (activeVideos.length === 0) {
      wContainer.innerHTML = '<div style="text-align: center; color: var(--text-dim); padding: 1rem;">暂无正在播放的视频</div>';
    } else {
      const activeIds = new Set(activeVideos.map(w => `worker_card_${w.id}`));
      Array.from(wContainer.querySelectorAll('.worker-card')).forEach(el => {
        if (!activeIds.has(el.id)) el.remove();
      });
      activeVideos.forEach(w => createOrUpdateWorkerCard(w));
    }
  }

  const consoleEl = document.getElementById('logConsole');
  if (consoleEl && consoleEl.children.length === 0 && Array.isArray(data.logs)) {
    data.logs.forEach(item => appendLog(item.timestamp, item.level, item.message));
  }
}

async function changeLogLevel(lvl) {
  try {
    const res = await API.setLogLevel(lvl);
    if (res.status === 'success') {
      pushToast(`控制台日志级别已切换为 ${res.level}`);
    } else {
      pushToast('切换日志级别失败', 'error');
    }
  } catch (e) {
    pushToast('更新日志级别异常', 'error');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initSSE();
  initLogScrollHandler();
  API.fetchLogLevel().then(res => {
    if (res && res.level) {
      const el = document.getElementById('logLevelSelector');
      if (el) el.value = res.level;
    }
  }).catch(() => {});

  loadAccounts().then(() => {
    loadCourses(false);
  });

  API.fetchPendingQuestions().then(res => {
    const list = res && res.questions;
    if (Array.isArray(list) && list.length > 0) {
      handleManualQuestion(list[0]);
    }
  }).catch(() => {});

  document.addEventListener('click', e => {
    if (!e.target.closest('.account-bar')) {
      toggleAccountDropdown(false);
    }
  });

  const searchInput = document.getElementById('courseSearchInput');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      applyCourseFilters();
    });
  }

  const quizInput = document.getElementById('quizAnswerInput');
  if (quizInput) {
    quizInput.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) {
        e.preventDefault();
        submitCurrentQuizAnswer();
      }
    });
  }

  const speedSlider = document.getElementById('globalSpeedSlider');
  const speedValEl = document.getElementById('globalSpeedVal');
  if (speedSlider) {
    speedSlider.addEventListener('input', e => {
      const sp = parseFloat(e.target.value);
      if (speedValEl) speedValEl.textContent = `${sp.toFixed(1)}x`;
    });
    speedSlider.addEventListener('change', async e => {
      const sp = parseFloat(e.target.value);
      if (speedValEl) speedValEl.textContent = `${sp.toFixed(1)}x`;
      await API.setGlobalSpeed(sp);
      pushToast(`全局倍速已更新为 ${sp.toFixed(1)}x`);
    });
  }
});
