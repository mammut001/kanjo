# Deploying Kanjo Family Usage Server / 部署 Kanjo 家庭用量服务器

[English](#english) | [简体中文](#简体中文)

---

<a name="english"></a>
# English

This guide walks you through deploying your own Kanjo Family Usage Server on a Linux VPS using Docker and Cloudflare Tunnel.

The family usage server aggregates high-level token counts and quota windows from all family members, allowing the administrator of a shared plan (such as Google AI Ultra) to monitor usage and quota pools from a private web dashboard.

---

## 1. Prerequisites

Before beginning, ensure you have:

1. **A Linux VPS with Docker installed** (e.g. Ubuntu 22.04 or 24.04). No `docker compose` is required—standard `docker` is sufficient.
2. **A domain managed on Cloudflare** (e.g. `example.com`), where you can route a subdomain like `usage.example.com`.
3. **A Google Firebase Project**:
   - Go to the [Firebase Console](https://console.firebase.google.com/) and create a new project.
   - Under **Build → Authentication**, click **Get Started**, enable the **Google** sign-in provider, and save.
   - In **Authentication → Settings → Authorized domains**, add your public domain (e.g. `usage.example.com`).
   - Under **Project Settings (General) → Your apps**, click the web icon (`</>`) to register a web app. Copy the Firebase SDK configuration object:
     ```json
     {
       "apiKey": "AIzaSy...",
       "authDomain": "your-project-id.firebaseapp.com",
       "projectId": "your-project-id",
       "appId": "1:...:web:...",
       "messagingSenderId": "..."
     }
     ```

---

## 2. Cloudflare Tunnel Setup

Cloudflare Tunnel exposes the server container securely without opening incoming ports on your VPS firewall.

1. **Install `cloudflared` locally or on your VPS**:
   ```bash
   # Follow Cloudflare documentation to install cloudflared
   cloudflared tunnel login
   ```
2. **Create the tunnel**:
   ```bash
   cloudflared tunnel create family-usage
   ```
   This generates a tunnel UUID (e.g. `12345678-abcd-1234-abcd-1234567890ab`) and saves a credentials JSON file in `~/.cloudflared/<TUNNEL_ID>.json`.
3. **Route DNS to the tunnel**:
   ```bash
   cloudflared tunnel route dns family-usage usage.example.com
   ```
4. **Place credentials and ingress configuration in `cloudflared/`**:
   Copy `<TUNNEL_ID>.json` into `/opt/family-usage/cloudflared/`.
   The `deploy.sh` script will automatically populate `cloudflared/config.yml` from `cloudflared/config.yml.template`:
   - `POST /api/report` and `GET /healthz` route to `http://family-app:8788` (the internal report receiver).
   - All other routes for your domain route to `http://family-app:8787` (the web dashboard).
   - All other unmatched requests return HTTP 404.

---

## 3. Environment Configuration (`family.env`)

Create `/opt/family-usage/family.env` on your VPS.

> [!IMPORTANT]
> **Values in `family.env` are literal (no shell quotes)**: Docker reads `--env-file` literally without stripping quotes. Do **not** wrap strings or JSON in quotes (e.g. write `FAMILY_PUBLIC_ORIGIN=https://usage.example.com` and `FIREBASE_WEB_CONFIG_JSON={"apiKey":...}` rather than `'{"apiKey":...}'`).

Template `/opt/family-usage/family.env`:

```bash
# Public URL of the family server (used for CSRF validation and dashboard origins)
FAMILY_PUBLIC_ORIGIN=https://usage.example.com

# Firebase Web App JSON configuration (compact JSON on a single line, NO surrounding quotes)
FIREBASE_WEB_CONFIG_JSON={"apiKey":"AIzaSy...","authDomain":"your-project-id.firebaseapp.com","projectId":"your-project-id","appId":"1:...:web:...","messagingSenderId":"..."}

# Allowed Administrator Google Accounts (comma-separated, case-insensitive)
# Only Google users with these emails will be permitted to sign into the dashboard.
FAMILY_ADMIN_EMAILS=admin@example.com

# Cloudflare Tunnel ID (matches the filename in cloudflared/<TUNNEL_ID>.json)
TUNNEL_ID=12345678-abcd-1234-abcd-1234567890ab

# Optional: Timezone for cycle aggregation (default: America/Toronto)
FAMILY_TIMEZONE=America/Toronto

# Optional: Set to 1 to also bind dashboard port 8787 to TAILSCALE_IP
PUBLISH_TAILSCALE=0
# TAILSCALE_IP=100.x.y.z
```

---

## 4. Deploy and Verify

1. **Copy the server directory to your VPS**:
   ```bash
   # From your local repository:
   rsync -avz family-server/ user@your-vps:/opt/family-usage/
   ```
2. **Run deployment script**:
   ```bash
   cd /opt/family-usage
   bash deploy.sh
   ```
   The script creates Docker network `family-net`, builds the container `family-usage-app`, starts `family-app`, and runs `family-cloudflared`.
3. **Verify the server is healthy**:
   ```bash
   curl -i https://usage.example.com/healthz
   # Expected response: HTTP 200 {"status":"ok"}
   ```
4. **Access the dashboard**:
   Open `https://usage.example.com/` in your browser. You will be redirected to the login page. Sign in with one of the emails listed in `FAMILY_ADMIN_EMAILS`.

---

## 5. Member Management & Client Onboarding

Tokens are generated on the server and stored as SHA-256 hashes in SQLite.

### Adding a member

Run inside the `family-app` container:

```bash
docker exec family-app python -m family_server member add "Alice"
```

Output:
```text
Successfully added member 'Alice' (ID: 1).
Token: kanjo_fam_xxxxxxxxxxxxxxxxxxxxxxxxxxxx

IMPORTANT: Store this token now. It will NEVER be shown again.
```

### Revoking a member

```bash
docker exec family-app python -m family_server member revoke "Alice"
```

### What to send to a family member

Send the member:
1. The **server address**: `https://usage.example.com`
2. Their **personal token** (e.g. `kanjo_fam_...`)
3. Setup instructions for their computer:

- **Mac users**:
  1. Open Kanjo → Settings → **Family usage**.
  2. Toggle it **On**.
  3. Select **Join a family**.
  4. Paste Server URL `https://usage.example.com` and your token (stored in macOS Keychain).
  5. Optionally enter your display name (e.g. `Alice (MacBook)`).
  6. Click **Report now** to confirm.

- **Windows users**:
  Open PowerShell (as regular user, no administrator rights needed) and run:
  ```powershell
  powershell -ExecutionPolicy Bypass -NoProfile -Command '$f=Join-Path $env:TEMP kanjo-family.ps1; irm https://github.com/mammut001/kanjo/releases/latest/download/install-family-windows.ps1 -OutFile $f; & $f -Server https://usage.example.com'
  ```
  Paste the token when prompted. The installer schedules a background task running every 30 minutes.

*(Note: As the family manager, you can also report your own Mac's usage by setting the mode to "Join a family" in Kanjo settings!)*

---

## 6. Security Recommendations

1. **Restrict the Firebase API Key**:
   - In Google Cloud Console (**APIs & Services → Credentials**), locate your Firebase Web API Key.
   - Under **Application restrictions**, select **Websites** and add `https://usage.example.com/*`.
   - Under **API restrictions**, select **Restrict key** and restrict to only:
     - *Identity Toolkit API*
     - *Token Service API*
2. **Whitelist Only Trusted Admins**:
   - Ensure `FAMILY_ADMIN_EMAILS` only contains your personal Google accounts. Any other Google account will be rejected with HTTP 403.
3. **Token Hashing**:
   - Bearer tokens are stored exclusively as SHA-256 digests in `/opt/family-usage/data/family.db`. Cleartext tokens are never written to disk or logs.
4. **Isolated Network**:
   - Neither the API port (8788) nor the dashboard port (8787) is exposed directly on the public internet. All traffic flows through the encrypted Cloudflare Tunnel.

---

<a name="简体中文"></a>
# 简体中文

本指南指导你在 Linux VPS 上使用 Docker 和 Cloudflare Tunnel 部署自己的 Kanjo 家庭用量统计服务器。

家庭用量服务器用于接收来自所有家庭成员的 Token 用量汇总与额度重置窗口。共享套餐（例如 Google AI Ultra）的管理员可以通过私有 Web 面板直观查看整个额度池的使用情况与各成员分布。

---

## 1. 准备工作

开始部署前，请确认具备以下条件：

1. **一台装有 Docker 的 Linux VPS**（如 Ubuntu 22.04 / 24.04）。不需要 `docker compose`，标准的 `docker` 即可。
2. **一个托管在 Cloudflare 上的域名**（例如 `example.com`），用于配置如 `usage.example.com` 的子域名。
3. **一个 Google Firebase 项目**：
   - 访问 [Firebase 控制台](https://console.firebase.google.com/) 创建新项目。
   - 在左侧进入 **构建 → Authentication**，点击开始，在登录提供方中启用 **Google 登录** 并保存。
   - 在 **Authentication → 设置 → 授权网域** 中，添加你的公网域名（如 `usage.example.com`）。
   - 在 **项目设置（常规）→ 您的应用** 中点击网页图标（`</>`）添加网页应用，复制 Firebase 配置对象：
     ```json
     {
       "apiKey": "AIzaSy...",
       "authDomain": "your-project-id.firebaseapp.com",
       "projectId": "your-project-id",
       "appId": "1:...:web:...",
       "messagingSenderId": "..."
     }
     ```

---

## 2. 配置 Cloudflare 隧道 (Cloudflare Tunnel)

通过 Cloudflare Tunnel，可以在 VPS 防火墙完全不对公网开放任何入站端口的前提下将服务发布到域名。

1. **安装 `cloudflared` 并登录**：
   ```bash
   cloudflared tunnel login
   ```
2. **创建隧道**：
   ```bash
   cloudflared tunnel create family-usage
   ```
   该命令会生成隧道 UUID（例如 `12345678-abcd-1234-abcd-1234567890ab`）并在 `~/.cloudflared/<TUNNEL_ID>.json` 生成凭证文件。
3. **绑定 DNS 记录到隧道**：
   ```bash
   cloudflared tunnel route dns family-usage usage.example.com
   ```
4. **将凭证放入 `cloudflared/` 目录**：
   将 `<TUNNEL_ID>.json` 复制到 `/opt/family-usage/cloudflared/` 目录下。
   `deploy.sh` 脚本在运行时会自动读取 `cloudflared/config.yml.template` 生成 `cloudflared/config.yml`：
   - `POST /api/report` 与 `GET /healthz` 指向内部上报接口 `http://family-app:8788`。
   - 域名下的其余所有请求指向 Web 面板 `http://family-app:8787`。
   - 其它未匹配流量一律返回 HTTP 404。

---

## 3. 配置环境变量 (`family.env`)

在 VPS 上创建配置文件 `/opt/family-usage/family.env`。

> [!IMPORTANT]
> **`family.env` 中的值是原义字面量（不要加引号）**：Docker 在读取 `--env-file` 时不会剥除单引号或双引号。请直接书写字面值（例如 `FAMILY_PUBLIC_ORIGIN=https://usage.example.com` 和 `FIREBASE_WEB_CONFIG_JSON={"apiKey":...}`，**不要**写成 `'{"apiKey":...}'`）。

`/opt/family-usage/family.env` 示例：

```bash
# 服务器公网访问地址（用于 CSRF 检查与面板重定向）
FAMILY_PUBLIC_ORIGIN=https://usage.example.com

# Firebase Web 应用 JSON 配置（单行紧凑 JSON，两端切勿包裹引号）
FIREBASE_WEB_CONFIG_JSON={"apiKey":"AIzaSy...","authDomain":"your-project-id.firebaseapp.com","projectId":"your-project-id","appId":"1:...:web:...","messagingSenderId":"..."}

# 授权管理员 Google 邮箱列表（英文逗号分隔，不区分大小写）
# 只有在列表内的邮箱才能成功登录后台面板。
FAMILY_ADMIN_EMAILS=admin@example.com

# Cloudflare Tunnel ID（与 cloudflared/<TUNNEL_ID>.json 文件名一致）
TUNNEL_ID=12345678-abcd-1234-abcd-1234567890ab

# 可选：统计周期的时区（默认：America/Toronto）
FAMILY_TIMEZONE=America/Toronto

# 可选：是否额外将 8787 面板端口发布到 Tailscale IP（0 为不发布）
PUBLISH_TAILSCALE=0
# TAILSCALE_IP=100.x.y.z
```

---

## 4. 部署与验证

1. **将服务端代码同步到 VPS**：
   ```bash
   # 在本地项目根目录下：
   rsync -avz family-server/ user@your-vps:/opt/family-usage/
   ```
2. **运行部署脚本**：
   ```bash
   cd /opt/family-usage
   bash deploy.sh
   ```
   脚本将创建 Docker 网络 `family-net`，构建镜像 `family-usage-app`，启动服务容器 `family-app` 与隧道容器 `family-cloudflared`。
3. **验证健康检查接口**：
   ```bash
   curl -i https://usage.example.com/healthz
   # 预期返回：HTTP 200 {"status":"ok"}
   ```
4. **访问面板**：
   在浏览器中打开 `https://usage.example.com/`，会自动跳转至登录页面。使用 `FAMILY_ADMIN_EMAILS` 白名单内的 Google 账号登录即可进入面板。

---

## 5. 成员管理与客户端接入

成员令牌在服务器端生成，以 SHA-256 单向哈希形式持久化保存在 SQLite 数据库中。

### 添加成员

在宿主机上通过 `family-app` 容器执行：

```bash
docker exec family-app python -m family_server member add "Alice"
```

输出：
```text
Successfully added member 'Alice' (ID: 1).
Token: kanjo_fam_xxxxxxxxxxxxxxxxxxxxxxxxxxxx

IMPORTANT: Store this token now. It will NEVER be shown again.
```

### 作废成员

```bash
docker exec family-app python -m family_server member revoke "Alice"
```

### 发送给成员的信息

将以下内容发给家庭成员：
1. **服务器地址**：`https://usage.example.com`
2. **个人专属令牌**（例如 `kanjo_fam_...`）
3. 对应的客户端接入指引：

- **Mac 用户**：
  1. 打开 Kanjo → 设置 → **家庭用量**。
  2. 打开开关，在模式中选择 **加入家庭**。
  3. 填入服务器地址 `https://usage.example.com`，粘贴你的令牌（保存在 macOS 钥匙串中）。
  4. 可选填写显示名（例如 `Alice (MacBook)`）。
  5. 点击 **立即上报** 测试连通性。

- **Windows 用户**：
  打开 PowerShell（普通用户权限即可，无需管理员），运行：
  ```powershell
  powershell -ExecutionPolicy Bypass -NoProfile -Command '$f=Join-Path $env:TEMP kanjo-family.ps1; irm https://github.com/mammut001/kanjo/releases/latest/download/install-family-windows.ps1 -OutFile $f; & $f -Server https://usage.example.com'
  ```
  在提示处粘贴令牌。脚本会自动在后台注册每 30 分钟静默上报的定时任务。

*(注：管理员自己本机的 Mac 也可以切回「加入家庭」，填入自己的令牌将用量一同上报！)*

---

## 6. 安全加固建议

1. **限制 Firebase API Key 范围**：
   - 访问 Google Cloud 控制台（**API 和服务 → 凭据**），找到 Firebase 生成的 Web API Key。
   - 在 **应用限制** 中选择 **网站**，添加 `https://usage.example.com/*`。
   - 在 **API 限制** 中选择 **限制密钥**，仅允许勾选：
     - *Identity Toolkit API*
     - *Token Service API*
2. **只允许受信任的管理员邮箱**：
   - `FAMILY_ADMIN_EMAILS` 仅填写你自己的 Google 邮箱。任何未授权的 Google 账号登录都会被直接拦截（HTTP 403）。
3. **令牌单向哈希**：
   - 所有客户端 Bearer 令牌在 `/opt/family-usage/data/family.db` 中均仅存储 SHA-256 哈希值，明文绝不落盘、不记日志。
4. **容器网络隔离**：
   - 上报端口 (8788) 与面板端口 (8787) 均不对公网网卡直接暴露，所有请求均通过 Cloudflare Tunnel 加密内网穿透到达。
