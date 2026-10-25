---
name: "apply-wechat-custom-theme"
description: "AI-ready skill to test, register, and publish Markdown articles to WeChat Official Accounts using a local custom CSS theme via Wenyan CLI."
---

# 微信公众号自定义主题应用工具 (WeChat Custom Theme Applier)

这是一个专门为 AI Agent 设计的技能，用于将本地生成的自定义 CSS 主题应用到 Markdown 文章中。它支持通过 `wenyan-cli` 进行本地预览、主题注册以及一键推送到微信公众号草稿箱。

## 前置要求

- **环境配置**：必须设置 `WECHAT_APP_ID` 和 `WECHAT_APP_SECRET` 环境变量。这两个凭证已写入用户的 `~/.zshrc`，因此 **每一条调用 `wenyan` 发布/上传的命令都必须在同一行前置 `source ~/.zshrc &&`** 来加载凭证（Agent 的每次 shell 调用都是独立进程，不会继承上一次的环境变量）。
- **依赖工具**：已安装 `wenyan-cli` (`pnpm add -g @wenyan-md/cli`)。
- **必要文件**：本地已存在 Markdown 文件 (`.md`) 和 CSS 主题文件 (`.css`)。

## 核心能力

- **本地测试渲染**：在发布前验证 CSS 样式的正确性。
- **一键发布草稿**：直接应用本地 CSS 将文章推送到公众号草稿箱。
- **主题持久化**：将优秀的自定义主题注册到 `wenyan-cli` 主题库中，方便后续调用。

## AI Agent 指令指南：工作流 SOP

当用户要求“应用生成的 `xxx.css` 并发布 `yyy.md`”时，Agent **必须** 遵循以下标准操作流程：

### Step 1: 测试渲染 (Render Test) [强制]

在正式发布前，必须先进行模拟渲染，以确保 CSS 语法正确且文件路径有效。

- **命令**：
    ```bash
    wenyan render -f <markdown_file_path> -c <css_file_path>
    ```
- **验证**：如果输出包含 `<div id="wenyan">` 的 HTML 字符串且无报错，则说明正常。

### Step 1.5: 生成头图 (Generate Cover) [按需]

若文章 frontmatter 缺少 `cover`，或用户要求“生成头图/封面”，调用 `mify-image-gen` 技能动态生成：

- **API Key**：图像 Key 已写入 `~/.zshrc` 的 **`MIFY_IMAGE_KEY`**（`sk-` 开头），但脚本只读技能的 `config/credentials.json`（字段 `image_api_key`），不直接读环境变量。首次使用前先把环境变量灌入技能配置（幂等）：
    ```bash
    source ~/.zshrc && python3 <mify-image-gen>/scripts/preflight.py --set-key "$MIFY_IMAGE_KEY"
    ```
    之后运行 `scripts/preflight.py` 校验 `ready:true`；若 `$MIFY_IMAGE_KEY` 为空则向用户索要后 `--set-key sk-xxxx`。
- **尺寸**：微信封面大图比例约 **2.35:1**。默认模型 `gemini-3-pro-image` 只支持固定比例集，**不支持 2.35:1** → 用最接近的 **`--size 16:9`**；若改用像素模型（volcengine 等）则 `--size 1146x488`。
- **内容来源**：从 Markdown 的 `title` 与正文前几段提炼一句画面描述作为 prompt（非 ASCII 先写 `cache/prompt_<ts>.txt` 再 `--prompt-file`）。
- **命令**：
    ```bash
    python3 <mify-image-gen>/scripts/generate_image.py \
      --prompt-file <mify-image-gen>/cache/prompt_<ts>.txt \
      --size 16:9 --output-dir <文章所在目录>
    ```
- 从返回 JSON 的 `local_path` 写回文章 frontmatter 的 `cover` 字段（建议绝对路径）。

### Step 2: 正式发布 (Publish to Draft)

测试通过后，使用该 CSS 文件将文章推送到微信公众号草稿箱（发布命令须加载凭证）。

- **命令**：
    ```bash
    source ~/.zshrc && wenyan publish -f <markdown_file_path> -c <css_file_path>
    ```
- **可选参数**：
    - `--no-mac-style`：禁用代码块 Mac 风格窗口。
    - `-h <highlight_theme>`：指定代码高亮主题（如 `atom-one-dark`）。

### Step 3: 注册主题 (Register Theme) [按需]

如果用户表示需要长期使用该主题，应将其注册到本地主题库。

- **命令**：
    ```bash
    wenyan theme --add --name <theme_name> --path <css_file_path>
    ```
- **后续调用**：注册后可直接使用 `-t <theme_name>` 参数发布。

## 故障排除 (Agent 专用)

- **文件不存在**：检查 `ENOENT` 报错，确认 Markdown 或 CSS 文件路径是否正确。
- **样式未生效**：检查 CSS 选择器是否缺少 `#wenyan` 前缀。
- **凭证错误**：如果微信 API 返回 `invalid credential`，先确认发布命令已前置 `source ~/.zshrc &&`；若仍失败，再检查 `~/.zshrc` 中的 `WECHAT_APP_ID` 和 `WECHAT_APP_SECRET`。
