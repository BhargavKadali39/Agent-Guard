const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Format integer paise as Indian rupees, e.g. 850000 -> "₹8,500.00". */
export function formatINR(paise: number | null | undefined): string {
  if (paise === null || paise === undefined) return "—";
  return inr.format(paise / 100);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function formatTime(value: string): string {
  const date = new Date(value);
  return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}

export function shortId(id: string | null | undefined, length = 8): string {
  if (!id) return "—";
  return id.length > length ? `${id.slice(0, length)}…` : id;
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  return value.replace(/[_:.]/g, " ").replace(/\s+/g, " ").trim();
}

const REASON_PREFIXES: Record<string, string> = {
  order_not_identified: "Order not identified",
  rejected_by_reviewer: "Rejected by reviewer",
  policy: "Rejected by policy",
};

const REASON_DETAILS: Record<string, string> = {
  order_ambiguous: "several eligible orders, none named in the message",
  intent_not_refund: "not a refund request",
  order_not_found_or_not_owned: "order not found for this customer",
};

function reasonDetail(code: string): string {
  const sep = code.indexOf(":");
  const key = (sep === -1 ? code : code.slice(0, sep)).trim();
  const value = sep === -1 ? "" : code.slice(sep + 1).trim();
  const label = REASON_DETAILS[key] ?? humanize(key);
  return value ? `${label} (${humanize(value)})` : label;
}

/** Readable text for a workflow's rejection reason, e.g. "policy:a,b" or "order_not_identified: x". */
export function reasonText(reason: string | null | undefined): string {
  if (!reason) return "—";
  const sep = reason.indexOf(":");
  if (sep === -1) return humanize(reason);
  const prefix = reason.slice(0, sep).trim();
  const rest = reason.slice(sep + 1).trim();
  const label = REASON_PREFIXES[prefix] ?? humanize(prefix);
  // A reviewer's comment is free text: show it as written.
  if (prefix === "rejected_by_reviewer") return rest ? `${label}: ${rest}` : label;
  const details = rest
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map(reasonDetail);
  return details.length ? `${label}: ${details.join("; ")}` : label;
}

export function roleLabel(role: string | null | undefined): string {
  switch (role) {
    case "support_operator":
      return "Support Operator";
    case "reviewer":
      return "Reviewer";
    case "senior_reviewer":
      return "Senior Reviewer";
    case "administrator":
      return "Administrator";
    case "agent":
      return "Agent";
    default:
      return humanize(role);
  }
}
