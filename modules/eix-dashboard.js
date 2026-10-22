/*
 * E-IX 面板 for Surge
 *
 * 同一个文件有两种用法:
 * 1. http-request 脚本: 浏览器打开 E-IX 网页时, 从请求头里抓 authorization, 存进 $persistentStore
 * 2. generic 面板脚本: 用 token 请求 getSubscribe 和 info 两个接口, 生成面板内容
 *
 * 面板脚本的 argument 格式:
 *   host=ap.cdn.e-ix.com&icon=airplane.circle.fill&color=#355CC2&policy=按规则&timeout=10&token=xxx
 * token 必须放在最后, 因为 token 里可能带有 = 号
 */

const STORE_KEY = 'eix_dashboard_token';
// 抓取脚本每次运行都记一笔, 面板没有 token 时用来判断问题出在哪
const SEEN_KEY = 'eix_dashboard_seen';
const PLACEHOLDER_TOKEN = '留空则自动抓取';
const DEFAULT_HOST = 'ap.cdn.e-ix.com';
const DEFAULT_ICON = 'airplane.circle.fill';
const DEFAULT_COLOR = '#355CC2';
const ERROR_ICON = 'exclamationmark.triangle.fill';
const COLOR_WARN = '#FF9500';
const COLOR_DANGER = '#FF3B30';
const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 ' +
  '(KHTML, like Gecko) Version/18.0 Safari/605.1.15';

const args = parseArgs(typeof $argument === 'string' ? $argument : '');

if (typeof $request !== 'undefined') {
  captureToken();
} else {
  runPanel().catch((e) => {
    $done(errorPanel(`脚本出错: ${(e && e.message) || e}`));
  });
}

// ---------- 抓 token ----------

function captureToken() {
  const headers = $request.headers || {};
  let token = '';
  for (const k of Object.keys(headers)) {
    if (k.toLowerCase() === 'authorization') {
      token = String(headers[k] || '').trim();
      break;
    }
  }
  $persistentStore.write(JSON.stringify({ time: Date.now(), auth: !!token }), SEEN_KEY);
  if (token && token !== $persistentStore.read(STORE_KEY)) {
    $persistentStore.write(token, STORE_KEY);
    $notification.post('E-IX 面板', '已获取登录 token', '打开 Surge 的面板就能看到最新数据');
  }
  $done({});
}

// ---------- 面板 ----------

