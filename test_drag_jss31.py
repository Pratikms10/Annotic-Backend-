import asyncio
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

        # Get `jss31` bounding box
        box = await page.evaluate("""() => {
            const el = document.querySelector('.jss31');
            return el ? el.getBoundingClientRect() : null;
        }""")
        
        if not box:
            print("No jss31 found!")
            return
            
        print(f"Jss31 box: {box}")
        
        # Center of the screen (playhead)
        # Since width is 3072, playhead is at 1536
        playhead_x = box['x'] + box['width'] / 2
        
        # Y must be EXACTLY in the middle of jss31 (which is 15px tall)
        target_y = box['y'] + (box['height'] / 2)
        
        print("Seeking to 5.0...")
        await page.evaluate("""() => {
            const a = document.querySelector('audio');
            if (a) {
                a.currentTime = 5.0;
                a.dispatchEvent(new Event('seeked', { bubbles: true }));
                a.dispatchEvent(new Event('timeupdate', { bubbles: true }));
            }
        }""")
        await page.wait_for_timeout(500)
        
        rows_before = await page.evaluate("() => { const c = document.getElementById('subTitleContainer'); return c ? c.children.length : 0; }")
        
        start_x = playhead_x + 5   # slight offset from playhead cursor
        end_x = start_x + 150
        
        print(f"Dragging on jss31 from X={start_x:.1f} to {end_x:.1f} at Y={target_y:.1f}")
        
        # Click firmly to focus timeline
        await page.mouse.click(start_x, target_y)
        await page.wait_for_timeout(200)

        # Drag
        await page.mouse.move(start_x, target_y)
        await page.wait_for_timeout(200)
        await page.mouse.down()
        await page.wait_for_timeout(300) # hold before drag
        
        steps = 20
        for i in range(steps):
            px = start_x + (150 * (i + 1) / steps)
            await page.mouse.move(px, target_y)
            await page.wait_for_timeout(20)
            
        await page.wait_for_timeout(200)
        await page.mouse.up()
        await page.wait_for_timeout(1500)
        
        rows_after = await page.evaluate("() => { const c = document.getElementById('subTitleContainer'); return c ? c.children.length : 0; }")
        
        if rows_after > rows_before:
            print("SUCCESS! Creating segment on jss31 worked!")
        else:
            print("FAILED. Dragging on jss31 did not create segment.")
            
        await page.wait_for_timeout(5000)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
