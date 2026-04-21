"""
Browser controller — adapted from adcock-agent's playwright_client.py.
Handles DOM capture, ISM extraction, screenshot, and action execution.
"""
import asyncio, base64, json
from pathlib import Path
from playwright.async_api import async_playwright, Page


ISM_SCRIPT = """
() => {
  const toInt = x => Number.isFinite(x) ? Math.round(x) : 0;
  const rectOf = el => { const r = el.getBoundingClientRect(); return {x:toInt(r.left),y:toInt(r.top),w:toInt(r.width),h:toInt(r.height)}; };
  const isVisible = el => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    if (cs.display==='none'||cs.visibility==='hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width>0 && r.height>0;
  };
  const tags = ['a','button','input','select','textarea','[role="button"]','[role="link"]','[tabindex]'];
  const els = [];
  let idx = 0;
  document.querySelectorAll(tags.join(',')).forEach(el => {
    if (!isVisible(el) || idx >= 40) return;
    const id = `n_${String(idx).padStart(6,'0')}`;
    el.setAttribute('data-hint-id', id);
    els.push({
      hintId: id,
      tag: el.tagName.toLowerCase(),
      text: (el.innerText||el.value||el.placeholder||el.getAttribute('aria-label')||'').trim().slice(0,80),
      type: el.type||'',
      rect: rectOf(el),
      href: el.href||''
    });
    idx++;
  });
  return {
    url: location.href,
    title: document.title,
    elements: els,
    bodyText: document.body.innerText.slice(0,2000)
  };
}
"""


class BrowserController:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._page: Page = None

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._page = await self._browser.new_page(viewport={"width": 1280, "height": 720})

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def navigate(self, url: str):
        await self._page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await self._page.wait_for_timeout(500)

    async def get_ism(self) -> dict:
        return await self._page.evaluate(ISM_SCRIPT)

    async def screenshot_b64(self) -> str:
        data = await self._page.screenshot(type="png")
        return base64.b64encode(data).decode()

    async def screenshot_file(self, path: str) -> str:
        await self._page.screenshot(path=path, type="png")
        return path

    async def execute_action(self, action: tuple):
        op = action[0]
        try:
            if op == "click_hint":
                hint_id = action[1]
                el = self._page.locator(f'[data-hint-id="{hint_id}"]').first
                await el.click(timeout=5000)
            elif op == "click_selector":
                await self._page.click(action[1], timeout=5000)
            elif op == "type":
                _, hint_id, text, clear = action
                el = self._page.locator(f'[data-hint-id="{hint_id}"]').first
                if clear:
                    await el.fill(text, timeout=5000)
                else:
                    await el.type(text, timeout=5000)
            elif op == "scroll":
                _, direction, amount = action
                dy = amount if direction == "down" else -amount
                await self._page.evaluate(f"window.scrollBy(0, {dy})")
            elif op == "wait":
                await self._page.wait_for_timeout(action[1])
            elif op == "sleep":
                await asyncio.sleep(action[1] / 1000)
            elif op == "press":
                for key in action[1]:
                    await self._page.keyboard.press(key)
        except Exception as e:
            return str(e)
        return None

    @property
    def page(self):
        return self._page
