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

> ⛓️ **标题不要重复（高频视觉 bug）**：微信文章标题由 frontmatter 的 `title` 提供，并会自动显示在文章顶部。因此正文**不要再写一个和标题相同的 `# 一级标题 (H1)`**，否则读者会在文章开头看到**标题出现两次**。正文直接从引言 `>` 或第一个 `##` 二级标题开始。若正文确实需要一个与标题不同的大标题，才用 `#`。

### 正文结构约束（避免常见排版问题）

- **不要重复 H1**：见上。正文首个标题从 `##` 开始。
- **mermaid 图会被正常渲染**：wenyan 会把 ```mermaid 代码块渲染成 **SVG 矢量图**（不是代码块），流程图/时序图都支持。可放心用 mermaid 画架构图，无需自己转图片。
- **本地图片用相对路径**：相对 Markdown 文件所在目录，如 `assets/<slug>/fig1.png`。发布时会自动上传到微信素材库并替换为 `mmbiz.qpic.cn` 地址。

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

## 发布后二次核验（务必做，含图片真伪）

退出码 0 ≠ 真的成功。每次发布后用 stable_token 换 access_token，调 `cgi-bin/draft/batchget`（`no_content:0`）核验：

```bash
sleep 3; source ~/.zshrc
TOKEN=$(curl -s "https://api.weixin.qq.com/cgi-bin/stable_token" -X POST \
  -d "{\"grant_type\":\"client_credential\",\"appid\":\"$WECHAT_APP_ID\",\"secret\":\"$WECHAT_APP_SECRET\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s "https://api.weixin.qq.com/cgi-bin/draft/batchget?access_token=$TOKEN" \
  -X POST -d '{"offset":0,"count":1,"no_content":0}' | python3 -I -c "
import sys,json,re,urllib.request
d=json.load(sys.stdin); it=d['item'][0]['content']['news_item'][0]
print('TITLE:', it['title']); print('AUTHOR:', it.get('author'))
imgs=re.findall(r'<img[^>]*?src=\"([^\"]*)\"', it['content'])
print('IMAGES:', len(imgs), '| MERMAID SVG:', it['content'].count('<svg'))
# 实测抽查一张图是否真的可访问（带微信 referer）
if imgs:
    req=urllib.request.Request(imgs[len(imgs)//2], headers={'Referer':'https://mp.weixin.qq.com/'})
    try: r=urllib.request.urlopen(req,timeout=15); print('IMG OK:', r.status, r.headers.get('content-type'))
    except Exception as e: print('IMG ERR:', e)
"
```

### ⚠️ 草稿编辑器里「图片显示破图」≠ 上传失败（高频误判）

微信草稿**编辑页面**对 `mmbiz.qpic.cn` 图片有防盗链（referer 校验），在 PC 编辑态下**经常不渲染、显示破图图标**——但图片其实已成功上传、在手机预览和正式发布页都正常。

- **判断真伪**：用上面脚本抽查一张图，带 `Referer: https://mp.weixin.qq.com/` 请求若返回 `HTTP 200 image/*`，就是好的，编辑器破图只是预览限制。
- **让用户最终确认**：请用户在后台点「预览」发到手机查看，手机上图片会正常显示。
- **不要**因为编辑器破图就反复重传或判定失败。

## 故障排除 (Agent 专用)

- **40164 invalid ip / invalid ip ... not in whitelist（会阻断发布，Agent 无法自行解决）**：当前出口 IP 不在公众号 IP 白名单里。**这是写接口硬性拦截，Agent 侧无论怎么重试都无用**，必须用户在微信后台操作：
    - 后台路径：「设置与开发」→「基本配置」→「IP 白名单」，把报错里给出的 IP（如 `1.202.162.23`）加进去保存。
    - 常见触发：换了网络、VPN、或出口 IP 变动。IP 可能几分钟后又变，必要时提醒用户加整段或用固定出口。
    - 报错里已经带了需要加白的 IP，直接把那个 IP 原样告诉用户即可，不用自己查。
    - 加白后再重试发布命令即可（无需改文章）。
- **40001 invalid credential / 42001 access_token expired（高频坑）**：本公众号启用了**固定 access_token（stable_token）**模式。CLI 可能缓存了一个失效的旧 token，导致写接口报 40001/42001，而读接口不报错，极具迷惑性。
    - **✅ 实测最稳的做法（优先用这个）**：发布命令前**先删掉缓存 token**再执行，几乎可解掉所有凭证类报错：
        ```bash
        rm -f ~/.config/wenyan-md/token.json
        source ~/.zshrc && node /opt/homebrew/lib/node_modules/@wenyan-md/cli/dist/cli.js publish -f 文件.md -t orangeheart
        ```
      > 本仓库的实践：每次发布前都先 `rm -f ~/.config/wenyan-md/token.json`，让 CLI 重新取凭证，比依赖 `--stable-token` 更可靠。
    - **关于 `--stable-token`**：部分已安装版本**并不支持**该选项，会直接报 `error: unknown option '--stable-token'`。遇到就去掉它、改用上面的「删缓存 + 重试」。不要反复尝试一个不存在的选项。
    - **快速判断**：拿 stable_token 做一次写操作若报 40007（而非 40001），说明凭证已过认证、只是缺 media_id——证明走 stable_token 路径是对的。

- **命令输出里的 `compdef:153: _comps: assignment to invalid subscript range` 噪声**：这是 `source ~/.zshrc` 触发的 zsh 补全告警，**与发布无关，可忽略**。看发布结果时用 `| grep -viE "compdef|_comps"` 过滤掉，只认 `发布成功，Media ID: xxxx` 这类真实回执。
- **AppID/Secret 错误**：确认命令是否已前置 `source ~/.zshrc &&`；若仍失败，检查 `~/.zshrc` 中 `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 是否正确。
- **图片上传失败**：确认 Markdown 中的本地图片路径在当前目录中真实存在。
- **发布排版不符预期**：检查 YAML Frontmatter 是否符合规范。
