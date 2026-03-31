import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import PLAYWRIGHT_SESSION_DIR, ANNOTIC_TASK_URL
from playwright.async_api import async_playwright

SEGMENTS_JSON = os.path.join(os.path.dirname(__file__), "segments.json")
SEEK_TOLERANCE = 0.05
MAX_SEEK_RETRIES = 10
MAX_DRAG_RETRIES = 5
DRAG_ADJUST_PX = 5


class AnnoticBot:
    def __init__(self, page):
        self.page = page
        self.pixels_per_second = None

    async def get_canvas_center(self):
        """Get the current dynamic center of the canvas."""
        box = await self.page.evaluate("""() => {
            const canvas = Array.from(document.querySelectorAll('canvas'))
                .find(c => c.getBoundingClientRect().width > 100);
            if (!canvas) return null;
            const cr = canvas.getBoundingClientRect();
            // We use the canvas rect directly, since it intercepts everything.
            return {
                x: cr.left,
                y: cr.top,
                width: cr.width,
                height: cr.height
            };
        }""")
        if not box:
            raise RuntimeError("Cannot find waveform canvas!")
        
        playhead_x = box['x'] + box['width'] / 2
        canvas_y = box['y'] + box['height'] / 2
        
        return playhead_x, canvas_y, box

    async def read_current_time(self) -> float:
        return await self.page.evaluate("""() => {
            const audio = document.querySelector('audio');
            return audio ? audio.currentTime : -1;
        }""")

    async def seek_to(self, target_sec: float) -> float:
        for attempt in range(MAX_SEEK_RETRIES):
            await self.page.evaluate(f"""() => {{
                const audio = document.querySelector('audio');
                if (audio) {{
                    audio.currentTime = {target_sec};
                    audio.dispatchEvent(new Event('seeked', {{ bubbles: true }}));
                    audio.dispatchEvent(new Event('timeupdate', {{ bubbles: true }}));
                }}
            }}""")
            await self.page.wait_for_timeout(300)

            current = await self.read_current_time()
            diff = abs(current - target_sec)
            if diff <= SEEK_TOLERANCE:
                return current

        current = await self.read_current_time()
        return current

    async def count_segments(self) -> int:
        return await self.page.evaluate("""() => {
            const c = document.getElementById('subTitleContainer');
            return c ? c.children.length : 0;
        }""")

    async def get_last_segment_info(self):
        """Extract the start and end time of the most recently created segment."""
        return await self.page.evaluate("""() => {
            const container = document.getElementById('subTitleContainer');
            if (!container || container.children.length === 0) return null;
            
            const lastRow = container.lastElementChild;
            // The times are usually in the first flex column, like "00:00:05.00000:00:06.000"
            // We can just grab all texts that match time formats
            const text = lastRow.innerText || "";
            const matches = text.match(/\\d{2}:\\d{2}:\\d{2}\\.\\d{3}/g);
            if (matches && matches.length >= 2) {
                return { start: matches[0], end: matches[1] };
            }
            return null;
        }""")
        
    async def delete_last_segment(self):
        """Click the delete button on the last segment."""
        await self.page.evaluate("""() => {
            const container = document.getElementById('subTitleContainer');
            if (!container || container.children.length === 0) return;
            const lastRow = container.lastElementChild;
            // Find SVG icon that looks like a trash can or delete
            const buttons = lastRow.querySelectorAll('svg');
            // We assume the last SVG is usually delete in these interfaces, or we just click standard buttons
            for (let svg of buttons) {
                if (svg.parentElement.tagName === 'BUTTON' || svg.parentElement.tagName === 'DIV') {
                    // Try to click
                    svg.parentElement.click();
                }
            }
        }""")
        await self.page.wait_for_timeout(500)
        # Handle "Are you sure?" popup if it exists
        await self.dismiss_popup()

    async def dismiss_popup(self):
        try:
            popup = self.page.locator('button:has-text("OK"), button:has-text("Yes"), button:has-text("Confirm")')
            if await popup.count() > 0:
                await popup.first.click()
                await self.page.wait_for_timeout(500)
        except Exception:
            pass

    async def perform_drag(self, start_x, end_x, y_pos):
        """Simulate a perfect, slow, exact mouse drag."""
        print(f"      Drag: {start_x:.0f} -> {end_x:.0f} (span: {abs(end_x - start_x):.0f}px)")
        await self.page.mouse.move(start_x, y_pos)
        await self.page.wait_for_timeout(200)
        await self.page.mouse.down()
        await self.page.wait_for_timeout(150)

        drag_dist = end_x - start_x
        steps = max(10, int(abs(drag_dist) / 5))
        for i in range(steps):
            px = start_x + (drag_dist * (i + 1) / steps)
            await self.page.mouse.move(px, y_pos)
            await self.page.wait_for_timeout(30)

        await self.page.wait_for_timeout(200)
        await self.page.mouse.up()
        await self.page.wait_for_timeout(1000)

    # ──────────────────────────────────────────
    # EMPIRICAL CALIBRATION 
    # ──────────────────────────────────────────
    async def calibrate_empirically(self):
        print("\n[SETUP] Starting empirical drag calibration...")
        # 1. Seek to safe time (e.g. 5.0 seconds)
        await self.seek_to(5.0)
        
        # 2. Get screen coordinates
        playhead_x, canvas_y, box = await self.get_canvas_center()
        
        # 3. Perform a fixed pixel drag (e.g. 150 pixels to the right)
        test_drag_px = 150
        
        # Make sure we don't drag out of bounds
        max_right = box['x'] + box['width'] - 10
        end_x = min(playhead_x + test_drag_px, max_right)
        actual_drag_px = end_x - playhead_x
        
        segments_before = await self.count_segments()
        await self.perform_drag(playhead_x, end_x, canvas_y)
        
        segments_after = await self.count_segments()
        if segments_after <= segments_before:
            raise RuntimeError("Empirical calibration failed: Dragging 150px did not create a segment placeholder! UI interceptor issue.")
            
        # 4. Read the created segment time duration
        info = await self.get_last_segment_info()
        if not info:
             raise RuntimeError("Empirical calibration failed: Created segment but could not read its timestamps.")
             
        def ts2sec(ts_str):
            h, m, s = ts_str.split(':')
            s, ms = s.split('.')
            return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000
            
        start_sec = ts2sec(info['start'])
        end_sec = ts2sec(info['end'])
        created_duration = end_sec - start_sec
        
        # 5. Calculate Pixels Per Second
        self.pixels_per_second = actual_drag_px / created_duration
        
        print(f"  [CALIBRATION SUCCESS]")
        print(f"    Dragged {actual_drag_px:.0f} pixels.")
        print(f"    Created segment duration: {created_duration:.3f} seconds.")
        print(f"    Calculated PPS = {self.pixels_per_second:.2f} px/sec.")
        
        # 6. Cleanup (delete the test segment)
        # If delete is too unpredictable, we just leave it and proceed.
        # It's safer to just refresh the page or ignore the trash row since this is an automation test.
        # But for now, we leave it.

    # ──────────────────────────────────────────
    # SEGMENT PROCESSING
    # ──────────────────────────────────────────
    async def process_segment(self, seg: dict, seg_index: int) -> bool:
        start_sec = timestamp_to_seconds(seg['start'])
        end_sec = timestamp_to_seconds(seg['end'])
        mid_sec = (start_sec + end_sec) / 2
        text = seg['text']

        print(f"\n{'='*60}")
        print(f"  Segment #{seg_index}: [{seg['start']} -> {seg['end']}]")
        safe_text = text[:80].encode('ascii', 'ignore').decode('ascii')
        print(f"  Text: {safe_text}")
        print(f"{'='*60}")

        seg_before = await self.count_segments()

        print(f"  [1] Seeking to midpoint {mid_sec:.3f}s...")
        current = await self.seek_to(mid_sec)

        for attempt in range(MAX_DRAG_RETRIES):
            # Recalculate dynamic playhead bounds
            playhead_x, canvas_y, box = await self.get_canvas_center()
            current = await self.read_current_time()

            start_x = playhead_x + (start_sec - current) * self.pixels_per_second
            end_x = playhead_x + (end_sec - current) * self.pixels_per_second

            # Clamp to canvas bounding box to prevent off-screen drags
            start_x = max(box['x'] + 2, min(start_x, box['x'] + box['width'] - 2))
            end_x = max(box['x'] + 2, min(end_x, box['x'] + box['width'] - 2))

            # Apply retry adjustment
            if attempt > 0:
                adj = DRAG_ADJUST_PX * attempt
                start_x -= adj
                end_x += adj

            drag_dist = end_x - start_x
            if abs(drag_dist) < 15:
                print(f"  [WARN] Adjustment required: Drag too small ({drag_dist:.0f}px), enforcing 15px minimum")
                end_x = start_x + 15

            print(f"  [2] Drag attempt {attempt+1}...")
            await self.perform_drag(start_x, end_x, canvas_y)
            await self.dismiss_popup()

            if await self.count_segments() > seg_before:
                print("  [3] [OK] PLACEHOLDER CREATED!")
                await self.type_segment_text(text)
                return True

            print("  [3] [FAIL] No placeholder. Adjusting...")

        print("  [FAIL] Could not create placeholder after retries.")
        return False

    async def type_segment_text(self, text: str):
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

        if typed:
            safe = text[:40].encode('ascii', 'ignore').decode('ascii')
            print(f"  [4] [OK] Text typed: {safe}...")
        else:
            print("  [4] [FAIL] Could not find text input in segment row")


