import type {
  Approval,
  Architecture,
  AuditEvent,
  Customer,
  DemoUsers,
  EventList,
  ExampleRequest,
  Health,
  LabRun,
  Metrics,
  Order,
  Policy,
  Scenario,
  ScenarioResult,
  SecuritySummary,
  SimulationConfig,
  TokenResponse,
  User,
  Workflow,
  WorkflowList,
} from "./types";

const TOKEN_KEY = "agentguard.token";
const USER_KEY = "agentguard.user";

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export const tokenStore = {
  get(): string | null {
    if (typeof window === "undefined") return null;
    return window.sessionStorage.getItem(TOKEN_KEY);
  },
  set(token: string, user: User) {
    window.sessionStorage.setItem(TOKEN_KEY, token);
    window.sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  user(): User | null {
    if (typeof window === "undefined") return null;
    const raw = window.sessionStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  },
  clear() {
    window.sessionStorage.removeItem(TOKEN_KEY);
    window.sessionStorage.removeItem(USER_KEY);
  },
};

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) headers.set("Content-Type", "application/json");
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers, cache: "no-store" });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { error: { code: "invalid_response", message: text.slice(0, 200) } };
  }
  if (!response.ok) {
    const error = (body as { error?: { code?: string; message?: string; details?: Record<string, unknown> } })?.error;
    if (response.status === 401 && onUnauthorized && !path.startsWith("/api/auth/login")) onUnauthorized();
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? `Request failed with status ${response.status}`,
      error?.details ?? {},
    );
  }
  return body as T;
}

export const api = {
  // auth
  login: (username: string, password: string) =>
    request<TokenResponse>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  me: () => request<User>("/api/auth/me"),
  demoUsers: () => request<DemoUsers>("/api/auth/demo-users"),
  health: () => request<Health>("/api/health"),

  // commerce
  customers: () => request<Customer[]>("/api/customers"),
  customerOrders: (customerId: string) => request<Order[]>(`/api/customers/${customerId}/orders`),
  orders: () => request<Order[]>("/api/orders"),
  activePolicy: () => request<Policy>("/api/policies/active"),

  // workflows
  workflows: (params: { state?: string; limit?: number; offset?: number } = {}) => {
    const search = new URLSearchParams();
    if (params.state) search.set("state", params.state);
    if (params.limit) search.set("limit", String(params.limit));
    if (params.offset) search.set("offset", String(params.offset));
    const query = search.toString();
    return request<WorkflowList>(`/api/workflows${query ? `?${query}` : ""}`);
  },
  workflow: (id: string) => request<Workflow>(`/api/workflows/${id}`),
  workflowEvents: (id: string) => request<EventList>(`/api/workflows/${id}/events`),
  submitWorkflow: (body: { customer_id: string; message: string; client_request_id?: string; simulation?: SimulationConfig | null }) =>
    request<Workflow>("/api/workflows", { method: "POST", body: JSON.stringify(body) }),
  resumeWorkflow: (id: string) => request<Workflow>(`/api/workflows/${id}/resume`, { method: "POST" }),
  cancelWorkflow: (id: string, reason: string) =>
    request<Workflow>(`/api/workflows/${id}/cancel`, { method: "POST", body: JSON.stringify({ reason }) }),

  // approvals
  approvals: (status?: string) => request<Approval[]>(`/api/approvals${status ? `?status=${status}` : ""}`),
  decide: (id: string, decision: "approve" | "reject", comment: string) =>
    request<Workflow>(`/api/approvals/${id}/decide`, { method: "POST", body: JSON.stringify({ decision, comment }) }),

  // observability
  events: (params: { category?: string; event_type?: string; workflow_id?: string; severity?: string; limit?: number } = {}) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") search.set(k, String(v));
    });
    const query = search.toString();
    return request<EventList>(`/api/events${query ? `?${query}` : ""}`);
  },
  securityEvents: (limit = 100) => request<EventList>(`/api/security/events?limit=${limit}`),
  securitySummary: () => request<SecuritySummary>("/api/security/summary"),
  metrics: () => request<Metrics>("/api/metrics/overview"),
  architecture: () => request<Architecture>("/api/architecture"),

  // failure lab & playground
  scenarios: () => request<Scenario[]>("/api/failure-lab/scenarios"),
  runScenario: (key: string) => request<ScenarioResult>(`/api/failure-lab/scenarios/${key}/run`, { method: "POST" }),
  labRuns: () => request<LabRun[]>("/api/failure-lab/runs"),
  examples: () => request<ExampleRequest[]>("/api/playground/examples"),
  resetDemoData: () => request<{ reset: Record<string, number> }>("/api/admin/reset-demo-data", { method: "POST" }),
};

export type { AuditEvent };
