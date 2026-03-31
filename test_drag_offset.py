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

        box = await page.evaluate("""() => {
            const canvas = Array.from(document.querySelectorAll('canvas'))
                .find(c => c.getBoundingClientRect().width > 100);
            return canvas ? canvas.getBoundingClientRect() : null;
        }""")
        
        if not box:
            print("No canvas found!")
            return
            
        playhead_x = box['x'] + box['width'] / 2
        canvas_y = box['y'] + box['height'] / 2
        
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
        
        def get_rows():
            return page.evaluate("() => { const c = document.getElementById('subTitleContainer'); return c ? c.children.length : 0; }")
            
        async def try_drag(offset=0):
            print(f"\nTrying drag with initial offset {offset}px...")
            start_x = playhead_x + offset
            end_x = start_x + 150
            
            rows_before = await get_rows()
            
            await page.mouse.move(start_x, canvas_y)
            await page.wait_for_timeout(200)
            await page.mouse.down()
            await page.wait_for_timeout(100)
            
            steps = 20
            for i in range(steps):
                px = start_x + (150 * (i + 1) / steps)
                await page.mouse.move(px, canvas_y)
                await page.wait_for_timeout(30)
                
            await page.mouse.up()
            await page.wait_for_timeout(1000)
            
            rows_after = await get_rows()
            if rows_after > rows_before:
                print(f"SUCCESS! Dragging with offset {offset} created a segment.")
                return True
            else:
                print(f"FAILED. No segment created.")
                return False

        # Try various offsets
        if await try_drag(0): pass
        elif await try_drag(5): pass
        elif await try_drag(10): pass
        elif await try_drag(-10): pass

        # What if it's the jss35 element blocking? Let's check its click!
        print("\nChecking if pointer-events on overlays helps...")
        await page.evaluate("""() => {
            const overlays = Array.from(document.querySelectorAll('div[class*="jss"]'));
            for(let el of overlays) {
                if(el.className.includes('jss35') || el.className.includes('jss38')) {
                    el.style.pointerEvents = 'none';
                    console.log('Disabled pointer events on', el.className);
                }
            }
        }""")
        
        await try_drag(5)
        
        print("\nWaiting 5s then closing...")
        await page.wait_for_timeout(5000)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
