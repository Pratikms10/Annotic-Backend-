import asyncio
import json
import os
import sys
import itertools

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import PLAYWRIGHT_SESSION_DIR, ANNOTIC_TASK_URL
from playwright.async_api import async_playwright

SEGMENTS_JSON = os.path.join(os.path.dirname(__file__), "segments.json")
SEEK_TOLERANCE = 0.05

class BruteForceBot:
    def __init__(self, page):
        self.page = page
        self.pps = None
        self.playhead_x = None
        self.box = None

    async def force_scroll(self):
        # Force scrolling to bypass React overflow hidden issues
        await self.page.evaluate("""() => {
            const els = document.querySelectorAll('*');
            for(let el of els) {
                const style = window.getComputedStyle(el);
                if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
                    el.scrollTop = 10000;
                }
            }
            window.scrollTo(0, 10000);
        }""")
        await self.page.wait_for_timeout(500)

    async def init_measurements(self):
        await self.force_scroll()

        self.box = await self.page.evaluate("""() => {
            const canvas = Array.from(document.querySelectorAll('canvas'))
                .find(c => c.getBoundingClientRect().width > 100);
            return canvas ? canvas.getBoundingClientRect() : null;
        }""")
        
        if not self.box:
            raise RuntimeError("Canvas not found!")
            
        print(f"Canvas Viewport Box: {self.box}")
        self.playhead_x = self.box['x'] + self.box['width'] / 2
        
        visible_sec = await self.page.evaluate("""() => {
            const span = document.querySelector('.jss34') || 
                         Array.from(document.querySelectorAll('span')).find(s => s.innerText.includes(' / '));
            if (span) {
                const parts = span.innerText.split(' / ');
                if (parts.length === 2 && parts[1].includes(':')) {
                    const t = parts[1].trim().split(':');
                    if (t.length === 3) {
                        return parseInt(t[0])*3600 + parseInt(t[1])*60 + parseFloat(t[2]);
                    }
                }
            }
            const a = document.querySelector('audio');
            return a ? a.duration : 0;
        }""")
        
        if not visible_sec or visible_sec <= 0:
            visible_sec = 94.72
            
        self.pps = self.box['width'] / visible_sec
        print(f"Calculated PPS: {self.pps:.2f} px/sec (Width: {self.box['width']}, VisSec: {visible_sec})")
        
    async def seek_to(self, target_sec: float) -> float:
        for _ in range(3):
            await self.page.evaluate(f"""() => {{
                const audio = document.querySelector('audio');
                if (audio) {{
                    audio.currentTime = {target_sec};
                    audio.dispatchEvent(new Event('seeked', {{ bubbles: true }}));
                    audio.dispatchEvent(new Event('timeupdate', {{ bubbles: true }}));
                }}
            }}""")
            await self.page.wait_for_timeout(200)
            current = await self.page.evaluate("document.querySelector('audio').currentTime")
            if abs(current - target_sec) <= SEEK_TOLERANCE:
                return current
        return await self.page.evaluate("document.querySelector('audio').currentTime")

    async def get_segment_count(self) -> int:
        return await self.page.evaluate("""() => {
            const c = document.getElementById('subTitleContainer');
            return c ? c.children.length : 0;
        }""")

    async def brute_force_segment(self, start_sec, end_sec):
        # The Brute Force Grid
        y_ratios = [0.1, 0.5, 0.9]
        focus_clicks = [False, True]
        holds_before = [10, 200, 500]
        holds_after = [10, 200]
        step_counts = [5, 20, 50]
        seek_offsets = [-1.0, 0.0, 0.5]
        
        combinations = list(itertools.product(
            y_ratios, focus_clicks, holds_before, holds_after, step_counts, seek_offsets
        ))
        
        print(f"\\nBeginning Brute Force: Testing {len(combinations)} combinations for interval {start_sec:.2f}s -> {end_sec:.2f}s...")
        
        for i, (y_ratio, focus, h_before, h_after, steps, offset) in enumerate(combinations):
            # Ensure canvas hasn't scrolled away
            await self.force_scroll()
            
            target_seek = max(0.0, start_sec + offset)
            current = await self.seek_to(target_seek)
            
            # The exact playhead might have shifted if the window resized, but assuming persistent box
            start_x = self.playhead_x + (start_sec - current) * self.pps
            end_x = self.playhead_x + (end_sec - current) * self.pps
            y_pos = self.box['y'] + (self.box['height'] * y_ratio)
            
            seg_before = await self.get_segment_count()
            
            # Status line
            print(f"  [{i+1}/{len(combinations)}] Y={y_ratio}, Foc={focus}, HB={h_before}, HA={h_after}, St={steps}, Off={offset}...", end=" ")
            
            # THE INTERACTION
            if focus:
                await self.page.mouse.click(self.box['x'] + 10, y_pos)
                await self.page.wait_for_timeout(100)
                
            await self.page.mouse.move(start_x, y_pos)
            await self.page.wait_for_timeout(100)
            
            await self.page.mouse.down()
            if h_before > 0:
                await self.page.wait_for_timeout(h_before)
                
            dist = end_x - start_x
            for j in range(steps):
                px = start_x + (dist * (j + 1) / steps)
                await self.page.mouse.move(px, y_pos)
                await self.page.wait_for_timeout(20)
                
            if h_after > 0:
                await self.page.wait_for_timeout(h_after)
                
            await self.page.mouse.up()
            
            # Small wait to let UI catch up
            await self.page.wait_for_timeout(800)
            
            # Cleanup any "Are you sure?" popups perfectly just in case
            try:
                popups = await self.page.locator('button:has-text("OK"), button:has-text("Yes")').all()
                for p in popups:
                    if await p.is_visible(): await p.click()
            except: pass
            
            seg_after = await self.get_segment_count()
            
            if seg_after > seg_before:
                print(f" [SUCCESS!!]")
                print(f"\\n>>>> BRUTE FORCE WINNER FOUND <<<<")
                print(f"Y_ratio:     {y_ratio}")
                print(f"Focus Click: {focus}")
                print(f"Hold Before: {h_before} ms")
                print(f"Hold After:  {h_after} ms")
                print(f"Steps:       {steps}")
                print(f"Seek Offset: {offset} s")
                return True
            else:
                print(f" [FAIL]")
                
        return False

def ts2s(ts):
    h, m, s = ts.split(':')
    s, ms = s.split('.')
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000

async def main():
    if not os.path.exists(SEGMENTS_JSON):
        print("segments.json missing!")
        return

    with open(SEGMENTS_JSON, 'r', encoding='utf-8') as f:
        segments = json.load(f)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=PLAYWRIGHT_SESSION_DIR,
            headless=False,
            no_viewport=True,
            args=['--window-size=1920,1080']
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        print(f"Loading {ANNOTIC_TASK_URL}...")
        await page.goto(ANNOTIC_TASK_URL, wait_until="networkidle", timeout=60000)
        
        await page.wait_for_selector('canvas', state='visible', timeout=30000)
        await page.wait_for_timeout(3000)
        
        bot = BruteForceBot(page)
        await bot.init_measurements()
        
        # Test on the first few valid segments
        for i, s in enumerate(segments[:3]):
            start_sec = ts2s(s['start'])
            end_sec = ts2s(s['end'])
            if end_sec - start_sec < 0.5:
                print(f"Skipping segment {i} (too short)")
                continue
                
            if await bot.brute_force_segment(start_sec, end_sec):
                print("\\nA valid configuration was discovered!")
                break
        
        print("\\nDone.")
        await page.wait_for_timeout(5000)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
