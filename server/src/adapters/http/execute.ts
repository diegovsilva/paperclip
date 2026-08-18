import type { AdapterExecutionContext, AdapterExecutionResult } from "../types.js";
import { asString, asNumber, parseObject } from "../utils.js";

export async function execute(ctx: AdapterExecutionContext): Promise<AdapterExecutionResult> {
  const { config, runId, agent, context } = ctx;
  const url = asString(config.url, "");
  if (!url) throw new Error("HTTP adapter missing url");

  const method = asString(config.method, "POST");
  const timeoutMs = asNumber(config.timeoutMs, 0);
  const headers = parseObject(config.headers) as Record<string, string>;
  const payloadTemplate = parseObject(config.payloadTemplate);
  const body = { ...payloadTemplate, agentId: agent.id, runId, context };

  const controller = new AbortController();
  const timer = timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null;

  try {
    const res = await fetch(url, {
      method,
      headers: {
        "content-type": "application/json",
        ...headers,
      },
      body: JSON.stringify(body),
      ...(timer ? { signal: controller.signal } : {}),
    });

    if (!res.ok) {
      throw new Error(`HTTP invoke failed with status ${res.status}`);
    }

    return {
      exitCode: 0,
      signal: null,
      timedOut: false,
      // Sem `summary` aqui de propósito: agentes http são fire-and-forget (o worker do
      // agente responde 2xx e processa em background) — o core marca a run como
      // concluída assim que ESTA chamada recebe 2xx, muito antes do worker ter tido
      // chance de postar seu próprio comentário no issue. Se `summary` fosse setado
      // (era `HTTP ${method} ${url}`), heartbeat.ts posta esse texto como se fosse "o
      // resultado" da run (buildHeartbeatRunIssueComment em heartbeat-run-summary.ts) —
      // confirmado num teste real: toda invocação virava um comentário ruidoso
      // "HTTP POST http://harness:8000/webhook/head" na timeline do ticket, antes (e
      // sobrepondo) o comentário real do agente. A URL configurada não é um resultado
      // apresentável de qualquer forma — é config estática, igual em toda run do agente.
      summary: null,
    };
  } catch (err) {
    if (timer && err instanceof Error && err.name === "AbortError") {
      return {
        exitCode: null,
        signal: null,
        timedOut: true,
        errorMessage: `HTTP ${method} ${url} timed out after ${timeoutMs}ms`,
        errorCode: "timeout",
      };
    }
    throw err;
  } finally {
    if (timer) clearTimeout(timer);
  }
}
