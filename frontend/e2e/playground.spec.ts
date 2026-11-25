import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test("auto-tier refund completes end to end and shows the audit timeline", async ({ page }) => {
  await login(page, "olivia.operator");
  await page.getByRole("link", { name: "Agent Playground" }).click();
  await page.getByLabel("Customer (trusted)").selectOption("CUST-1005");
  await page
    .getByLabel("Customer message (untrusted)")
    .fill("The laptop backpack from ORD-1009 has a broken zip. Please refund ₹999 as a partial refund.");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByText("COMPLETED").first()).toBeVisible();
  await expect(page.getByText(/Refunded ₹999\.00/)).toBeVisible();
  await expect(page.getByText("execution.completed")).toBeVisible();
  await expect(page.getByText("approval.auto_granted")).toBeVisible();
});

test("prompt injection is flagged, denied and escalated to a senior reviewer", async ({ page }) => {
  await login(page, "olivia.operator");
  await page.goto("/playground");
  await page.getByRole("button", { name: /Prompt injection on a large refund/ }).click();
  await expect(page.getByLabel("Customer message (untrusted)")).toHaveValue(/SYSTEM OVERRIDE/);
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByText("AWAITING APPROVAL").first()).toBeVisible();
  await expect(page.getByText("suspected injection")).toBeVisible();
  await expect(page.getByText("security.injection_suspected")).toBeVisible();
  await expect(page.getByText("tool.authorization_denied").first()).toBeVisible();
  await expect(page.getByText(/Waiting for senior reviewer/i)).toBeVisible();
});
