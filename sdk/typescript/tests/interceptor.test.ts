import { describe, it, expect } from "vitest";
import { ZodError } from "zod";
import {
  traceAgent,
  traceTool,
  getCurrentTraceContext,
  getCurrentTrace,
  Redactor,
  redactPayload,
  StepSchema,
} from "../src/index.js";

describe("TypeScript Interceptor SDK (@arc/sdk)", () => {
  it("test_ts_trace_tool_wrapper", async () => {
    async function processOrder(params: { orderId: string }) {
      return { status: "processed", id: params.orderId };
    }

    const wrappedTool = traceTool(processOrder, { mutating: true, name: "processOrder" });

    await traceAgent({ name: "order_agent" }, async () => {
      const result = await wrappedTool({ orderId: "8842" });

      expect(result).toEqual({ status: "processed", id: "8842" });

      const ctx = getCurrentTraceContext();
      expect(ctx).toBeDefined();
      expect(ctx?.steps.length).toBe(1);

      const step = ctx!.steps[0];
      expect(step.step_id).toBe(0);
      expect(step.kind).toBe("tool_call");
      expect(step.request?.tool).toBe("processOrder");
      expect(step.request?.mutating).toBe(true);
      expect(step.request?.args).toEqual({ orderId: "8842" });
      expect(step.response?.status).toBe("ok");
      expect(step.response?.body).toEqual({ status: "processed", id: "8842" });
      expect(typeof step.response?.latency_ms).toBe("number");
      expect(step.response!.latency_ms).toBeGreaterThanOrEqual(0);

      const ctf = getCurrentTrace();
      expect(ctf?.agent.name).toBe("order_agent");
      expect(ctf?.steps.length).toBe(1);
    });
  });

  it("test_ts_tier1_sanitizer_regex", () => {
    const redactor = new Redactor();

    const sampleArgs = {
      authToken: "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token123",
      secretKey: "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC3\n-----END PRIVATE KEY-----",
      normalField: "public_order_8842",
    };

    const redacted = redactor.redact(sampleArgs);

    expect(redacted.authToken).toContain("[REDACTED:bearer_token]");
    expect(redacted.secretKey).toBe("[REDACTED:private_key]");
    expect(redacted.normalField).toBe("public_order_8842");

    const directRedacted = redactPayload("Bearer my-secret-token-abc");
    expect(directRedacted).toBe("[REDACTED:bearer_token]");
  });

  it("test_ts_zod_schema_validation_failure", () => {
    const invalidStep = {
      step_id: -1, // Invalid: must be non-negative integer
      kind: "invalid_kind_type", // Invalid enum value
      t_virtual_ms: "invalid_string_latency", // Invalid: must be number
    };

    expect(() => {
      StepSchema.parse(invalidStep);
    }).toThrow(ZodError);

    try {
      StepSchema.parse(invalidStep);
    } catch (err) {
      expect(err).toBeInstanceOf(ZodError);
      const zodErr = err as ZodError;
      const issues = zodErr.issues.map((i) => i.path.join("."));
      expect(issues).toContain("step_id");
      expect(issues).toContain("kind");
      expect(issues).toContain("t_virtual_ms");
    }
  });

  it("test_ts_async_unhandled_rejection_safety", async () => {
    async function failingAsyncTool() {
      throw new Error("Async database connection timeout");
    }

    const wrappedFailingTool = traceTool(failingAsyncTool, {
      name: "failingAsyncTool",
      trapExceptions: true,
    });

    await traceAgent({ name: "resilient_agent" }, async () => {
      const result = await wrappedFailingTool();

      // Exception should be trapped and converted to error result object
      expect(result).toEqual({
        status: "error",
        error: "Async database connection timeout",
      });

      const ctx = getCurrentTraceContext();
      expect(ctx).toBeDefined();
      expect(ctx?.steps.length).toBe(1);

      const step = ctx!.steps[0];
      expect(step.kind).toBe("tool_call");
      expect(step.outcome).toBe("error");
      expect(step.response?.status).toBe("error");
      expect(step.response?.error).toBe("Async database connection timeout");
      expect(step.response?.traceback).toBeDefined();
      expect(step.forkable).toBe(false);
    });
  });

  it("test_ts_circular_reference_and_stacktrace_redaction", async () => {
    const redactor = new Redactor();
    const cyclicObj: any = { name: "test" };
    cyclicObj.self = cyclicObj;

    const redacted = redactor.redact(cyclicObj);
    expect(redacted.name).toBe("test");
    expect(redacted.self).toBe("[CIRCULAR]");

    async function toolWithSecretException() {
      throw new Error("Failed with secret: Bearer secret-token-123");
    }

    const wrappedTool = traceTool(toolWithSecretException, {
      name: "secretTool",
      trapExceptions: true,
    });

    await traceAgent({ name: "secret_agent" }, async () => {
      await wrappedTool();
      const ctx = getCurrentTraceContext();
      const step = ctx!.steps[0];
      expect(step.response?.error).toContain("[REDACTED:bearer_token]");
      expect(step.response?.traceback).toContain("[REDACTED:bearer_token]");
    });
  });
});
