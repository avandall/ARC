import { z } from "zod";

export const StepKindSchema = z.enum([
  "model_decision",
  "tool_call",
  "human_gate",
  "external_event",
  "retry",
]);
export type StepKind = z.infer<typeof StepKindSchema>;

export const StepRequestSchema = z.object({
  tool: z.string().nullable().optional(),
  args: z.record(z.string(), z.any()).nullable().optional(),
  args_ref: z.string().nullable().optional(),
  idempotency_key: z.string().nullable().optional(),
  declared_mutating: z.boolean().nullable().optional(),
  mutating: z.boolean().nullable().optional(),
  scope: z.array(z.string()).nullable().optional(),
});
export type StepRequest = z.infer<typeof StepRequestSchema>;

export const StepResponseSchema = z.object({
  status: z.string().nullable().optional(),
  body: z.any().optional(),
  error: z.string().nullable().optional(),
  traceback: z.string().nullable().optional(),
  body_ref: z.string().nullable().optional(),
  latency_ms: z.number().nullable().optional(),
});
export type StepResponse = z.infer<typeof StepResponseSchema>;

export const StepSchema = z.object({
  step_id: z.number().int().nonnegative(),
  kind: StepKindSchema,
  t_virtual_ms: z.number().nonnegative(),
  parent_step: z.number().int().nullable().optional(),
  request: StepRequestSchema.nullable().optional(),
  response: StepResponseSchema.nullable().optional(),
  outcome: z.string().nullable().optional(),
  state_snapshot_ref: z.string().nullable().optional(),
  forkable: z.boolean().nullable().optional(),
  fork_reasons: z.array(z.string()).nullable().optional(),
});
export type Step = z.infer<typeof StepSchema>;

export const AgentMetaSchema = z.object({
  name: z.string(),
  version: z.string(),
  git_sha: z.string().nullable().optional(),
});
export type AgentMeta = z.infer<typeof AgentMetaSchema>;

export const ModelMetaSchema = z.object({
  provider: z.string(),
  model_id: z.string(),
  params: z.record(z.string(), z.any()).nullable().optional(),
});
export type ModelMeta = z.infer<typeof ModelMetaSchema>;

export const DeterminismLevelSchema = z.enum(["L0", "L1", "L2", "L3"]);
export type DeterminismLevel = z.infer<typeof DeterminismLevelSchema>;

export const OutcomeStatusSchema = z.enum([
  "completed",
  "agent_error",
  "escalated_to_human",
  "timeout",
  "aborted",
  "unknown",
]);
export type OutcomeStatus = z.infer<typeof OutcomeStatusSchema>;

export const StatusSourceSchema = z.enum([
  "human_triage",
  "reconciliation_webhook",
  "agent_self_report",
  "inferred_no_terminal_event",
]);
export type StatusSource = z.infer<typeof StatusSourceSchema>;

export const OutcomeSchema = z.object({
  status: OutcomeStatusSchema.optional(),
  outcome_status: OutcomeStatusSchema.optional(),
  status_source: StatusSourceSchema,
  cost_usd: z.number().nullable().optional(),
  wall_ms: z.number().nullable().optional(),
});
export type Outcome = z.infer<typeof OutcomeSchema>;

export const CtfSchema = z.object({
  trace_id: z.string().min(1),
  session_id: z.string().nullable().optional(),
  agent: AgentMetaSchema,
  model: ModelMetaSchema,
  started_at: z.string(),
  determinism_level: DeterminismLevelSchema,
  steps: z.array(StepSchema),
  effects: z.array(z.record(z.string(), z.any())).optional(),
  final_state_ref: z.string().nullable().optional(),
  outcome: OutcomeSchema,
  redaction_key_id: z.string().nullable().optional(),
});
export type CtfTrace = z.infer<typeof CtfSchema>;
