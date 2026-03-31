import asyncio
import itertools
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
        print("Navigating to new task URL...")
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
            
        center_x = box['x'] + box['width'] / 2
        y_top = box['y'] + 15
        y_center = box['y'] + box['height'] / 2
        y_bottom = box['y'] + box['height'] - 15
        
        # Seek back and forth to ensure UI is active
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
            
        async def try_drag(y_lane, y_name, hold_ms, steps, offset=10):
            print(f"\\n--- Testing: Y={y_name}, Hold={hold_ms}ms, Steps={steps}, Offset={offset}px ---")
            
            # Click first to force focus
            await page.mouse.click(center_x - 50, y_lane)
            await page.wait_for_timeout(200)

            start_x = center_x + offset
            end_x = start_x + 150
            
            rows_before = await get_rows()
            
            # Step 1: Move mouse to start
            await page.mouse.move(start_x, y_lane)
            await page.wait_for_timeout(200)
            
            # Step 2: Press and HOLD
            await page.mouse.down()
            print(f"  Holding for {hold_ms}ms...")
            await page.wait_for_timeout(hold_ms)
            
            # Step 3: Move
            print(f"  Dragging with {steps} steps...")
            for i in range(steps):
                px = start_x + (150 * (i + 1) / steps)
                # Introduce slight Y jitter to simulate real mouse? No, keep it straight.
                await page.mouse.move(px, y_lane)
                await page.wait_for_timeout(20)
                
            # Step 4: Release
            await page.wait_for_timeout(100)
            await page.mouse.up()
            await page.wait_for_timeout(1500)
            
            rows_after = await get_rows()
            if rows_after > rows_before:
                print(f"\\n>>> SUCCESS! WINNING COMBO: Y={y_name}, Hold={hold_ms}ms, Steps={steps}, Offset={offset}px <<<")
                return True
            else:
                print(f"  Failed.")
                return False

        # Parameters to test
        y_lanes = [(y_center, "Center"), (y_top, "Top"), (y_bottom, "Bottom")]
        hold_times = [100, 500, 1000]
        step_counts = [5, 20, 50]
        offsets = [5, 20]
        
        combinations = list(itertools.product(y_lanes, hold_times, step_counts, offsets))
        print(f"Testing {len(combinations)} combinations...")
        
        for (y_val, y_name), hold, steps, offset in combinations:
            # We attempt it
            won = await try_drag(y_val, y_name, hold, steps, offset)
            if won:
                print("\\nStopping grid search because we found the trigger!")
                break

        print("\\nWaiting 5s then closing...")
        await page.wait_for_timeout(5000)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
