---
name: "publish-to-wechat"
description: "AI-ready skill to format and publish Markdown articles to WeChat Official Accounts using Wenyan CLI."
---

# 微信公众号文章发布工具 (WeChat Publisher)

这是一个专门为 AI Agent 设计的技能，用于将标准的 Markdown 文档转换为符合微信公众号排版要求的富文本并直接发布。它集成了自动化样式注入、代码高亮处理以及素材库图片自动上传功能。

## 前置要求

- **环境配置**：必须设置 `WECHAT_APP_ID` 和 `WECHAT_APP_SECRET` 环境变量。这两个凭证已写入用户的 `~/.zshrc`，因此在执行任何 `wenyan` 命令前，**必须先 `source ~/.zshrc` 以加载凭证**：

    ```bash
    source ~/.zshrc && wenyan publish -f my-article.md
    ```

    > ⚠️ Agent 执行的每个 shell 调用都是独立进程，不会继承上一次的环境变量。因此 **每一条调用 `wenyan` 的命令都要在同一行前置 `source ~/.zshrc &&`**，否则会报 `invalid credential`。
- **依赖工具**：已安装 `wenyan-cli` (`pnpm add -g @wenyan-md/cli`)。

## ⛓️ 铁律：用 node 直接调用 CLI 发布（务必遵守）

> **发布文章时，一律使用下面这条命令，不要用裸 `wenyan` 命令：**
>
> ```bash
> source ~/.zshrc && node /opt/homebrew/lib/node_modules/@wenyan-md/cli/dist/cli.js publish -f 文件.md -t orangeheart
> ```
>
> **为什么必须这样：** `wenyan` 只是指向 `.../@wenyan-md/cli/dist/cli.js` 的软链接。Agent 子 shell 的 PATH 上若存在一个有问题的 `node`，裸 `wenyan` 会**静默无任何输出、退出码却为 0**——看起来成功，实则草稿从未写入微信草稿箱，极具迷惑性。改用 `node <cli 绝对路径>` 显式调用正确的 node，才能拿到真正的回执：`发布成功，Media ID: xxxx`。
>
> **发布后务必二次核验**（退出码 0 ≠ 真的发布成功）：拿 `WECHAT_APP_ID/SECRET` 换 access_token，调 `cgi-bin/draft/count` 看草稿数是否 +1、`cgi-bin/draft/batchget` 确认标题/封面无误。只有在草稿箱里真实看到这篇，才算发布成功。

## 核心能力

- **自动化排版**：支持多种内置主题（如 `orangeheart`）和代码高亮方案。
- **智能素材处理**：自动解析 Markdown 中的本地或网络图片，并同步上传至微信素材库。
- **元数据驱动**：通过 YAML Frontmatter 自动配置文章标题、封面、作者和原文链接。
- **高度可定制**：支持自定义 CSS 主题注入，满足个性化品牌视觉。

## AI Agent 指令指南：发布流程规范

### Frontmatter 约束 (必须包含)

文章开头 **必须** 包含以下 YAML 块，否则发布接口将返回错误：

```yaml
---
title: 文章标题
cover: ./cover.jpg # 若缺省则自动取正文第一张图；推荐用下方流程动态生成
author: A_You # ⛓️ 固定值，务必填 A_You，不要随机生成或改成其它作者名
source_url: https://example.com/original-article # 可选，原文链接
---
```

> ⛓️ **作者铁律**：`author` 字段**一律固定为 `A_You`**。除非用户在当前对话中明确要求换成别的作者名，否则生成文章时必须写死 `author: A_You`，不得随机生成、不得留空、不得沿用示例中的「作者名称」占位符。

### 头图（封面）动态生成规范

当文章 **没有现成封面** 或用户要求“生成头图/封面”时，Agent 应调用 `mify-image-gen` 技能动态生成一张与文章内容匹配的头图，然后写回 frontmatter 的 `cover` 字段。

**1. API Key 获取方式**（与微信凭证不同）

图像 API Key 已写入用户的 `~/.zshrc`，变量名为 **`MIFY_IMAGE_KEY`**（`sk-` 开头）。但 `mify-image-gen` 脚本本身 **不直接读环境变量**，它只读该技能的 `config/credentials.json`（字段 `image_api_key`）。因此首次使用前要把环境变量“灌”进技能配置一次：

```bash
# 加载 ~/.zshrc 得到 $MIFY_IMAGE_KEY，再写入技能凭证（幂等，重复执行无副作用）
source ~/.zshrc && python3 <mify-image-gen>/scripts/preflight.py --set-key "$MIFY_IMAGE_KEY"
```

- 校验：运行 `python3 <mify-image-gen>/scripts/preflight.py`，`ready:true` 即可生成；
- 若报 `image_api_key not configured`，说明还没灌入，执行上面那条命令；
- 若 `$MIFY_IMAGE_KEY` 为空，说明 `~/.zshrc` 未设置，向用户索要后 `--set-key sk-xxxx`。

