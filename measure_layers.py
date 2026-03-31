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
            function getBox(el) {
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {tag: el.tagName, className: el.className, x: r.left, y: r.top, w: r.width, h: r.height, zIndex: getComputedStyle(el).zIndex};
            }
            
            const canvas = document.querySelector('canvas');
            const jss24 = document.querySelector('.jss24');
            const jss31 = document.querySelector('.jss31');
            const jss35 = document.querySelector('.jss35');
            const jss38 = document.querySelector('.jss38');
            const subTitleContainer = document.getElementById('subTitleContainer');
            
            return {
                canvas: getBox(canvas),
                jss24: getBox(jss24),
                jss31: getBox(jss31),
                jss35: getBox(jss35),
                jss38: getBox(jss38),
                subTitleContainer: getBox(subTitleContainer)
            }
        }""")
        
        print(json.dumps(info, indent=2))
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
