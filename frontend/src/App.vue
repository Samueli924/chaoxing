<template>
  <el-container class="layout-container">
    <el-aside width="200px" class="aside">
      <div class="logo">
        <h3>超星桌面版</h3>
      </div>
      <el-menu default-active="1" @select="handleSelect" background-color="#304156" text-color="#bfcbd9" active-text-color="#409EFF">
        <el-menu-item index="1">
          <el-icon><Setting /></el-icon>
          <span>账号与配置</span>
        </el-menu-item>
        <el-menu-item index="2">
          <el-icon><Reading /></el-icon>
          <span>课程列表</span>
        </el-menu-item>
        <el-menu-item index="3">
          <el-icon><Monitor /></el-icon>
          <span>运行控制面板</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-main>
        <!-- 账号设置视图 -->
        <div v-show="activeIndex === '1'">
          <el-card shadow="never">
            <template #header>
              <div class="card-header"><span>超星挂机配置中心</span></div>
            </template>
            <el-tabs v-model="activeConfigTab">
              <!-- 通用配置 -->
              <el-tab-pane label="基础设置" name="common">
                <el-form :model="config.common" label-width="150px" style="max-width: 600px;">
                  <el-form-item label="登录账号">
                    <el-input v-model="config.common.username" placeholder="请输入手机号/账号"></el-input>
                  </el-form-item>
                  <el-form-item label="登录密码">
                    <el-input v-model="config.common.password" type="password" show-password placeholder="请输入密码"></el-input>
                  </el-form-item>
                  <el-form-item label="播放倍速">
                    <el-slider v-model="config.common.speed" :min="1" :max="2" :step="0.1" show-input></el-slider>
                  </el-form-item>
                  <el-form-item label="并行任务数">
                    <el-input-number v-model="config.common.jobs" :min="1" :max="10"></el-input-number>
                  </el-form-item>
                  <el-form-item label="未开放章节行为">
                    <el-radio-group v-model="config.common.notopen_action">
                      <el-radio value="retry">重试</el-radio>
                      <el-radio value="continue">跳过(继续)</el-radio>
                    </el-radio-group>
                  </el-form-item>
                  <el-form-item label="自动增加学习次数">
                    <el-switch v-model="config.common.add_learning_count" />
                  </el-form-item>
                </el-form>
              </el-tab-pane>

              <!-- 题库配置 -->
              <el-tab-pane label="题库/AI设置" name="tiku">
                <el-form :model="config.tiku" label-width="150px" style="max-width: 600px;">
                  <el-form-item label="题库引擎提供商">
                    <el-select v-model="config.tiku.provider" placeholder="请选择引擎" style="width: 100%">
                      <el-option label="TikuYanxi (言溪)" value="TikuYanxi" />
                      <el-option label="TikuLike (LIKE)" value="TikuLike" />
                      <el-option label="SiliconFlow (硅基流动)" value="SiliconFlow" />
                      <el-option label="AI (自定义大模型)" value="AI" />
                      <el-option label="TikuGo" value="TikuGo" />
                      <el-option label="TikuManual (手动打字)" value="TikuManual" />
                    </el-select>
                  </el-form-item>
                  
                  <el-form-item label="自动提交答卷">
                    <el-switch v-model="config.tiku.submit" />
                  </el-form-item>
                  <el-form-item label="最低题库覆盖率" v-if="config.tiku.submit">
                    <el-slider v-model="config.tiku.cover_rate" :min="0" :max="1" :step="0.05" show-input></el-slider>
                  </el-form-item>

                  <el-form-item label="API Token" v-if="['TikuYanxi', 'TikuLike'].includes(config.tiku.provider)">
                    <el-input v-model="config.tiku.tokens" placeholder="言溪或LIKE的Token"></el-input>
                  </el-form-item>

                  <template v-if="config.tiku.provider === 'SiliconFlow' || config.tiku.provider === 'AI'">
                    <el-form-item label="大模型 API Key">
                      <el-input v-model="config.tiku.key" placeholder="例如 sk-..."></el-input>
                    </el-form-item>
                    <el-form-item label="大模型 Endpoint">
                      <el-input v-model="config.tiku.endpoint" placeholder="例如 https://api.siliconflow.cn/v1/chat/completions"></el-input>
                    </el-form-item>
                    <el-form-item label="大模型名称">
                      <el-input v-model="config.tiku.model" placeholder="例如 deepseek-ai/DeepSeek-V3"></el-input>
                    </el-form-item>
                  </template>
                  
                  <el-form-item>
                    <el-button type="info" @click="testApi" :loading="testingApi">测试题库/API连接</el-button>
                  </el-form-item>
                </el-form>
              </el-tab-pane>

              <!-- 通知配置 -->
              <el-tab-pane label="通知推送(微信/等)" name="notification">
                <el-form :model="config.notification" label-width="150px" style="max-width: 600px;">
                  <el-form-item label="推送提供商">
                    <el-select v-model="config.notification.provider" placeholder="请选择" style="width: 100%">
                      <el-option label="不推送" value="" />
                      <el-option label="ServerChan (Server酱)" value="ServerChan" />
                      <el-option label="Bark (iOS)" value="Bark" />
                      <el-option label="Qmsg (QQ群)" value="Qmsg" />
                      <el-option label="Telegram" value="Telegram" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="推送链接(URL)" v-if="config.notification.provider">
                    <el-input v-model="config.notification.url" placeholder="请填入推送平台提供的带Token URL"></el-input>
                  </el-form-item>
                </el-form>
              </el-tab-pane>
            </el-tabs>

            <div style="margin-top: 20px;">
              <el-button type="primary" @click="saveConfig" :loading="saving">保存配置并登录</el-button>
            </div>
          </el-card>
        </div>

        <!-- 课程列表视图 -->
        <div v-show="activeIndex === '2'">
          <el-card shadow="never">
            <template #header>
              <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                <span>选择要挂机的课程</span>
                <div>
                  <el-button type="success" @click="fetchCourses" :loading="loadingCourses">刷新课程</el-button>
                  <el-button type="primary" @click="startTask" :disabled="selectedCourses.length === 0">开始刷课</el-button>
                </div>
              </div>
            </template>
            <el-table 
              :data="courses" 
              style="width: 100%" 
              @selection-change="handleSelectionChange"
              v-loading="loadingCourses"
            >
              <el-table-column type="selection" width="55" />
              <el-table-column prop="title" label="课程名称" />
              <el-table-column prop="class_name" label="班级" width="180" />
              <el-table-column prop="teacher" label="教师" width="180" />
            </el-table>
          </el-card>
        </div>

        <!-- 运行控制面板视图 -->
        <div v-show="activeIndex === '3'" class="dashboard">
          <el-card shadow="never" style="margin-bottom: 20px;">
            <template #header>
              <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                <span>当前进度</span>
                <el-button type="danger" @click="stopTask">停止当前任务</el-button>
              </div>
            </template>
            <!-- 动态进度条渲染 -->
            <div v-if="Object.keys(progressBars).length === 0" style="color:#999; text-align: center;">暂无进行中的进度条</div>
            <div v-for="(bar, id) in progressBars" :key="id" class="progress-bar-wrapper">
              <div class="progress-label">{{ bar.desc }}</div>
              <el-progress 
                :percentage="bar.total > 0 ? Math.min(100, Number(((bar.n / bar.total) * 100).toFixed(1))) : 0" 
                :format="() => `${bar.n} / ${bar.total}`"
                :status="bar.n >= bar.total && bar.total > 0 ? 'success' : ''"
              />
            </div>
          </el-card>

          <el-card shadow="never">
            <template #header>
              <span>控制台输出</span>
            </template>
            <div class="log-container" ref="logContainer">
              <div v-for="(log, index) in logs" :key="index" class="log-item">
                <span style="color: #409EFF">[{{ log.time }}]</span> {{ log.msg }}
              </div>
            </div>
          </el-card>
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'

