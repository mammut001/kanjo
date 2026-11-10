# 家庭用量汇总（Family usage）规则草案

> 目的：Google AI Ultra 家庭组里，每个成员电脑上的 Kanjo 把用量汇总报到我们自己的服务器，你在一个面板上看到每个人用了多少、额度池还剩多少、被谁用掉的。
> 先确认规则再写码。分两批交给 agy：第一批服务器，第二批 Kanjo 端。

## 0. 已经做好的

- Cloudflare Tunnel `family-usage`（id `0bfee670-…`），凭证在 VPS `/opt/family-usage/cloudflared/`。
- DNS：`usage.paytonpei.top` → 这条隧道。隧道尚未启动。
- VPS（vps-greencloud）：Ubuntu 26.04，Docker 在跑，**没有 docker compose**，Tailscale IP `100.115.238.6`，对外只开 22。

## 1. 总体结构

```
成员的 Mac（Kanjo） ──HTTPS POST──▶ usage.paytonpei.top ──Cloudflare Tunnel──▶ VPS: app 容器 :8788（只接上报）
你（Tailscale） ──────────────────────────────────────────────▶ VPS: 100.115.238.6:8787（面板）
```

- **公网只暴露两个路径**：`POST /api/report`、`GET /healthz`。隧道的 ingress 规则只转发这两个，其他一律 404。
- **面板不上公网**：只监听 Tailscale IP，只有你能打开（手机装了 Tailscale 也能看）。
- 家人什么都不用装，只在 Kanjo 里填地址和令牌。

## 2. 上报内容（隐私）

只发汇总数字，和网站公开汇总同一口径：

- **不发**：项目名、路径、仓库地址、分支、会话 id、会话标题、对话内容、账号邮箱。
- **发**：
  - `member_label`：成员在 Kanjo 里自己填的显示名（可空，服务器以令牌对应的名字为准）
  - `generated_at`、`timezone`、`generated_by`
  - `summary`：现有公开汇总的结构（`all_time` / `months` / `weeks`），外加 `days`（最近 31 天，结构同 Period，`period` 为 `YYYY-MM-DD`）
  - `quota_windows`：Kanjo 现有的额度窗口原样上报（Antigravity 周窗口 / 5 小时窗口 / extra_windows 等，各 agent 都带）
  - `plans`：各 agent 的订阅档位标签（如 "Google AI Ultra"），**不带 account 字段**
- Kanjo CLI 新命令输出这份文档：`kanjo export --family-report`（与 `--mobile`、`--public-summary` 互斥）。CONTRACT.md 新增一节写结构。

## 3. 服务器（第一批）

代码放在 kanjo 仓库新目录 `family-server/`（和契约一起维护），部署到 VPS `/opt/family-usage/`。

- **技术**：Python 3（标准库 `http.server` + `sqlite3`，不引第三方依赖），镜像 `python:3.14-slim`。一个进程开两个监听：
  - `0.0.0.0:8788`（容器内）上报 API，只给 cloudflared 容器访问（同一个 docker network，不发布到宿主端口）
  - `0.0.0.0:8787`（容器内）面板，发布到宿主 `100.115.238.6:8787`
- **cloudflared**：独立容器，同一 docker network，`config.yml` 的 ingress：
  - `path: ^/api/report$` → `http://family-app:8788`
  - `path: ^/healthz$` → `http://family-app:8788`
  - 兜底 `http_status:404`
- **部署脚本** `family-server/deploy.sh`：只用 `docker network create` / `docker build` / `docker run --restart unless-stopped`，不装 compose。幂等（重复运行会替换容器、保留数据卷）。
- **存储**：SQLite 文件在宿主 `/opt/family-usage/data/family.db`。
  - `members(id, name, token_sha256, created_at, revoked_at)`
  - `reports(member_id, received_at, generated_at, payload_json)`：每个成员保留最新一份 + 每天最后一份（历史 90 天，自动清理更早的）
- **令牌**：
  - 管理命令：`docker exec family-app python -m family_server member add <名字>`（生成令牌，只打印这一次）、`member list`、`member revoke <名字>`。
  - 只存 SHA-256，不存明文。
- **上报接口** `POST /api/report`：
  - `Authorization: Bearer <令牌>`；令牌无效或已作废 → 401。
  - 请求体 ≤ 2 MB，JSON，`kind == "kanjo-family-report"`，结构校验不过 → 400。
  - 服务器再做一次隐私兜底：payload 里出现 `/Users/`、`@`、`sessions_detail`、`account` 等字段或模式 → 400 并记日志（不入库）。
  - 限流：每个令牌每分钟最多 1 次，超了 429。
  - 成功 → 200 `{"status":"ok","received_at":...}`。
- **面板** `GET /`（只在 Tailscale 上）：中文界面，服务端渲染一页 HTML，不引前端框架。
  1. 顶部：Google AI Ultra 额度池——各成员最近一次上报的 Antigravity 周窗口已用百分比和重置时间。如果是共享池，大家报上来的数字应该接近；不一致时并列显示，不猜。
  2. 每个成员一张卡：今天 / 近 7 天 / 本月的 token 和折算金额，按模型列前 5，最近一次上报时间（超过 24 小时标「未更新」）。
  3. 本周「谁用掉了额度池」：按 Antigravity（Google 模型）本周 token 排名，显示占比。
  4. 近 30 天按人分色的每日柱状图（SVG 手写）。
  - 金额旁注明「按公开 API 价格折算，不是实际支出」。
- **测试**：`family-server/tests/`，标准库 unittest：令牌哈希、401/400/429/200、隐私兜底、历史清理、面板渲染（用 fixture 报文）。
- **验收**：
  - 本机 `python3 -m unittest` 通过。
  - 部署后：`curl https://usage.paytonpei.top/healthz` = 200；`/` 和其他路径从公网访问 = 404；面板在 `http://100.115.238.6:8787` 能打开。
  - 用临时令牌 POST 一份 fixture 报文，面板上出现；作废令牌后再 POST = 401。

## 4. Kanjo 端（第二批）

- **CLI**
  - `kanjo export --family-report`：输出第 2 节的文档。
  - `kanjo report-family --url URL`：生成报文并 POST。令牌从环境变量 `KANJO_FAMILY_TOKEN` 读，**不走命令行参数**（避免出现在进程列表里）。输出一行 JSON 状态（`sent` / `error` + message）。只用标准库 `urllib`，超时 30 秒，失败不重试（由 App 调度）。
- **App 设置**：在「发布到网站」那节后面加「家庭用量」：
  - 开关（默认关）
  - 服务器地址（默认 `https://usage.paytonpei.top`）
  - 令牌：存 **macOS 钥匙串**，不存 UserDefaults；界面上只显示「已设置 / 未设置」和「更换」
  - 显示名（可选）
  - 状态行：上次上报时间或错误信息；「立即上报」按钮
  - 一句说明：会上报哪些数字、不会上报项目名和路径
- **调度**：每次刷新完成后，开关打开且距上次成功超过 15 分钟才上报；后台 QoS；同一时间只跑一个；失败后至少等 30 分钟再自动重试；`no_network` 时不上报。逻辑写成 KanjoCore 纯函数 + 测试（参照 PublishSchedule）。
- **验收**：用临时设置域 + 临时令牌端到端跑一次（同发布功能的隔离测试做法）；关掉开关后不再上报；报文里搜不到 `/Users`、`@`、项目名。

## 5. 需要你确认 / 提供

1. 成员名单（名字即可，我在服务器上生成令牌后私下发给每个人）。
2. 面板语言只做中文可以吗？
3. 历史保留 90 天够不够？