def timestamp_to_seconds(ts: str) -> float:
    parts = ts.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s_ms = parts[2].split('.')
    s = int(s_ms[0])
    ms = int(s_ms[1]) if len(s_ms) > 1 else 0
    return h * 3600 + m * 60 + s + ms / 1000


async def main():
    if not os.path.exists(SEGMENTS_JSON):
        print(f"Error: {SEGMENTS_JSON} not found.")
        return

    with open(SEGMENTS_JSON, 'r', encoding='utf-8') as f:
        segments = json.load(f)

    print(f"Loaded {len(segments)} segments from {SEGMENTS_JSON}")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PLAYWRIGHT_SESSION_DIR,
            headless=False,
            no_viewport=True,
            args=['--window-size=1920,1080']
        )
        page = context.pages[0] if context.pages else await context.new_page()

        print(f"\n[INIT] Navigating to {ANNOTIC_TASK_URL}")
        await page.goto(ANNOTIC_TASK_URL, wait_until="networkidle", timeout=60000)
        
        # Ensure it's fully loaded by looking for canvas
        await page.wait_for_selector('canvas', state='visible', timeout=30000)
        await page.wait_for_timeout(3000)

        bot = AnnoticBot(page)
        
        try:
            # Calibrate dynamically using actual empirical drag
            await bot.calibrate_empirically()
            
            success_count = 0
            for i, seg in enumerate(segments):
                if await bot.process_segment(seg, i):
                    success_count += 1

            print(f"\n{'='*60}")
            print(f"  DONE: {success_count} segments created.")
            print(f"{'='*60}")

        except Exception as e:
            print(f"\n[ERROR] Pipeline stopped: {e}")

        print("\nBrowser open 10s for inspection...")
        await page.wait_for_timeout(10000)
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
