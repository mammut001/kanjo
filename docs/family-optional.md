# 家庭用量 · 改成可选功能（规则草案）

> 目标：Kanjo 的普通用户默认完全看不到、也不会触发家庭上报；想用的人打开开关后，App 告诉他两条路：
> 加入别人的家庭，或者自己部署服务器。我们家的地址和配置不再写进代码里当默认值。
> 先确认规则再写码。

## 现状（要改的原因）

- Mac 设置里的开关已经默认关闭，但**服务器地址默认是 `https://usage.paytonpei.top`**：别人打开开关、粘贴令牌，就会往我们的服务器发数据。
- Windows 安装脚本 `-Server` 默认也是我们的域名。
- 服务端代码里写死了我们的值：`FAMILY_PUBLIC_ORIGIN` 默认 `usage.paytonpei.top`；Firebase 项目默认 `kanjo-family-usage`；CSP 的 `frame-src` 直接写了 `kanjo-family-usage.firebaseapp.com`。别人用自己的 Firebase 项目部署，Google 登录会被 CSP 拦掉。
- `family-server/README.md` 写的是我们这台 VPS 的具体配置，别人照着没法部署。

## 1. Mac App

- 开关保持**默认关闭**。关闭时只显示开关和一行说明：「把用量汇总报给你自己或家人搭的服务器，用于共享套餐（如 Google AI Ultra）。默认关闭。」
- 打开后，先显示两个选项：
  1. **加入家庭**：管理员会给你服务器地址和令牌。显示地址输入框（**默认空**，占位 `https://usage.example.com`）、令牌、显示名、「立即上报」。
  2. **自己当管理员**：一段简短说明（需要一台 VPS、一个域名、一个 Firebase 项目），加一个「查看部署教程」按钮，打开 GitHub 上的 `family-server/DEPLOY.md`。
- 地址为空或不合法时**不上报**，状态写「未填写服务器地址」。
- **老用户迁移**（保证我们家现有成员不断）：如果开关已经打开，但地址从没手动填过（用的是旧默认值），升级时一次性把 `https://usage.paytonpei.top` 写进设置。开关没开过的人什么都不写。

## 2. Windows 安装脚本

- 去掉 `-Server` 的默认值。没传时交互式询问服务器地址（必须是 `https://`）；用 `-NoPrompt` 又没传，就报错退出。
- 管理员发给成员的命令带上地址：
  `... & $f -Server https://usage.example.com`

## 3. CLI

- `report-family --url` 本来就必须写，不变。
- README 和帮助文字里的示例地址统一换成 `https://usage.example.com`。

## 4. 服务端（family-server）

- 去掉所有我们家的默认值：
  - `FAMILY_PUBLIC_ORIGIN`、`FIREBASE_PROJECT_ID`、`FIREBASE_WEB_CONFIG_JSON` 都改成**必填**，缺了就启动失败并说明缺哪个；
  - CSP `frame-src` 改为根据 `authDomain` 生成。
- 我们自己 VPS 上的 `family.env` 已经填了这些值，部署后行为不变（上线前我会核对）。
- `deploy.sh` 的安装目录允许通过环境变量覆盖，默认仍是 `/opt/family-usage`。
- 新写 **`family-server/DEPLOY.md`**（中英文），面向第一次搭的人：
  1. 准备：一台装好 Docker 的 VPS；一个托管在 Cloudflare 的域名；一个 Firebase 项目（开启 Google 登录，把你的域名加进授权域名）。
  2. 建 Cloudflare Tunnel，把 `你的域名` 指向容器（附 cloudflared 配置模板）。
  3. 填 `family.env`（模板，全部用占位符）。
  4. 运行 `deploy.sh`，打开 `https://你的域名/healthz` 检查。
  5. 给成员建令牌：`member add`，把「地址 + 令牌 + Mac/Windows 加入步骤」发给对方。
  6. 安全提示：限制 Firebase API key 的来源和可用 API；只放行管理员邮箱。
- `family-server/README.md` 只保留架构和安全说明，改用占位符；我们家的具体配置（域名、隧道 ID、邮箱）不放进仓库，记在我的项目笔记里。

## 5. README

- 「家庭用量」一节开头写明：**可选，默认关闭，需要自己（或家人）部署服务器**。
- 分两块：
  - **加入家庭**：问管理员要地址和令牌，按 Mac / Windows 两行操作；
  - **自己部署**：链接到 `family-server/DEPLOY.md`。
- 不再出现「我们家是 usage.paytonpei.top」这类说法。

## 6. 测试

- Swift：默认地址为空时不上报；迁移只在「已开启且没填过地址」时写入旧地址；地址校验。
- 服务端：缺少必填环境变量时启动失败；CSP 按 authDomain 生成。
- Windows CI：带 `-Server` 能装好；`-NoPrompt` 且没给 `-Server` 时退出码非 0。
- 上线后：用我们的 VPS 跑一次部署，Google 登录和成员上报都正常。

## 不做

- 不做「一键部署到 VPS」的脚本或托管服务，只写教程。
- 不提供公共服务器。
