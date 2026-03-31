import asyncio
import json
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import PLAYWRIGHT_SESSION_DIR, ANNOTIC_TASK_URL
from playwright.async_api import async_playwright

SEGMENTS_JSON = os.path.join(os.path.dirname(__file__), "segments.json")
SEEK_TOLERANCE = 0.05

class AnnoticAutomator:
    def __init__(self, page):
        self.page = page
        self.pps = None
        self.playhead_x = None
        self.box = None
        self.winning_drag_params = None

    async def init_measurements(self):
        # Critical Fix: The canvas is at the bottom of the page (y ≈ 1308), 
        # which is OUTSIDE the 1080p viewport. Mouse events at y=1308 fail natively!
        # MUST scroll into view first.
        print("Scrolling waveform into view...")
        canvas_locator = self.page.locator('canvas').first
        await canvas_locator.wait_for(state="visible")
        await canvas_locator.scroll_into_view_if_needed()
        await self.page.wait_for_timeout(1000) # Wait for snap

        # 1. Get waveform dimensions
        self.box = await self.page.evaluate("""() => {
            const canvas = Array.from(document.querySelectorAll('canvas'))
                .find(c => c.getBoundingClientRect().width > 100);
            return canvas ? canvas.getBoundingClientRect() : null;
        }""")
        
        if not self.box:
            raise RuntimeError("Canvas not found!")
            
        print(f"Viewport Bounding Box: {self.box}")
        
        if not self.box:
            raise RuntimeError("Canvas not found!")

        # 2. Get playhead x (Center of waveform = playhead)
        self.playhead_x = self.box['x'] + self.box['width'] / 2
        
        # 3. Get visible time range
        # Extract the total duration from the UI span '00:00:00 / 00:01:34'
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
            // fallback Native audio
            const a = document.querySelector('audio');
            return a ? a.duration : 0;
        }""")
        
        if not visible_sec or visible_sec <= 0:
            visible_sec = 94.72
            
        self.pps = self.box['width'] / visible_sec
        print(f"Canvas Width={self.box['width']:.1f}, Visible Duration={visible_sec:.1f}s")
        print(f"Pixels Per Second: {self.pps:.2f} px/sec")
        
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

    async def perform_drag(self, start_x, end_x, y_lane=0.5, hold=300, steps=15, focus=True):
        # Y Coordinate: Center by default, or slightly above/below depending on config
        y_pos = self.box['y'] + (self.box['height'] * y_lane)
        
        # Optionally click to focus selection first
        if focus:
            await self.page.mouse.click(self.box['x'] + 50, y_pos)
            await self.page.wait_for_timeout(100)

        # 1. Move to start X
        await self.page.mouse.move(start_x, y_pos)
        await self.page.wait_for_timeout(100)
        
        # 2. Click and Hold (Hold time before moving)
        await self.page.mouse.down()
        await self.page.wait_for_timeout(hold)
        
        # 3. Drag with movement style
        drag_dist = end_x - start_x
        for i in range(steps):
            px = start_x + (drag_dist * (i + 1) / steps)
            await self.page.mouse.move(px, y_pos)
            await self.page.wait_for_timeout(20)
            
        # 4. Hold slightly and Release
        await self.page.wait_for_timeout(150)
        await self.page.mouse.up()
        await self.page.wait_for_timeout(1000)

    async def type_text(self, text: str):
        return await self.page.evaluate(f"""() => {{
            const container = document.getElementById('subTitleContainer');
            if (!container) return false;
            const lastRow = container.lastElementChild;
            if (!lastRow) return false;
            
            const input = lastRow.querySelector('textarea, input[type="text"], [contenteditable="true"]');
            if (input) {{
                if (input.tagName === 'TEXTAREA' || input.tagName === 'INPUT') {{
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value'
                    )?.set || Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    )?.set;
                    if (nativeInputValueSetter) {{
                        nativeInputValueSetter.call(input, `{text.replace('`', '\\`').replace("'", "\\'")}`);
                    }} else {{
                        input.value = `{text.replace('`', '\\`').replace("'", "\\'")}`; 
                    }}
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }} else {{
                    input.textContent = `{text.replace('`', '\\`').replace("'", "\\'")}`; 
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    return true;
                }}
            }}
            return false;
        }}""")

    def ts2s(self, ts):
        h, m, s = ts.split(':')
        s, ms = s.split('.')
        return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000

    async def process_segment(self, seg, idx):
        start_sec = self.ts2s(seg['start'])
        end_sec = self.ts2s(seg['end'])
        
        print(f"\\n[{idx+1}] Processing: {seg['start']} -> {seg['end']}")
        
        # Grid configs to tune the 5 things
        configs = [self.winning_drag_params] if self.winning_drag_params else [
            # TUNE 1: Seek precisely to start, so start_x = center, drag right.
            # Y=0.5 (center), Hold=400ms, Steps=20, Focus=True
            {'seek': 0.0, 'y': 0.5, 'hold': 400, 'steps': 20, 'focus': True},
            
            # TUNE 2: Seek -1.0s before start. Drag from center+1s to center+1s+dur
            # Y=0.5, Hold=400ms, Focus=True
            {'seek': -1.0, 'y': 0.5, 'hold': 400, 'steps': 20, 'focus': True},
            
            # TUNE 3: The exact center, but Y=0.1 (top lane near jss31), Hold=800ms
            {'seek': 0.0, 'y': 0.1, 'hold': 800, 'steps': 15, 'focus': False},
            
            # TUNE 4: Y=0.9 (bottom lane), Hold=300
            {'seek': -0.5, 'y': 0.9, 'hold': 300, 'steps': 25, 'focus': True}
        ]
        
        for cfg in configs:
            if not cfg: continue
            
            target_seek = max(0.0, start_sec + cfg['seek'])
            current = await self.seek_to(target_seek)
            
            # Convert start/end -> pixel offset
            start_x = self.playhead_x + (start_sec - current) * self.pps
            end_x = self.playhead_x + (end_sec - current) * self.pps
            
            seg_before = await self.get_segment_count()
            
            print(f"  > Tuned Drag: Seek Offset={cfg['seek']}s, StartX={start_x:.1f}, EndX={end_x:.1f}, Y={cfg['y']}, Hold={cfg['hold']}ms")
            await self.perform_drag(start_x, end_x, y_lane=cfg['y'], hold=cfg['hold'], steps=cfg['steps'], focus=cfg['focus'])
            
            seg_after = await self.get_segment_count()
            
            if seg_after > seg_before:
                print(f"  [OK] Placeholder magically spawned! Using this tuning permanently.")
                self.winning_drag_params = cfg
                
                # Fill in text
                if await self.type_text(seg['text']):
                    print("  [OK] Text typed.")
                return True
                
            print("  [FAIL] Drag ignored by UI.")
            
        return False

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
        
        bot = AnnoticAutomator(page)
        await bot.init_measurements()
        
        success_count = 0
        for i, s in enumerate(segments):
            if await bot.process_segment(s, i):
                success_count += 1
                
        print(f"\\nSUCCESSFULLY PROCESSED {success_count} / {len(segments)} SEGMENTS!")
        await page.wait_for_timeout(5000)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
