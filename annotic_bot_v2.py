import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import PLAYWRIGHT_SESSION_DIR, ANNOTIC_TASK_URL
from playwright.async_api import async_playwright

SEGMENTS_JSON = os.path.join(os.path.dirname(__file__), "segments.json")
SEEK_TOLERANCE = 0.05

class AnnoticAutomator:
    def __init__(self, page):
        self.page = page
        self.winning_drag_params = None
        self.pps = None
        self.playhead_x = None
        self.box = None

    async def init_measurements(self):
        # 1. Get waveform dimensions
        self.box = await self.page.evaluate("""() => {
            const canvas = Array.from(document.querySelectorAll('canvas'))
                .find(c => c.getBoundingClientRect().width > 100);
            return canvas ? canvas.getBoundingClientRect() : null;
        }""")
        if not self.box:
            raise RuntimeError("Canvas not found!")
            
        # The center of the canvas is ALWAYS the playhead red line
        self.playhead_x = self.box['x'] + self.box['width'] / 2
        
        # 2. Get visible time range (Assuming the canvas shows the full audio by default, or relying on audio duration)
        # If the UI is zoomed, audio.duration is wrong. But let's assume it's full width for now.
        duration = await self.page.evaluate("document.querySelector('audio').duration")
        if not duration or duration <= 0:
            duration = 94.72 # fallback
            
        self.pps = self.box['width'] / duration
        print(f"Canvas: Width={self.box['width']:.1f}, Audio Duration={duration:.1f}s")
        print(f"Pixels Per Second: {self.pps:.2f} px/sec")
        
    async def seek_to(self, target_sec: float) -> float:
        for _ in range(5):
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

    async def dismiss_popup(self):
        try:
            popup = self.page.locator('button:has-text("OK"), button:has-text("Yes"), button:has-text("Confirm")')
            if await popup.count() > 0:
                await popup.first.click()
                await self.page.wait_for_timeout(500)
        except:
            pass

    async def perform_tuned_drag(self, start_sec, end_sec, current_time, params):
        # Unpack parameters
        y_lane_ratio = params['y']          # 0.0 (top), 0.5 (center), 1.0 (bottom)
        hold_time = params['hold']          # ms
        steps = params['steps']             # int
        focus_click = params['focus']       # bool
        
        # Math: convert start/end to pixel offsets relative to current playhead
        start_x = self.playhead_x + (start_sec - current_time) * self.pps
        end_x = self.playhead_x + (end_sec - current_time) * self.pps
        
        y_pos = self.box['y'] + (self.box['height'] * y_lane_ratio)
        
        # Focus the timeline?
        if focus_click:
            # click on a safe neutral spot (far left edge of waveform)
            await self.page.mouse.click(self.box['x'] + 10, y_pos)
            await self.page.wait_for_timeout(200)
            
        # Drag Sequence
        await self.page.mouse.move(start_x, y_pos)
        await self.page.wait_for_timeout(100)
        
        await self.page.mouse.down()
        await self.page.wait_for_timeout(hold_time) # The crucial HOLD
        
        drag_dist = end_x - start_x
        for i in range(steps):
            px = start_x + (drag_dist * (i + 1) / steps)
            await self.page.mouse.move(px, y_pos)
            await self.page.wait_for_timeout(20)
            
        await self.page.wait_for_timeout(hold_time) # Post hold
        await self.page.mouse.up()
        await self.page.wait_for_timeout(1000)

    async def write_text(self, text):
        typed = await self.page.evaluate(f"""() => {{
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
        return typed

    async def process_segment(self, start_str, end_str, text, seg_index):
        def ts2s(ts):
            h, m, s = ts.split(':')
            s, ms = s.split('.')
            return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000
            
        start_sec = ts2s(start_str)
        end_sec = ts2s(end_str)
        
        print(f"\\n--- Segment #{seg_index}: {start_str} -> {end_str} ---")
        
        # THE GRID: Tuples of (seek_offset, y_ratio, hold_ms, steps, focus_click)
        configs = [
            # If we know the winning formula, use only that
            self.winning_drag_params
        ] if self.winning_drag_params else [
            # Strategy A: Seek exactly to start_sec (clicks on red line)
            {'seek': 0.0, 'y': 0.5, 'hold': 500, 'steps': 15, 'focus': False},
            {'seek': 0.0, 'y': 0.9, 'hold': 500, 'steps': 15, 'focus': False},
            
            # Strategy B: Seek to midpoint (drags across red line)
            {'seek': (end_sec - start_sec) / 2, 'y': 0.5, 'hold': 200, 'steps': 20, 'focus': False},
            {'seek': (end_sec - start_sec) / 2, 'y': 0.1, 'hold': 500, 'steps': 10, 'focus': True},
            
            # Strategy C: Seek 1 second BEFORE start (drags to the right, never touching red line initially)
            {'seek': -1.0, 'y': 0.5, 'hold': 400, 'steps': 25, 'focus': True},
            {'seek': -1.0, 'y': 0.8, 'hold': 800, 'steps': 10, 'focus': False},
            {'seek': -1.0, 'y': 0.2, 'hold': 200, 'steps': 5, 'focus': False},
            
            # Strategy D: Bruteforce combinations on center
            {'seek': -0.5, 'y': 0.5, 'hold': 100, 'steps': 5, 'focus': True},
            {'seek': 0.5, 'y': 0.5, 'hold': 1000, 'steps': 20, 'focus': True},
        ]
        
        for idx, cfg in enumerate(configs):
            if not cfg: continue
            
            # 1. Convert start & end -> sec (done above)
            # 2. Read playhead time
            target_seek = start_sec + cfg['seek']
            if target_seek < 0: target_seek = 0
            
            current_time = await self.seek_to(target_seek)
            
            seg_before = await self.get_segment_count()
            
            print(f"  Attempt {idx+1}: SeekOffset={cfg['seek']:.1f}s | Y={cfg['y']} | Hold={cfg['hold']}ms | Steps={cfg['steps']} | Focus={cfg['focus']}")
            
            # 3. Perform TUNE DRAG
            await self.perform_tuned_drag(start_sec, end_sec, current_time, cfg)
            await self.dismiss_popup()
            
            seg_after = await self.get_segment_count()
            if seg_after > seg_before:
                print(f"  >>> SUCCESS! Placeholder created! Saving winning config.")
                self.winning_drag_params = cfg
                
                # Verify length? The segment exists. Let's type text!
                if await self.write_text(text):
                    print("  >>> Text typed successfully.")
                else:
                    print("  >>> Text input not found.")
                return True
            else:
                print(f"  [FAIL] Did not spawn placeholder.")
                
        print("  !!! Exhausted all tuning configs for this segment. Moving on.")
        return False

async def main():
    if not os.path.exists(SEGMENTS_JSON):
        print("segments.json not found!")
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
        print(f"Navigating to {ANNOTIC_TASK_URL}")
        await page.goto(ANNOTIC_TASK_URL, wait_until="networkidle", timeout=60000)
        
        await page.wait_for_selector('canvas', state='visible', timeout=30000)
        await page.wait_for_timeout(3000)

        bot = AnnoticAutomator(page)
        await bot.init_measurements()

        successes = 0
        for i, s in enumerate(segments):
            safe_txt = s['text'][:20].encode('ascii', 'ignore').decode('ascii')
            ok = await bot.process_segment(s['start'], s['end'], s['text'], i)
            if ok: successes += 1

        print(f"\\nAll done. {successes}/{len(segments)} segments created.")
        await page.wait_for_timeout(10000)
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(main())