const activeIndex = ref('1')
const activeConfigTab = ref('common')
const saving = ref(false)
const testingApi = ref(false)
const loadingCourses = ref(false)

// 完整映射原本的 ini 配置
const config = ref({
  common: {
    username: '',
    password: '',
    speed: 1.0,
    jobs: 4,
    notopen_action: 'retry',
    add_learning_count: false,
    target_count: 100,
    use_cookies: false
  },
  tiku: {
    provider: 'TikuYanxi',
    submit: false,
    cover_rate: 0.9,
    tokens: '',
    key: '',
    endpoint: '',
    model: ''
  },
  notification: {
    provider: '',
    url: ''
  }
})

const courses = ref<any[]>([])
const selectedCourses = ref<any[]>([])
const logs = ref<{time: string, msg: string}[]>([])
const logContainer = ref<HTMLElement | null>(null)

// 进度条字典：id -> 进度状态
const progressBars = ref<Record<string, { desc: string, n: number, total: number }>>({})

// 切换菜单
const handleSelect = (key: string) => {
  activeIndex.value = key
  if (key === '2' && courses.value.length === 0) {
    fetchCourses()
  }
}

const handleSelectionChange = (val: any[]) => {
  selectedCourses.value = val
}

const pyApi = async (method: string, ...args: any[]) => {
  if (window.pywebview && window.pywebview.api) {
    return await window.pywebview.api[method](...args)
  } else {
    console.warn(`[Mock] Calling ${method}`, args)
    return { success: false, msg: 'PyWebView 未就绪，正在测试模式运行' }
  }
}

