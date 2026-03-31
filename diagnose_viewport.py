import asyncio
import os
from playwright.async_api import async_playwright
import config

async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=config.PLAYWRIGHT_SESSION_DIR,
            headless=True,
            no_viewport=True,
            args=['--window-size=1920,1080']
        )
        page = context.pages[0] if context.pages else await context.new_page()
        print(f"Navigating to {config.ANNOTIC_TASK_URL}")
        await page.goto(config.ANNOTIC_TASK_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        # Scroll into view
        await page.locator("canvas").first.scroll_into_view_if_needed()
        await page.wait_for_timeout(1000)

        info = await page.evaluate("""() => {
            const canvas = Array.from(document.querySelectorAll('canvas'))
                .find(c => c.getBoundingClientRect().width > 100);
            const cr = canvas ? canvas.getBoundingClientRect() : null;
            const container = canvas ? canvas.parentElement.parentElement : null;
            const ctr = container ? container.getBoundingClientRect() : null;

            return {
                windowInnerWidth: window.innerWidth,
                windowInnerHeight: window.innerHeight,
                canvasRect: cr ? { top: cr.top, left: cr.left, width: cr.width, height: cr.height } : null,
                containerRect: ctr ? { top: ctr.top, left: ctr.left, width: ctr.width, height: ctr.height } : null,
                devicePixelRatio: window.devicePixelRatio
            };
        }""")

        import json
        print(json.dumps(info, indent=2))
        
        await context.close()

if __name__ == "__main__":
    asyncio.run(main())
