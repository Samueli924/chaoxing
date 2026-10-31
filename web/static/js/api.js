const API = {
  async fetchAccounts() {
    const res = await fetch('/api/accounts');
    return res.json();
  },

  async switchAccount(accountId) {
    const res = await fetch('/api/accounts/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    return res.json();
  },

  async setAccountAlias(accountId, alias) {
    const res = await fetch('/api/accounts/alias', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId, alias })
    });
    return res.json();
  },

  async deleteAccount(accountId) {
    const res = await fetch('/api/accounts/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    return res.json();
  },

  async createQrSession() {
    const res = await fetch('/api/auth/qr/create', { method: 'POST' });
    return res.json();
  },

  async pollQrStatus(sessionId) {
    const res = await fetch(`/api/auth/qr/status/${sessionId}`);
    return res.json();
  },

  async loginWithPassword(username, password) {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    return res.json();
  },

  async fetchCourses(refresh = false) {
    const url = refresh ? '/api/courses?refresh=true' : '/api/courses';
    const res = await fetch(url);
    return res.json();
  },

  async fetchCourseProgress(refresh = false) {
    const url = refresh ? '/api/courses/progress?refresh=true' : '/api/courses/progress';
    const res = await fetch(url);
    return res.json();
  },

  async saveCourseList(courseList) {
    const res = await fetch('/api/config/course_list', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ course_list: courseList })
    });
    return res.json();
  },

  async fetchFullConfig() {
    const res = await fetch('/api/config/full');
    return res.json();
  },

  async saveFullConfig(configData) {
    const res = await fetch('/api/config/full', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(configData)
    });
    return res.json();
  },

  async startTask(courseList = null) {
    const payload = courseList !== null ? { course_list: courseList } : {};
    const res = await fetch('/api/task/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    return res.json();
  },

  async stopTask() {
    const res = await fetch('/api/task/stop', { method: 'POST' });
    return res.json();
  },

  async setGlobalSpeed(speed) {
    const res = await fetch('/api/speed/global', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speed })
    });
    return res.json();
  },

  async setWorkerSpeed(workerId, speed) {
    const res = await fetch('/api/speed/worker', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ worker_id: workerId, speed })
    });
    return res.json();
  },

  async fetchStatus() {
    const res = await fetch('/api/status');
    return res.json();
  },

  async fetchPendingQuestions() {
    const res = await fetch('/api/manual/pending');
    return res.json();
  },

  async submitManualAnswer(promptId, answer) {
    const res = await fetch('/api/manual/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt_id: promptId, answer })
    });
    return res.json();
  },

  async skipManualAnswer(promptId) {
    const res = await fetch('/api/manual/skip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt_id: promptId })
    });
    return res.json();
  },

  async fetchLogLevel() {
    const res = await fetch('/api/log/level');
    return res.json();
  },

  async setLogLevel(level) {
    const res = await fetch('/api/log/level', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level })
    });
    return res.json();
  }
};