// GUI 接收 Python 推送进度的函数
window.updateProgress = (id: string, desc: string, n: number, total: number) => {
  progressBars.value[id] = { desc, n, total }
}

// 供 Python 调用的全局日志推送函数 (保留为了兼容)
window.addLog = (msg: string) => {
  appendLog(msg)
}

const appendLog = (msg: string) => {
  const now = new Date()
  const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`
  logs.value.push({ time: timeStr, msg })
  
  if (logs.value.length > 1000) {
    logs.value.shift()
  }

  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

// 轮询更新 UI (进度和日志)
const pollUpdates = async () => {
  try {
    const res = await pyApi('get_ui_updates')
    if (res && res.success) {
      if (res.logs && res.logs.length > 0) {
        res.logs.forEach((msg: string) => appendLog(msg))
      }
      if (res.progress) {
        progressBars.value = res.progress
      }
    }
  } catch (e) {
    // 忽略轮询异常
  }
}

let pollTimer: any = null

const loadConfig = async () => {
  const res = await pyApi('get_config')
  if (res && res.success && res.data) {
    // 递归合并对象，防止缺失字段
    const mergeObj = (target: any, source: any) => {
      for (const key of Object.keys(source)) {
        if (source[key] instanceof Object && key in target) {
          Object.assign(source[key], mergeObj(target[key], source[key]))
        }
      }
      return Object.assign(target || {}, source)
    }
    config.value = mergeObj(config.value, res.data)
  }
}

const saveConfig = async () => {
  saving.value = true
  const res = await pyApi('save_config_and_login', JSON.stringify(config.value))
  saving.value = false
  if (res.success) {
    ElMessage.success('配置已保存并登录成功！')
    activeIndex.value = '2' // 跳转到课程列表
    fetchCourses()
  } else {
    ElMessage.error(res.msg || '登录失败，请检查账号密码')
  }
}

const testApi = async () => {
  testingApi.value = true
  const res = await pyApi('test_api_connection', JSON.stringify(config.value))
  testingApi.value = false
  if (res.success) {
    ElMessage.success(res.msg)
  } else {
    ElMessage.error(res.msg)
  }
}

const fetchCourses = async () => {
  loadingCourses.value = true
  const res = await pyApi('get_courses')
  loadingCourses.value = false
  if (res.success) {
    courses.value = res.data
    ElMessage.success(`成功获取 ${courses.value.length} 门课程`)
  } else {
    ElMessage.error(res.msg || '获取课程失败，请先登录')
  }
}

const startTask = async () => {
  if (selectedCourses.value.length === 0) return
  const courseIds = selectedCourses.value.map(c => c.courseId)
  activeIndex.value = '3' // 跳转到控制面板
  window.addLog(`准备开始执行 ${courseIds.length} 门课程任务...`)
  const res = await pyApi('start_tasks', JSON.stringify(courseIds))
  if (!res.success) {
    ElMessage.error(res.msg || '启动任务失败')
  }
}

const stopTask = async () => {
  const res = await pyApi('stop_tasks')
  if (res.success) {
    window.addLog('已发送停止指令...')
  }
}

onMounted(() => {
  window.addEventListener('pywebviewready', function() {
    loadConfig()
    if (!pollTimer) pollTimer = setInterval(pollUpdates, 500)
  })
  if (!window.pywebview) {
    setTimeout(() => {
      loadConfig()
      if (!pollTimer) pollTimer = setInterval(pollUpdates, 500)
    }, 1000)
  }
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style>
html, body, #app {
  margin: 0;
  padding: 0;
  height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

.layout-container {
  height: 100vh;
}

.aside {
  background-color: #304156;
  color: white;
  display: flex;
  flex-direction: column;
}

.logo {
  height: 60px;
  line-height: 60px;
  text-align: center;
  border-bottom: 1px solid #1f2d3d;
}

.logo h3 {
  margin: 0;
  color: #fff;
  font-weight: 500;
}

.el-menu {
  border-right: none;
}

.dashboard {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.progress-bar-wrapper {
  margin-bottom: 15px;
}
.progress-label {
  font-size: 13px;
  margin-bottom: 5px;
  color: #606266;
}

.log-container {
  height: calc(100vh - 380px);
  min-height: 200px;
  overflow-y: auto;
  background-color: #1e1e1e;
  color: #d4d4d4;
  padding: 10px;
  border-radius: 4px;
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
  line-height: 1.5;
}

.log-item {
  margin-bottom: 4px;
}
</style>
