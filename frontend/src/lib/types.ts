// API types mirroring backend/app/schemas/api.py

export type Role = "support_operator" | "reviewer" | "senior_reviewer" | "administrator";

export type WorkflowState =
  | "CREATED"
  | "ANALYZING"
  | "VERIFYING"
  | "POLICY_CHECK"
  | "AWAITING_APPROVAL"
  | "APPROVED"
  | "EXECUTING"
  | "COMPLETED"
  | "REJECTED"
  | "FAILED"
  | "CANCELLED";

export interface User {
  id: string;
  username: string;
  display_name: string;
  role: Role;
  permissions: string[];
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: User;
}

export interface Customer {
  id: string;
  name: string;
  email: string;
  city: string;
  tier: string;
}

export interface Order {
  id: string;
  customer_id: string;
  product_id: string;
  product_name: string;
  quantity: number;
  total_paise: number;
  refunded_paise: number;
  refundable_paise: number;
  status: string;
  placed_at: string;
  delivered_at: string | null;
}

export interface Approval {
  id: string;
  workflow_id: string;
  action: string;
  order_id: string | null;
  amount_paise: number;
  currency: string;
  required_role: string;
  reason: string;
  details: Record<string, unknown> | null;
  status: "pending" | "approved" | "rejected" | "expired" | "invalidated";
  auto: boolean;
  workflow_state_at_request: string;
  requested_at: string;
  expires_at: string | null;
  decided_by: string | null;
  decided_by_name: string | null;
  decided_by_role: string | null;
  decided_at: string | null;
  comment: string | null;
  customer_id: string | null;
  customer_name: string | null;
}

export interface Execution {
  id: string;
  workflow_id: string;
  order_id: string;
  approval_id: string;
  amount_paise: number;
  currency: string;
  idempotency_key: string;
  status: string;
  gateway_reference: string;
  executed_by: string;
  executed_at: string;
}

export interface ProposedToolCall {
  tool: string;
  arguments: Record<string, unknown>;
  rationale: string;
}

export interface Interpretation {
  intent: string;
  order_id: string | null;
  requested_amount_paise: number | null;
  reason_category: string;
  summary: string;
  confidence: number;
  conflicting_statements: string[];
  suspected_injection: boolean;
  proposed_tool_calls: ProposedToolCall[];
  provider: string;
  model: string | null;
  latency_ms: number | null;
}

export interface Verification {
  order_id: string | null;
  amount_paise: number | null;
  requested_amount_paise: number | null;
  refundable_paise: number | null;
  flags: string[];
  discrepancies: string[];
  requires_human_review: boolean;
  review_reason: string | null;
  verified_at: string;
}

export interface PolicyRule {
  rule: string;
  passed: boolean;
  detail: string;
}

export interface PolicyDecision {
  eligible: boolean;
  tier: string;
  required_role: string | null;
  amount_paise: number;
  refundable_paise: number;
  reasons: string[];
  rules: PolicyRule[];
  policy_name: string;
  policy_version: number;
  exception_override_available: boolean;
}

export interface SimulationConfig {
  fail_tool?: string | null;
  fail_times?: number;
  fail_mode?: "transient" | "permanent";
  gateway_fail_times?: number;
  db_fail_times?: number;
  interrupt_after?: string | null;
  interrupt_armed?: boolean;
  provider_fault?: "misread_amount" | "wrong_intent" | "low_confidence" | null;
  notes?: string | null;
}

export interface Workflow {
  id: string;
  customer_id: string;
  customer_name: string | null;
  order_id: string | null;
  message: string;
  state: WorkflowState;
  created_by: string | null;
  client_request_id: string | null;
  provider_name: string;
  approval_id: string | null;
  failure_reason: string | null;
  rejection_reason: string | null;
  resumable: boolean;
  resume_count: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  interpretation: Interpretation | null;
  verification: Verification | null;
  policy_decision: PolicyDecision | null;
  checkpoint: { step?: string; context?: Record<string, unknown>; saved_at?: string; resume_target?: string } | null;
  simulation: SimulationConfig | null;
  approvals: Approval[];
  execution: Execution | null;
  interrupted: boolean;
}

export interface WorkflowList {
  items: Workflow[];
  total: number;
}

export interface AuditEvent {
  id: number;
  workflow_id: string | null;
  timestamp: string;
  category: string;
  event_type: string;
  severity: "info" | "warning" | "error";
  actor_type: string;
  actor_id: string;
  tool_name: string | null;
  duration_ms: number | null;
  authorization_outcome: string;
  workflow_state: string | null;
  message: string;
  payload: Record<string, unknown> | null;
}

export interface EventList {
  items: AuditEvent[];
  total: number;
}

export interface Metrics {
  total_workflows: number;
  completed_workflows: number;
  pending_approvals: number;
  failed_workflows: number;
  rejected_workflows: number;
  awaiting_approval_workflows: number;
  blocked_unauthorized_actions: number;
  injection_attempts_detected: number;
  average_workflow_duration_ms: number | null;
  total_refunded_paise: number;
  workflows_by_state: Record<string, number>;
  workflows_per_day: { date: string; total: number; completed: number; rejected: number; failed: number; awaiting_approval: number }[];
  policy_outcomes: Record<string, number>;
  generated_at: string;
}

export interface Scenario {
  key: string;
  title: string;
  category: string;
  description: string;
  initial_request: string;
  expected_behavior: string;
  explanation: string;
}

export interface Assertion {
  name: string;
  passed: boolean;
  detail: string;
}

export interface ScenarioResult {
  scenario: Scenario;
  run_id: string;
  passed: boolean;
  started_at: string;
  duration_ms: number;
  observed_behavior: string;
  assertions: Assertion[];
  workflow_ids: string[];
  events: AuditEvent[];
}

export interface LabRun {
  id: string;
  scenario_key: string;
  passed: boolean;
  run_by: string | null;
  started_at: string;
  duration_ms: number;
  result: Record<string, unknown>;
}

export interface ExampleRequest {
  key: string;
  title: string;
  customer_id: string;
  message: string;
  expected: string;
  simulation: SimulationConfig | null;
}

export interface ArchitectureComponent {
  id: string;
  name: string;
  layer: string;
  path: string;
  responsibility: string;
}

export interface Architecture {
  components: ArchitectureComponent[];
  edges: { source: string; target: string; label: string }[];
  trust_boundaries: { name: string; description: string }[];
  tools: {
    name: string;
    description: string;
    permission: string;
    allowed_states: string[] | null;
    side_effect: boolean;
    idempotent: boolean;
    max_attempts: number;
    failure_behavior: string;
  }[];
  state_transitions: { from: string; to: string[]; terminal: boolean; in_flight: boolean; waiting: boolean }[];
  permission_matrix: { permission: string; roles: Record<string, boolean> }[];
  ai_provider: Record<string, string>;
}

export interface SecuritySummary {
  counts: Record<string, number>;
  denied_tools: Record<string, number>;
  total_denied: number;
}

export interface Health {
  status: string;
  environment: string;
  database: string;
  ai_provider: Record<string, string>;
  demo_mode: boolean;
  version: string;
}

export interface DemoUsers {
  enabled: boolean;
  password?: string;
  users: { username: string; role: Role; display_name: string }[];
}

export interface Policy {
  id: string;
  name: string;
  version: number;
  is_active: boolean;
  config: {
    currency: string;
    eligible_statuses: string[];
    refund_window_days: number;
    auto_approve_max_paise: number;
    reviewer_max_paise: number;
    allow_partial_refunds: boolean;
    allow_exception_override: boolean;
  };
  created_at: string;
  created_by: string | null;
}
