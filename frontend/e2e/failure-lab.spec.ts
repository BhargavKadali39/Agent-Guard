import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test("failure lab scenarios run with real assertions", async ({ page }) => {
  await login(page, "sana.senior");
  await page.goto("/failure-lab");
  await expect(page.getByText("Prompt Injection", { exact: true }).first()).toBeVisible();
  const card = page.getByText("Human Approval Rejection", { exact: true }).locator("xpath=ancestor::div[contains(@class,'rounded-lg')][1]");
  await card.getByRole("button", { name: "Run" }).click();
  await expect(page.getByText("all passed")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("rejection_recorded_with_reviewer_identity")).toBeVisible();
  await expect(page.getByText("execution_blocked_after_rejection")).toBeVisible();
});

test("architecture explorer reflects the live tool catalogue", async ({ page }) => {
  await login(page, "arjun.admin");
  await page.goto("/architecture");
  await expect(page.getByText("execute_simulated_refund").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Permission matrix" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Trust boundaries" })).toBeVisible();
});

test("security monitor is visible to reviewers", async ({ page }) => {
  await login(page, "ravi.reviewer");
  await page.getByRole("link", { name: "Security Monitor" }).click();
  await expect(page.getByRole("heading", { name: "Security Monitor" })).toBeVisible();
  await expect(page.getByText("Injection attempts flagged")).toBeVisible();
});
