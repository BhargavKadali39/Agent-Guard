import { expect, test } from "@playwright/test";

import { DEMO_PASSWORD, login } from "./helpers";

test("unauthenticated users are sent to the login page", async ({ page }) => {
  await page.goto("/workflows");
  await expect(page).toHaveURL(/\/login/);
});

test("wrong password shows an error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill("olivia.operator");
  await page.getByLabel("Password").fill("definitely-wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").filter({ hasText: /invalid username or password/i })).toBeVisible();
});

test("operator can sign in and see the overview; security monitor is hidden", async ({ page }) => {
  await login(page, "olivia.operator");
  await expect(page.getByText("Olivia Fernandes")).toBeVisible();
  await expect(page.getByRole("link", { name: "Security Monitor" })).toHaveCount(0);
  await expect(page.getByText("Total workflows")).toBeVisible();
  expect(DEMO_PASSWORD.length).toBeGreaterThan(0);
});