async function runPanel() {
  // 模块参数没被替换时, argument 里会留着 {{{NAME}}} 原样
  if (Object.keys(args).some((k) => String(args[k]).indexOf('{{{') >= 0)) {
    return $done(errorPanel('模块参数没有生效\n当前的 Surge 版本可能不支持模块参数, 请升级 Surge'));
  }

  const host = (args.host || DEFAULT_HOST).replace(/^https?:\/\//, '').replace(/\/+$/, '');
  const base = `https://${host}/api/v1/access`;

  let manual = cleanToken(args.token);
  const manualInvalid = !!manual && !looksLikeToken(manual);
  if (manualInvalid) manual = '';
  const captured = cleanToken($persistentStore.read(STORE_KEY));
  const tokens = [manual, captured].filter((t, i, a) => t && a.indexOf(t) === i);

  if (!tokens.length) {
    return $done(noticePanel(noTokenMessage(host, manualInvalid)));
  }

  // 手动填的 token 优先; 它失效时再试自动抓到的
  let lastError = null;
  for (const token of tokens) {
    try {
      const [sub, user] = await Promise.all([
        api(base, 'getSubscribe', token),
        api(base, 'info', token).catch(() => null),
      ]);
      return $done(render(sub, user));
    } catch (e) {
      lastError = e;
      if (!e.auth) break;
    }
  }

  if (lastError && lastError.auth) {
    return $done(noticePanel('登录已过期\n用浏览器重新打开 E-IX 网页登录一次即可'));
  }
  return $done(errorPanel(`请求失败: ${(lastError && lastError.message) || '未知错误'}`));
}

function api(base, path, token) {
  const timeout = Number(args.timeout) > 0 ? Number(args.timeout) : 10;
  const policy = (args.policy || '').trim();
  const options = {
    url: `${base}/${path}`,
    headers: {
      Accept: 'application/json',
      authorization: token,
      'Content-Language': 'zh-CN',
      'User-Agent': UA,
    },
    timeout,
  };
  if (policy && policy !== '按规则' && policy !== '#') options.policy = policy;

  return new Promise((resolve, reject) => {
    $httpClient.get(options, (error, response, data) => {
      if (error) return reject(makeError(String(error), 0, false));
      const status = (response && (response.status || response.statusCode)) || 0;
      let json = null;
      try {
        json = JSON.parse(data);
      } catch (_) {}
      if (status >= 200 && status < 300 && json && json.data) return resolve(json.data);
      // 后端返回 JSON 报错才算登录问题; 返回 HTML 的 403 多半是 Cloudflare 拦截
      const auth = (status === 401 || status === 403) && !!(json && json.message);
      let message = (json && json.message) || `HTTP ${status}`;
      if (!json && status === 403) message = 'HTTP 403, 可能被 Cloudflare 拦截, 试试换个 POLICY';
      reject(makeError(message, status, auth));
    });
  });
}

function render(sub, user) {
  if (!sub.plan_id || !sub.plan) {
    return noticePanel('还没有订阅套餐');
  }

  const used = (Number(sub.u) || 0) + (Number(sub.d) || 0);
  const total = Number(sub.transfer_enable) || 0;
  const remain = Math.max(0, total - used);
  const ratio = total ? Math.min(1, used / total) : 0;

  const lines = [];
  lines.push(`已用 ${fmtBytes(used)} / ${fmtBytes(total)} · ${(ratio * 100).toFixed(1)}%`);

  let remainLine = `剩余 ${fmtBytes(remain)}`;
  if (sub.reset_day === 0) remainLine += ' · 今天重置流量';
  else if (sub.reset_day !== null && sub.reset_day !== undefined) {
    remainLine += ` · ${sub.reset_day} 天后重置流量`;
  }
  lines.push(remainLine);

  // 和网页一致: 没有 expired_at 是长期有效, 7 天内算即将到期
  let state = 'active';
  if (sub.expired_at) {
    const days = Math.ceil((sub.expired_at - Date.now() / 1000) / 86400);
    if (days <= 0) {
      state = 'expired';
      lines.push(`已于 ${fmtDate(sub.expired_at)} 到期`);
    } else {
      if (days <= 7) state = 'expiringSoon';
      lines.push(`到期 ${fmtDate(sub.expired_at)} · 剩余 ${days} 天`);
    }
  } else {
    lines.push('到期 长期有效');
  }

  const extra = [];
  if (sub.device_limit) extra.push(`在线设备 ${sub.alive_ip || 0} / ${sub.device_limit}`);
  if (user && user.balance !== null && user.balance !== undefined) {
    extra.push(`余额 ¥${((Number(user.balance) || 0) / 100).toFixed(2)}`);
  }
  if (extra.length) lines.push(extra.join(' · '));

  lines.push(`更新于 ${fmtTime(new Date())}`);

  let color = args.color || DEFAULT_COLOR;
  let style = 'good';
  if (state === 'expired' || ratio >= 0.9) {
    color = COLOR_DANGER;
    style = 'error';
  } else if (state === 'expiringSoon' || ratio >= 0.8) {
    color = COLOR_WARN;
    style = 'alert';
  }

  const tag = { expired: ' · 已过期', expiringSoon: ' · 即将到期' }[state] || '';
  return {
    title: `${sub.plan.name || 'E-IX'}${tag}`,
    content: lines.join('\n'),
    icon: args.icon || DEFAULT_ICON,
    'icon-color': color,
    style,
  };
}

// ---------- 工具函数 ----------

function noticePanel(content) {
  return {
    title: 'E-IX',
    content,
    icon: ERROR_ICON,
    'icon-color': COLOR_WARN,
    style: 'alert',
  };
}

function errorPanel(content) {
  return {
    title: 'E-IX',
    content,
    icon: ERROR_ICON,
    'icon-color': COLOR_DANGER,
    style: 'error',
  };
}

function makeError(message, status, auth) {
  const e = new Error(message);
  e.status = status;
  e.auth = auth;
  return e;
}

function parseArgs(raw) {
  const out = {};
  let rest = raw;
  const m = /(?:^|&)token=/.exec(raw);
  if (m) {
    out.token = raw.slice(m.index + m[0].length);
    rest = raw.slice(0, m.index);
  }
  for (const pair of rest.split('&')) {
    if (!pair) continue;
    const i = pair.indexOf('=');
    if (i < 0) out[pair] = '';
    else out[pair.slice(0, i)] = pair.slice(i + 1);
  }
  return out;
}

// 去掉空白和各种引号; 模块参数里的中文占位文字当作没填
function cleanToken(value) {
  if (!value) return '';
  const t = String(value)
    .trim()
    .replace(/^["'“”‘’「」]+|["'“”‘’「」]+$/g, '')
    .trim();
  if (!t || t === '#' || t === PLACEHOLDER_TOKEN || /[一-鿿]/.test(t)) return '';
  return t;
}

function looksLikeToken(t) {
  return /^[\x21-\x7e ]+$/.test(t);
}

// 没有 token 时, 根据抓取脚本的记录说明卡在哪一步
function noTokenMessage(host, manualInvalid) {
  const lines = ['还没有登录 token'];
  if (manualInvalid) {
    lines.push('模块参数 TOKEN 里的内容不像 token, 检查是否多了空格或中文引号');
  }
  let seen = null;
  try {
    seen = JSON.parse($persistentStore.read(SEEN_KEY) || 'null');
  } catch (_) {}
  if (!seen || !seen.time) {
    lines.push(`抓取脚本还没运行过, 说明 Surge 没有解密 ${host} 的请求`);
    lines.push('检查 Surge 的 MitM 和脚本开关, 以及 MITM 主机名里有没有这个域名');
  } else if (!seen.auth) {
    lines.push(`抓取脚本 ${fmtDateTime(seen.time)} 运行过, 但请求里没有 token`);
    lines.push(`先在浏览器里打开 ${host} 并登录`);
  }
  lines.push('也可以在模块参数 TOKEN 里手动填写');
  return lines.join('\n');
}

function fmtBytes(n) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let v = Math.abs(n);
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${i === 0 ? v : v.toFixed(2)} ${units[i]}`;
}

function pad(n) {
  return String(n).padStart(2, '0');
}

function fmtDate(sec) {
  const d = new Date(sec * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function fmtTime(d) {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtDateTime(ms) {
  const d = new Date(ms);
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${fmtTime(d)}`;
}
