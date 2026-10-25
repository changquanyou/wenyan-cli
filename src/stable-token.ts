import { credentialStore, wechatPublisher } from "@wenyan-md/core/wrapper";

const STABLE_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/stable_token";

/**
 * 解析微信 AppID / AppSecret。
 * 优先级：命令行参数 > 环境变量 (WECHAT_APP_ID / WECHAT_APP_SECRET) > 本地凭据库。
 * 与 @wenyan-md/core 内部的 getAppIdAndSecret 保持一致（该函数未导出，这里复刻其解析顺序）。
 */
async function resolveWechatCredential(appIdArg?: string): Promise<{ appId: string; appSecret: string }> {
    const envAppId = process.env.WECHAT_APP_ID;
    const envAppSecret = process.env.WECHAT_APP_SECRET;

    // 未指定 appId 时，若环境变量齐全则直接使用
    if (!appIdArg && envAppId && envAppSecret) {
        return { appId: envAppId, appSecret: envAppSecret };
    }

    const appId = appIdArg || envAppId;
    if (!appId) {
        throw new Error(
            "无法确定 WeChat AppID：请通过 --app-id 传入，或设置环境变量 WECHAT_APP_ID，或先用 `wenyan credential --set` 保存凭据。"
        );
    }

    // 若有 appId 且环境变量 secret 齐全（且 appId 与环境一致或未显式指定别名），优先环境变量
    if (envAppSecret && (appId === envAppId)) {
        return { appId, appSecret: envAppSecret };
    }

    // 否则回退到本地凭据库（支持 appId 或 alias）
    const credential = await credentialStore.getWechatCredential(appId);
    if (!credential?.appSecret) {
        throw new Error(
            `未找到 AppID [${appId}] 的 AppSecret：请设置 WECHAT_APP_SECRET，或先用 \`wenyan credential --set\` 保存凭据。`
        );
    }
    return { appId: credential.appId, appSecret: credential.appSecret };
}

/**
 * 为启用了「固定 access_token（stable_token）」模式的公众号获取并导入凭证。
 *
 * 背景：部分公众号在后台开启了稳定版接口调用凭据，此时普通 `/cgi-bin/token`
 * 端点返回的 token 会被写接口（草稿/素材）拒绝并报 40001，而读接口却正常，极具迷惑性。
 * 本函数改用 `/cgi-bin/stable_token` 取得正确凭证，并通过 wechatPublisher.setExternalToken
 * 注入 CLI 的 token 缓存，使后续发布直接复用，无需改动 @wenyan-md/core（升级不丢）。
 */
export async function primeStableToken(appIdArg?: string): Promise<void> {
    const { appId, appSecret } = await resolveWechatCredential(appIdArg);

    const res = await fetch(STABLE_TOKEN_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            grant_type: "client_credential",
            appid: appId,
            secret: appSecret,
            force_refresh: false,
        }),
    });

    if (!res.ok) {
        throw new Error(`获取 stable_token 失败：HTTP ${res.status} ${await res.text()}`);
    }

    const data: { access_token?: string; errcode?: number; errmsg?: string } = await res.json();
    if (!data.access_token) {
        throw new Error(`获取 stable_token 失败：${data.errcode ?? ""} ${data.errmsg ?? JSON.stringify(data)}`);
    }

    // 导入为外部 token（expireAt=-1，Wenyan 不再自动刷新；stable_token 自身在微信侧仍会续期）
    await wechatPublisher.setExternalToken(appId, data.access_token);
}
