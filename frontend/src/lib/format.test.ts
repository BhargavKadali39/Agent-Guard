import { describe, expect, it } from "vitest";

import { formatDuration, formatINR, humanize, reasonText, roleLabel, shortId } from "./format";

describe("formatINR", () => {
  it("formats paise as Indian rupees", () => {
    expect(formatINR(850000)).toBe("₹8,500.00");
    expect(formatINR(200001)).toBe("₹2,000.01");
    expect(formatINR(0)).toBe("₹0.00");
  });
  it("handles missing values", () => {
    expect(formatINR(null)).toBe("—");
    expect(formatINR(undefined)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("scales units", () => {
    expect(formatDuration(45)).toBe("45 ms");
    expect(formatDuration(1500)).toBe("1.5 s");
    expect(formatDuration(90_000)).toBe("1.5 min");
    expect(formatDuration(null)).toBe("—");
  });
});

describe("labels", () => {
  it("humanizes snake_case and colon separated reasons", () => {
    expect(humanize("policy:outside_refund_window")).toBe("policy outside refund window");
    expect(roleLabel("senior_reviewer")).toBe("Senior Reviewer");
    expect(roleLabel("agent")).toBe("Agent");
    expect(shortId("1df31790-6486-4d2c")).toBe("1df31790…");
  });
});

describe("reasonText", () => {
  it("formats the reasons the orchestrator records", () => {
    expect(reasonText("order_not_identified: order_ambiguous")).toBe(
      "Order not identified: several eligible orders, none named in the message",
    );
    expect(reasonText("order_not_identified: intent_not_refund:order_status_inquiry, order_ambiguous")).toBe(
      "Order not identified: not a refund request (order status inquiry); several eligible orders, none named in the message",
    );
    expect(reasonText("order_not_identified: order_not_found_or_not_owned:ORD-1099")).toBe(
      "Order not identified: order not found for this customer (ORD-1099)",
    );
    expect(reasonText("order_not_identified: no eligible order")).toBe("Order not identified: no eligible order");
    expect(reasonText("policy:amount_not_positive,already_refunded")).toBe(
      "Rejected by policy: amount not positive; already refunded",
    );
  });
  it("keeps a reviewer's comment as written", () => {
    expect(reasonText("rejected_by_reviewer: Offered a replacement, not_refund.")).toBe(
      "Rejected by reviewer: Offered a replacement, not_refund.",
    );
    expect(reasonText(null)).toBe("—");
    expect(reasonText("auto")).toBe("auto");
  });
});
