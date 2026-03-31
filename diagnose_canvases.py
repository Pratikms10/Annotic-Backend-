import asyncio
import json
from playwright.async_api import async_playwright
import config

async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=config.PLAYWRIGHT_SESSION_DIR,
            headless=False,
            no_viewport=True,
            args=['--window-size=1920,1080']
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        print("Navigating...")
        await page.goto(config.ANNOTIC_TASK_URL, wait_until="networkidle", timeout=60000)
        
        await page.wait_for_selector('canvas', state='visible', timeout=30000)
        await page.wait_for_timeout(3000)

        info = await page.evaluate("""() => {
            const canvases = Array.from(document.querySelectorAll('canvas'));
            return canvases.map((c, i) => {
                const r = c.getBoundingClientRect();
                return {
                    index: i,
                    width: r.width,
                    height: r.height,
                    top: r.top,
                    left: r.left,
                    parentClass: c.parentElement ? c.parentElement.className : 'none',
                    grandParentClass: c.parentElement && c.parentElement.parentElement ? c.parentElement.parentElement.className : 'none'
                };
            });
        }""")
        
        print("CANVASES FOUND:")
        print(json.dumps(info, indent=2))
        
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
