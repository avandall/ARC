import { AsyncLocalStorage } from "async_hooks";
import { performance } from "perf_hooks";
import { randomUUID } from "crypto";
import { redactPayload, Redactor } from "./sanitizer.js";
import { CtfTrace, Step } from "./schemas.js";

export interface TraceContextOptions {
  traceId?: string;
  agentName?: string;
  agentVersion?: string;
  modelProvider?: string;
  modelId?: string;
}

export class TraceContext {
  public traceId: string;
  public agentName: string;
  public agentVersion: string;
  public modelProvider: string;
  public modelId: string;
  public startedAt: string;
  public startPerf: number;
  public steps: Step[] = [];
  public effects: Record<string, any>[] = [];
  public outcomeStatus: string = "completed";
  public statusSource: string = "agent_self_report";

  constructor(options: TraceContextOptions = {}) {
    this.traceId = options.traceId || randomUUID();
    this.agentName = options.agentName || "default_agent";
    this.agentVersion = options.agentVersion || "1.0.0";
    this.modelProvider = options.modelProvider || "openai";
    this.modelId = options.modelId || "gpt-4o";
    this.startedAt = new Date().toISOString();
    this.startPerf = performance.now();
  }

  public addStep(step: Step): void {
    this.steps.push(step);
  }

  public toCtfDict(): Record<string, any> {
    const wallMs = Math.round((performance.now() - this.startPerf) * 100) / 100;
    return {
      trace_id: this.traceId,
      session_id: null,
      agent: {
        name: this.agentName,
        version: this.agentVersion,
        git_sha: null,
      },
      model: {
        provider: this.modelProvider,
        model_id: this.modelId,
        params: null,
      },
      started_at: this.startedAt,
      determinism_level: "L1",
      steps: this.steps,
      effects: this.effects,
      final_state_ref: null,
      outcome: {
        status: this.outcomeStatus,
        outcome_status: this.outcomeStatus,
        status_source: this.statusSource,
        cost_usd: 0.0,
        wall_ms: wallMs,
      },
      redaction_key_id: "tier1_default",
    };
  }
}

const asyncLocalStorage = new AsyncLocalStorage<TraceContext>();

export function getCurrentTraceContext(): TraceContext | undefined {
  return asyncLocalStorage.getStore();
}

export function getCurrentTrace(): Record<string, any> | null {
  const ctx = getCurrentTraceContext();
  if (!ctx) return null;
  return ctx.toCtfDict();
}

export interface TraceAgentOptions {
  name?: string;
  version?: string;
  traceId?: string;
  modelProvider?: string;
  modelId?: string;
}

export function traceAgent<T>(
  options: TraceAgentOptions,
  fn: (ctx: TraceContext) => Promise<T> | T
): Promise<T> {
  const ctx = new TraceContext({
    traceId: options.traceId,
    agentName: options.name || "default_agent",
    agentVersion: options.version || "1.0.0",
    modelProvider: options.modelProvider || "openai",
    modelId: options.modelId || "gpt-4o",
  });

  return asyncLocalStorage.run(ctx, async () => {
    try {
      const res = await fn(ctx);
      return res;
    } catch (err) {
      ctx.outcomeStatus = "agent_error";
      throw err;
    }
  });
}

export interface TraceToolOptions {
  name?: string;
  mutating?: boolean;
  trapExceptions?: boolean;
  redactor?: Redactor;
}

export function traceTool<TArgs extends any[], TRet>(
  toolFn: (...args: TArgs) => Promise<TRet> | TRet,
  options: TraceToolOptions = {}
): (...args: TArgs) => Promise<TRet> {
  const toolName = options.name || toolFn.name || "anonymous_tool";
  const trapExceptions = options.trapExceptions ?? true;

  return async (...args: TArgs): Promise<TRet> => {
    const ctx = getCurrentTraceContext();
    const stepId = ctx ? ctx.steps.length : 0;
    const tVirtualMs = ctx
      ? Math.round((performance.now() - ctx.startPerf) * 100) / 100
      : 0.0;

    let sanitizedArgs: Record<string, any>;
    if (args.length === 1 && typeof args[0] === "object" && args[0] !== null) {
      sanitizedArgs = redactPayload(args[0]);
    } else {
      sanitizedArgs = { args: redactPayload(args) };
    }

    const t0 = performance.now();

    try {
      const result = await toolFn(...args);
      const latencyMs = Math.round((performance.now() - t0) * 1000) / 1000;
      const sanitizedResult = redactPayload(result);

      const stepDict: Step = {
        step_id: stepId,
        kind: "tool_call",
        t_virtual_ms: tVirtualMs,
        parent_step: null,
        request: {
          tool: toolName,
          args: sanitizedArgs,
          args_ref: null,
          idempotency_key: null,
          declared_mutating: options.mutating ?? null,
          mutating: options.mutating ?? null,
          scope: null,
        },
        response: {
          status: "ok",
          body: sanitizedResult,
          error: null,
          traceback: null,
          body_ref: null,
          latency_ms: latencyMs,
        },
        outcome: "success",
        forkable: true,
        fork_reasons: null,
      };

      if (ctx) {
        ctx.addStep(stepDict);
      }

      return result;
    } catch (err: any) {
      const latencyMs = Math.round((performance.now() - t0) * 1000) / 1000;
      const errorMessage = err instanceof Error ? err.message : String(err);
      const stackTrace = err instanceof Error ? err.stack || String(err) : String(err);
      const sanitizedError = redactPayload(errorMessage);
      const sanitizedStackTrace = redactPayload(stackTrace);

      const stepDict: Step = {
        step_id: stepId,
        kind: "tool_call",
        t_virtual_ms: tVirtualMs,
        parent_step: null,
        request: {
          tool: toolName,
          args: sanitizedArgs,
          args_ref: null,
          idempotency_key: null,
          declared_mutating: options.mutating ?? null,
          mutating: options.mutating ?? null,
          scope: null,
        },
        response: {
          status: "error",
          body: null,
          error: sanitizedError,
          traceback: sanitizedStackTrace,
          body_ref: null,
          latency_ms: latencyMs,
        },
        outcome: "error",
        forkable: false,
        fork_reasons: null,
      };

      if (ctx) {
        ctx.addStep(stepDict);
      }

      if (trapExceptions) {
        return {
          status: "error",
          error: errorMessage,
        } as unknown as TRet;
      }

      throw err;
    }
  };
}