> `<mify-image-gen>` = 该技能目录（通常 `~/.claude/skills/mify-image-gen` 或本仓库 `skills/mify-image-gen`）。

**2. 头图尺寸规范**

微信公众号封面大图（分享大图）标准比例约为 **2.35 : 1**，但要迁就不同模型支持的尺寸，统一按下表选 `--size`，生成后可在微信后台裁剪定位：

- **默认模型 `gemini-3-pro-image`（宽高比制）**：只接受固定比例集 `1:1 2:3 3:2 3:4 4:3 4:5 5:4 9:16 16:9`，**不支持 2.35:1**。头图用最接近的宽屏比例 **`--size 16:9`**（传 2.35:1 会报 `Invalid vertex_ai aspect ratio`）。
- **像素模型（volcengine / tongyi / GPT Image）**：传像素值 **`--size 1146x488`**（2.35:1）即可，脚本会按 provider 规则校验/适配。

**3. 从 MD 提取内容生成头图的流程**

1. 读取目标 Markdown，提取 `title` 与正文前几段的核心主题/关键词，归纳出一句画面描述（主体 + 场景 + 风格，中文即可）。
2. 调用图像生成（非 ASCII prompt 先写入 `<mify-image-gen>/cache/prompt_<ts>.txt` 再用 `--prompt-file`）：
    ```bash
    # 默认 gemini-3-pro-image：用 16:9
    python3 <mify-image-gen>/scripts/generate_image.py \
      --prompt-file <mify-image-gen>/cache/prompt_<ts>.txt \
      --size 16:9 \
      --output-dir <文章所在目录>
    # 像素模型（如 volcengine）：--model <pixel-model> --size 1146x488
    ```
3. 从返回 JSON 读取 `local_path`，将其写回文章 frontmatter 的 `cover` 字段（建议用绝对路径）。
4. 继续执行发布（`source ~/.zshrc && wenyan publish ...`），封面随草稿一起上传素材库。

### 核心参数说明

- `-f, --file`：**(必填)** Markdown 文件路径。
- `-t, --theme`：排版主题（默认 `default`）。
- `-h, --highlight`：代码高亮主题（默认 `solarized-light`）。
- `--no-mac-style`：禁用代码块 Mac 风格。

## 常用操作示例

> 以下示例统一遵守上面的「铁律」：用 `node <cli 绝对路径>` 显式调用，避免裸 `wenyan` 的静默失败。

### 1. 标准发布 (使用默认配置)
```bash
source ~/.zshrc && node /opt/homebrew/lib/node_modules/@wenyan-md/cli/dist/cli.js publish -f my-article.md
```

### 2. 指定内置主题与高亮发布
```bash
source ~/.zshrc && node /opt/homebrew/lib/node_modules/@wenyan-md/cli/dist/cli.js publish -f article.md -t orangeheart -h solarized-light
```

### 3. 列出所有可用主题
```bash
source ~/.zshrc && node /opt/homebrew/lib/node_modules/@wenyan-md/cli/dist/cli.js theme -l
```

## 故障排除 (Agent 专用)

- **IP 限制错误 (invalid ip)**：提醒用户将当前环境的出口 IP 加入微信后台的“IP 白名单”。
- **40001 invalid credential / "could get access_token by getStableAccessToken"（高频坑）**：本公众号启用了**固定 access_token（stable_token）**模式，CLI 默认走的普通 `/cgi-bin/token` 端点返回的凭证会被写接口拒绝（报 40001），而**读接口不报错**，极具迷惑性。两处要同时处理：
    1. **清掉 CLI 的本地 token 缓存**：`rm ~/.config/wenyan-md/token.json`（缓存里可能存着失效的旧 token，会一直被复用）。
    2. **让 CLI 改用 stable_token 端点**：patch 已安装包 `/opt/homebrew/lib/node_modules/@wenyan-md/cli/node_modules/@wenyan-md/core/dist/wechat.js` 的 `fetchAccessToken`，把 `GET /cgi-bin/token` 改为 `POST https://api.weixin.qq.com/cgi-bin/stable_token`（body: `{grant_type:"client_credential", appid, secret}`）。该 patch 在 `pnpm add -g` 升级后会被覆盖，升级后需重新打。
    - 快速判断：拿 stable_token 做一次写操作若报 40007（而非 40001），说明凭证已过认证、只是缺 media_id——证明必须用 stable_token。
- **AppID/Secret 错误**：确认命令是否已前置 `source ~/.zshrc &&`；若仍失败，检查 `~/.zshrc` 中 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 是否正确。
- **图片上传失败**：确认 Markdown 中的本地图片路径在当前目录中真实存在。
- **发布排版不符预期**：检查 YAML Frontmatter 是否符合规范。
