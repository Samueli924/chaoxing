# 前端方案

目标：让不会用命令行的用户，打开网页 → 输入账号密码 → 勾选课程与任务 → 一键完成，并能看到实时进度。

## 一、已实现的前端（本仓库内）

已内置一个**零依赖的本地网页控制台**（`api/web.py` + `resource/web/index.html`，仅用 Python 标准库，随程序分发）：

```
浏览器 (index.html, 单页)  ⇄  本机 HTTP 服务 (api/web.py)  ⇄  Runner/Chaoxing 核心
```

- 启动：`python main.py --web`，或**双击打包好的 exe** 自动打开浏览器。
- 页面流程：访问口令（仅对外开放时）→ 登录 → 选择课程 → 选择任务（任务点 / 章节检测方式 / 章节学习次数）→ 开始 → 实时进度条 + 日志 + 结果汇总，可随时停止。
- 适配手机/桌面，深色模式自动适配，无需任何前端构建、无外部 CDN。

### 安全设计（已实现）
- 默认只监听 `127.0.0.1`；监听其它地址时**强制访问口令**（未设置 `CHAOXING_WEB_TOKEN` 时自动生成并打印到日志）。
- 写操作要求自定义请求头（阻止跨站请求伪造 CSRF）；本机模式校验 `Host`（阻止 DNS 重绑定）。
- 密码只用于登录学习通、只存在于内存，不回传给页面；已保存的题库密钥不回传。

## 二、关于 rdfz.net 二级域名部署

> ⚠️ **重要前提**：本工具会用**用户本人的手机号和密码**登录学习通。如果把它做成一个**面向所有人、公开收集账号密码**的网站，等于把大量他人的学习通凭据集中到一台服务器上——这既有安全与隐私风险，也容易被当作钓鱼站点。因此**不建议**在 rdfz.net 上部署"任何人都能输入账号密码"的公共多租户服务。

推荐在 rdfz.net 二级域名上采用下面两种方式之一：

### 方案 A（推荐，安全）：静态介绍/下载页
- 域名：**`chaoxing.rdfz.net`**（备选：`gk.rdfz.net`、`kb.rdfz.net`）。
- 内容：项目介绍 + 使用说明 + 下载链接（指向 GitHub Releases 的 exe）+ "如何本地运行网页控制台"的图文引导。
- 特点：**不接触任何账号密码**，纯静态，可托管在 GitHub Pages / Cloudflare Pages / 校内静态服务器，零运维、零风险。
- 我可以直接产出这个静态页面（复用现有页面的视觉风格）。

### 方案 B（进阶，单人自用）：自建单用户控制台
- 适合**你自己或少数受信任的人**在一台服务器上自用，不对外开放注册。
- 架构：`chaoxing.rdfz.net` → 反向代理 (Nginx/Caddy, HTTPS) → 本机 `127.0.0.1:8765` 的网页控制台。
- 必须：强访问口令（`CHAOXING_WEB_TOKEN`）、HTTPS、来源 IP 白名单或额外一层 Basic Auth。

  Caddy 示例（自动 HTTPS）：
  ```
  chaoxing.rdfz.net {
      reverse_proxy 127.0.0.1:8765
      basic_auth { admin <bcrypt-hash> }   # 额外一层口令
  }
  ```

  systemd 常驻：
  ```ini
  [Service]
  Environment=CHAOXING_WEB_HOST=127.0.0.1
  Environment=CHAOXING_WEB_PORT=8765
  Environment=CHAOXING_WEB_TOKEN=<强口令>
  Environment=CHAOXING_DATA_DIR=/var/lib/chaoxing
  ExecStart=/usr/bin/python3 /opt/chaoxing/main.py --web --no-browser
  Restart=on-failure
  ```

  或 Docker：
  ```bash
  docker run -d --name chaoxing -p 127.0.0.1:8765:8765 \
    -e CHAOXING_WEB_TOKEN=<强口令> -v /var/lib/chaoxing:/data chaoxing
  ```

### 不推荐：公共多租户服务
公开让任意用户输入学习通账号密码的托管站点，涉及集中保管他人凭据，风险与合规问题都很大，故不在本方案内实现。

## 三、建议与下一步

1. **域名**：建议 `chaoxing.rdfz.net`。
2. **部署形态**：优先**方案 A（静态下载/介绍页）**面向大众；需要自己远程用时叠加**方案 B（单人自建 + HTTPS + 口令）**。
3. 需要你确认：采用 A 还是 A+B、以及最终二级域名。确认后：
   - 选 A：我产出静态站点文件（`site/` 目录），你把它托管到 rdfz.net 对应二级域名即可。
   - 选 B：由你在自己的服务器上按上面的步骤部署（rdfz.net 的 DNS 与服务器需要你操作，我无法代为访问）。

> 说明：rdfz.net 的 DNS 解析与服务器均需在你的基础设施上完成，我无法从当前环境直接部署到该域名；本方案确定后即可落地。
