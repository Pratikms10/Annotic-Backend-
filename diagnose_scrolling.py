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

        async def get_y():
            return await page.evaluate("""() => {
                const canvas = document.querySelector('canvas');
                return canvas ? canvas.getBoundingClientRect().y : -1;
            }""")
            
        y1 = await get_y()
        print(f"Initial Canvas Y: {y1}")
        
        # Method 1: Mouse wheel
        print("Attempting Mouse Wheel scroll...")
        await page.mouse.move(500, 500)
        await page.mouse.wheel(0, 500)
        await page.wait_for_timeout(1000)
        y2 = await get_y()
        print(f"Canvas Y after wheel: {y2}")
        
        # Method 2: Force scroll all scrollable ancestors
        if y2 == y1:
            print("Mouse wheel failed. Forcing all overflow:auto/scroll containers to max scroll...")
            await page.evaluate("""() => {
                const els = document.querySelectorAll('*');
                for(let el of els) {
                    const style = window.getComputedStyle(el);
                    if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
                        el.scrollTop = 1000;
                    }
                }
                window.scrollTo(0, 1000);
            }""")
            await page.wait_for_timeout(1000)
            y3 = await get_y()
            print(f"Canvas Y after forceful DOM scroll: {y3}")
            
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
