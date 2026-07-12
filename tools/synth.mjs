#!/usr/bin/env node
// tools/synth.mjs — reharness LLM 合成器 (Pi agent core SDK)
// 用法: node tools/synth.mjs --prompt-file <path> --out <out.c> [--model provider/id] [--model-file <models.json>] [--auth-file <auth.json>]
//
// 从 prompt 文件读合成请求(.ris/.dspec/.bind/.facts + 约束), 用 Pi createAgentSession
// 调 LLM, 累积 assistant 文本, 提取第一个 ```c 代码块, 写到 --out。
// 失败: 退出码非 0, 错误写到 stderr。
//
// 这是 reharness 合成层的 TypeScript 实现; 前端 libclang 提取器仍为 Python。

import { resolve } from "node:path";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import {
  AuthStorage,
  ModelRegistry,
  SessionManager,
  createAgentSession,
} from "@earendil-works/pi-coding-agent";

// ── 参数解析 ────────────────────────────────────────────────
function parseArgs(argv) {
  const a = {};
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i];
    const v = argv[++i];
    if (k === "--prompt-file") a.promptFile = v;
    else if (k === "--out") a.out = v;
    else if (k === "--model") a.model = v; // provider/id
    else if (k === "--model-file") a.modelFile = v;
    else if (k === "--auth-file") a.authFile = v;
    else if (k === "--timeout") a.timeout = parseInt(v, 10); // 秒
    else { i--; }
  }
  if (!a.promptFile || !a.out) {
    console.error("用法: synth.mjs --prompt-file <path> --out <out.c> [--model provider/id]");
    process.exit(2);
  }
  return a;
}

// ── 从 LLM 文本提取第一个 ```c 代码块 ───────────────────────
function extractC(text) {
  const m = text.match(/```c\n([\s\S]*?)\n```/);
  if (m) return m[1];
  // 宽松: 任意 ``` 围栏
  const m2 = text.match(/```\n([\s\S]*?)\n```/);
  if (m2) return m2[1];
  // 无围栏但像 C
  if (/#include\s*[<"]/.test(text) || /static\s+\w+/.test(text)) return text.trim();
  return null;
}

const args = parseArgs(process.argv);

// ── 读 prompt ───────────────────────────────────────────────
let promptText;
try {
  promptText = readFileSync(args.promptFile, "utf-8");
} catch (e) {
  console.error(`读 prompt 失败: ${e.message}`);
  process.exit(2);
}

// ── auth + model registry ───────────────────────────────────
const authStorage = args.authFile
  ? AuthStorage.create(resolve(args.authFile))
  : AuthStorage.create();
const modelRegistry = args.modelFile
  ? ModelRegistry.create(authStorage, resolve(args.modelFile))
  : ModelRegistry.create(authStorage);

// 选模型: --model provider/id > 配置里第一个可用
let model = undefined;
if (args.model) {
  const [provider, ...rest] = args.model.split("/");
  const id = rest.join("/");
  model = modelRegistry.find(provider, id);
  if (!model) {
    console.error(`未找到模型 ${args.model}; 可用: ${(await modelRegistry.getAvailable()).map((m) => `${m.provider}/${m.id}`).join(", ")}`);
    process.exit(3);
  }
} else {
  const avail = await modelRegistry.getAvailable();
  if (avail.length === 0) {
    console.error("没有可用模型 (检查 ~/.pi/agent/models.json 的 apiKey)");
    process.exit(3);
  }
  model = avail[0];
}
process.stderr.write(`[synth] model: ${model.provider}/${model.id}\n`);

// ── 超时保护 ────────────────────────────────────────────────
const timeoutSec = args.timeout ?? 600;
const timer = setTimeout(() => {
  console.error(`[synth] 超时 ${timeoutSec}s`);
  process.exit(124);
}, timeoutSec * 1000);

// ── 跑合成 ──────────────────────────────────────────────────
let buf = "";
const { session } = await createAgentSession({
  model,
  sessionManager: SessionManager.inMemory(),
  authStorage,
  modelRegistry,
});

session.subscribe((event) => {
  if (event.type === "message_update" && event.assistantMessageEvent?.type === "text_delta") {
    buf += event.assistantMessageEvent.delta;
  }
});

try {
  await session.prompt(promptText);
} catch (e) {
  console.error(`[synth] prompt 失败: ${e.message}`);
  process.exit(4);
} finally {
  session.dispose();
  clearTimeout(timer);
}

const code = extractC(buf);
if (!code || code.length < 50) {
  console.error(`[synth] 未提取到有效 C 代码块 (输出 ${buf.length} 字节)`);
  // 把原始输出写到 .raw 便于排查
  writeFileSync(args.out + ".raw", buf);
  process.exit(5);
}

writeFileSync(args.out, code + "\n");
process.stderr.write(`[synth] 已写 ${args.out} (${code.length} 字节)\n`);
process.exit(0);
