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
        print("Navigating to URL...")
        await page.goto(config.ANNOTIC_TASK_URL, wait_until="networkidle", timeout=60000)
        
        await page.wait_for_selector('canvas', state='visible', timeout=30000)
        await page.wait_for_timeout(3000)
        
        print("Seeking to 5.0s...")
        await page.evaluate("""() => {
            const a = document.querySelector('audio');
            if (a) {
                a.currentTime = 5.0;
                a.dispatchEvent(new Event('seeked', { bubbles: true }));
                a.dispatchEvent(new Event('timeupdate', { bubbles: true }));
            }
        }""")
        await page.wait_for_timeout(1000)

        info = await page.evaluate("""() => {
            const cursor = document.querySelector('.wf-cursor');
            const cRect = cursor ? cursor.getBoundingClientRect() : null;
            
            const canvas = document.querySelector('canvas');
            const canvasRect = canvas ? canvas.getBoundingClientRect() : null;
            
            return {
                cursorRect: cRect ? {x: cRect.x, y: cRect.y, w: cRect.width, h: cRect.height} : null,
                canvasRect: canvasRect ? {x: canvasRect.x, y: canvasRect.y, w: canvasRect.width, h: canvasRect.height} : null,
                windowWidth: window.innerWidth
            };
        }""")
        
        print(json.dumps(info, indent=2))
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
