import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test("reviewer approves a pending refund and the workflow completes", async ({ page }) => {
  // Create a reviewer-tier request as the operator.
  await login(page, "olivia.operator");
  await page.goto("/playground");
  await page.getByLabel("Customer (trusted)").selectOption("CUST-1001");
  await page
    .getByLabel("Customer message (untrusted)")
    .fill("Headphones from ORD-1001 arrived damaged. Please refund ₹2,500 as a partial refund.");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByText("AWAITING APPROVAL").first()).toBeVisible();

  // The operator sees the approval but cannot decide it.
  await page.goto("/approvals");
  const row = page.getByRole("row").filter({ hasText: "₹2,500.00" }).first();
  await expect(row).toBeVisible();
  await expect(row.getByRole("button", { name: "Approve" })).toBeDisabled();

  // Sign out and decide as a reviewer.
  await page.getByRole("button", { name: "Sign out" }).click();
  await login(page, "ravi.reviewer");
  await page.goto("/approvals");
  const reviewRow = page.getByRole("row").filter({ hasText: "₹2,500.00" }).first();
  await reviewRow.getByRole("button", { name: "Approve" }).click();
  await page.getByLabel("Comment").fill("Verified the photos.");
  await page.getByRole("button", { name: "Confirm approval" }).click();
  await expect(page.getByText(/workflow is now COMPLETED/)).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "Ravi Menon" }).first()).toBeVisible();
});
