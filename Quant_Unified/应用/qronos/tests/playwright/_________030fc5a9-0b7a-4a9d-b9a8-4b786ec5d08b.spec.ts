
import { test } from '@playwright/test';
import { expect } from '@playwright/test';

test('自动化导入与启动_2025-12-08', async ({ page, context }) => {
  
    // Navigate to URL
    await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
});