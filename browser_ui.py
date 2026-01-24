import sdl2
import skia
import urllib.parse
import math
import threading
import OpenGL.GL
from constants import HEIGHT, WIDTH, VSTEP, SCROLL_STEP, REFRESH_RATE_SEC
from dom import HTMLParser, Text, tree_to_list, print_tree
from css import DEFAULT_STYLE_SHEET, CSSParser, style, cascade_priority, absolute_bounds_for_obj
from layout import Element, DocumentLayout, paint_tree, get_font, add_parent_pointers
from draw import DrawLine, DrawOutline, DrawText, linespace, PaintCommand, CompositedLayer, DrawCompositedLayer, Blend, local_to_absolute
from network import URL
from js import JSContext
from task import TaskRunner, Task, MeasureTime, CommitData

class Browser:
  def __init__(self):
    self.chrome = Chrome(self)

    self.sdl_window = sdl2.SDL_CreateWindow(b"Browser",
      sdl2.SDL_WINDOWPOS_CENTERED,
      sdl2.SDL_WINDOWPOS_CENTERED,
      WIDTH, HEIGHT,
      sdl2.SDL_WINDOW_SHOWN | sdl2.SDL_WINDOW_OPENGL)
    
    sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MAJOR_VERSION, 3)
    sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MINOR_VERSION, 2)
    sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_FORWARD_COMPATIBLE_FLAG, True)
    sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_PROFILE_MASK, sdl2.SDL_GL_CONTEXT_PROFILE_CORE)

    self.gl_context = sdl2.SDL_GL_CreateContext(self.sdl_window)
    print(("OpenGL initiallized: vendor={}, renderer={}").format(OpenGL.GL.glGetString(OpenGL.GL.GL_VENDOR), OpenGL.GL.glGetString(OpenGL.GL.GL_RENDERER)))

    self.skia_context = skia.GrDirectContext.MakeGL()

    self.root_surface = skia.Surface.MakeFromBackendRenderTarget(
      self.skia_context,
      skia.GrBackendRenderTarget(
        WIDTH, HEIGHT, 0, 0,
        skia.GrGLFramebufferInfo(
            0, OpenGL.GL.GL_RGBA8)),
        skia.kBottomLeft_GrSurfaceOrigin,
        skia.kRGBA_8888_ColorType,
        skia.ColorSpace.MakeSRGB())
    assert self.root_surface is not None

    self.chrome_surface = skia.Surface.MakeRenderTarget(
      self.skia_context, skia.Budgeted.kNo,
      skia.ImageInfo.MakeN32Premul(WIDTH, math.ceil(self.chrome.bottom))
    )
    assert self.chrome_surface is not None
    
    self.tabs = []
    self.active_tab = None
    self.focus = None
    self.address_bar = ""
    self.lock = threading.Lock()
    self.active_tab_url = None
    self.active_tab_scroll = 0

    self.measure = MeasureTime()
    threading.current_thread().name = "Browser thread"

    if sdl2.SDL_BYTEORDER == sdl2.SDL_BIG_ENDIAN:
      self.RED_MASK = 0xff000000
      self.GREEN_MASK = 0x00ff0000
      self.BLUE_MASK = 0x0000ff00
      self.ALPHA_MASK = 0x000000ff
    else:
      self.RED_MASK = 0x000000ff
      self.GREEN_MASK = 0x0000ff00
      self.BLUE_MASK = 0x00ff0000
      self.ALPHA_MASK = 0xff000000

    self.animation_timer = None

    self.needs_animation_frame = True
    self.needs_composite = False
    self.needs_raster = False
    self.needs_draw = False

    self.active_tab_height = 0
    self.active_tab_display_list = None

    self.composited_updates = {}
    self.composited_layers = []
    self.draw_list = []

  def commit(self, tab, data):
    self.lock.acquire(blocking=True)
    if tab == self.active_tab:
      self.active_tab_url = data.url
      if data.scroll != None:
        self.active_tab_scroll = data.scroll
      self.active_tab_height = data.height
      if data.display_list:
        self.active_tab_display_list = data.display_list
      self.animation_timer = None
      self.composited_updates = data.composited_updates
      if self.composited_updates == None:
        self.composited_updates = {}
        self.set_needs_composite()
      else:
        self.set_needs_draw()
    self.lock.release()

  def handle_quit(self):
    self.measure.finish()
    for tab in self.tabs:
      tab.task_runner.set_needs_quit()
    sdl2.SDL_GL_DeleteContext(self.gl_context)
    sdl2.SDL_DestroyWindow(self.sdl_window)

  def clear_data(self):
    self.active_tab_scroll = 0
    self.active_tab_url = None
    self.display_list = []
    self.composited_layers = []
    self.composited_updates = {}

  def handle_enter(self):
    self.lock.acquire(blocking=True)
    if self.chrome.enter():
      self.set_needs_raster()
    self.lock.release()

  def handle_key(self, char):
    self.lock.acquire(blocking=True)
    if not (0x20 <= ord(char) < 0x7f): return
    if self.chrome.keypress(char):
      self.set_needs_raster()
    elif self.focus == "content":
      task = Task(self.active_tab.keypress, char)
      self.active_tab.task_runner.schedule_task(task)
    self.lock.release()

  def handle_down(self):
    self.lock.acquire(blocking=True)
    if not self.active_tab_height:
      self.lock.release()
      return
    self.active_tab_scroll = self.clamp_scroll(
      self.active_tab_scroll + SCROLL_STEP
    )
    self.set_needs_draw()
    self.needs_animation_frame = True
    self.lock.release()

  def handle_up(self):
    self.lock.acquire(blocking=True)
    if not self.active_tab_height:
      self.lock.release()
      return
    self.active_tab_scroll = self.clamp_scroll(
      self.active_tab_scroll - SCROLL_STEP
    )
    self.set_needs_draw()
    self.needs_animation_frame = True
    self.lock.release()

  def handle_scroll_with_mouse(self, e):
    if e > 0:
      self.handle_up()
    elif e < 0:
      self.handle_down()

  def clamp_scroll(self, scroll):
    height = self.active_tab_height
    maxscroll = height - (HEIGHT - self.chrome.bottom)
    return max(0, min(scroll, maxscroll))

  def handle_click(self, e):
    self.lock.acquire(blocking=True)
    if e.y < self.chrome.bottom:
      self.focus = None
      self.chrome.click(e.x, e.y)
      self.set_needs_raster()
    else:
      if self.focus != "content":
        self.set_needs_raster()
      self.focus = "content"
      self.chrome.blur()
      tab_y = e.y - self.chrome.bottom
      task = Task(self.active_tab.click, e.x, tab_y)
      self.active_tab.task_runner.schedule_task(task)
    self.lock.release() 

  def set_needs_raster(self):
    self.needs_raster = True
    self.needs_draw = True

  def set_needs_composite(self):
    self.needs_composite = True
    self.needs_raster = True
    self.needs_draw = True

  def set_needs_draw(self):
    self.needs_draw = True

  def raster_tab(self):
    for composited_layer in self.composited_layers:
      composited_layer.raster()

  def raster_chrome(self):
    canvas = self.chrome_surface.getCanvas()
    canvas.clear(skia.ColorWHITE)

    for cmd in self.chrome.paint():
      cmd.execute(canvas)

  def draw(self):
    canvas = self.root_surface.getCanvas()
    canvas.clear(skia.ColorWHITE)

    canvas.save()
    canvas.translate(0, self.chrome.bottom - self.active_tab_scroll)
    for item in self.draw_list:
      item.execute(canvas)
    canvas.restore()

    chrome_rect = skia.Rect.MakeLTRB(
        0, 0, WIDTH, self.chrome.bottom)
    canvas.save()
    canvas.clipRect(chrome_rect)
    self.chrome_surface.draw(canvas, 0, 0)
    canvas.restore()

    # skia_image = self.root_surface.makeImageSnapshot()
    # skia_bytes = skia_image.tobytes()

    # depth = 32
    # pitch = 4 * WIDTH
    # sdl_surface = sdl2.SDL_CreateRGBSurfaceFrom(
    #   skia_bytes, WIDTH, HEIGHT, depth, pitch,
    #   self.RED_MASK, self.GREEN_MASK, self.BLUE_MASK, self.ALPHA_MASK
    # )

    # rect = sdl2.SDL_Rect(0, 0, WIDTH, HEIGHT)
    # window_surface = sdl2.SDL_GetWindowSurface(self.sdl_window)
    # sdl2.SDL_BlitSurface(sdl_surface, rect, window_surface, rect)
    # sdl2.SDL_UpdateWindowSurface(self.sdl_window)
    self.root_surface.flushAndSubmit()
    sdl2.SDL_GL_SwapWindow(self.sdl_window)

  def composite_raster_and_draw(self):
    self.lock.acquire(blocking=True)
    if not self.needs_composite and not self.needs_raster and not self.needs_draw:
      self.lock.release()
      return
    
    self.measure.time('composite-raster-and-draw')
    
    if self.needs_composite:
      self.measure.time('composite')
      self.composite()
      self.measure.stop('composite')
    if self.needs_raster:
      self.measure.time('raster')
      self.raster_chrome()
      self.raster_tab()
      self.measure.stop('raster')
    if self.needs_draw:
      self.measure.time('draw')
      self.paint_draw_list()
      self.draw()
      self.measure.stop('draw')
    
    self.measure.stop('composite-raster-and-draw')
    self.needs_composite = False
    self.needs_raster = False
    self.needs_draw = False
    self.lock.release()

  def new_tab(self, url):
    self.lock.acquire(blocking=True)
    self.new_tab_internal(url)
    self.lock.release()

  def new_tab_internal(self, url):
    new_tab = Tab(self, HEIGHT - self.chrome.bottom)
    self.tabs.append(new_tab)
    self.set_active_tab(new_tab)
    self.schedule_load(url)

  def set_active_tab(self, tab):
    self.active_tab = tab
    self.clear_data()
    self.needs_animation_frame = True
    self.animation_timer = None

  def set_needs_animation_frame(self, tab):
    self.lock.acquire(blocking=True)
    if tab == self.active_tab:
      self.needs_animation_frame = True
    self.lock.release()

  def schedule_animation_frame(self):
    def callback():
      self.lock.acquire(blocking=True)
      scroll = self.active_tab_scroll
      self.needs_animation_frame = False
      task = Task(self.active_tab.run_animation_frame, scroll)
      self.active_tab.task_runner.schedule_task(task)
      self.lock.release()

    self.lock.acquire(blocking=True)
    if self.needs_animation_frame and not self.animation_timer:
      self.animation_timer = threading.Timer(REFRESH_RATE_SEC, callback)
      self.animation_timer.start()
    self.lock.release()

  def schedule_load(self, url, body=None):
    self.active_tab.task_runner.clear_pending_tasks()
    task = Task(self.active_tab.load, url, body)
    self.active_tab.task_runner.schedule_task(task)

  def composite(self):
    self.composited_layers = []
    add_parent_pointers(self.active_tab_display_list)
    all_commands = []
    for cmd in self.active_tab_display_list:
      all_commands = tree_to_list(cmd, all_commands)
    
    non_composited_commands = [cmd
      for cmd in all_commands
      if isinstance(cmd, PaintCommand) or not cmd.needs_compositing
      if not cmd.parent or cmd.parent.needs_compositing
    ]

    for cmd in non_composited_commands:
      did_break = False
      for layer in reversed(self.composited_layers):
        if layer.can_merge(cmd):
          layer.add(cmd)
          did_break = True
          break
        elif skia.Rect.Intersects(
          layer.absolute_bounds(),
          local_to_absolute(cmd, cmd.rect)
        ):
          layer = CompositedLayer(self.skia_context, cmd)
          self.composited_layers.append(layer)
          did_break = True
          break
      if not did_break:
        layer = CompositedLayer(self.skia_context, cmd)
        self.composited_layers.append(layer)

    self.active_tab_height = 0
    for layer in self.composited_layers:
      self.active_tab_height = max(self.active_tab_height, layer.absolute_bounds().bottom())

  def paint_draw_list(self):
    new_effects = {}
    self.draw_list = []
    for composited_layer in self.composited_layers:
      current_effect = DrawCompositedLayer(composited_layer)
      if not composited_layer.display_items: continue
      parent = composited_layer.display_items[0].parent
      while parent:
        new_parent = self.get_latest(parent)
        if new_parent in new_effects:
          new_effects[new_parent].children.append(current_effect)
          break
        else:
          current_effect = new_parent.clone(current_effect)
          new_effects[new_parent] = current_effect
          parent = parent.parent
      if not parent:
        self.draw_list.append(current_effect)

  def get_latest(self, effect):
    node = effect.node
    if node not in self.composited_updates:
      return effect
    if not isinstance(effect, Blend):
      return effect
    return self.composited_updates[node]

class Tab:
  def __init__(self, browser, tab_height):
    self.history = []
    self.tab_height = tab_height
    self.focus = None
    self.url = None
    self.scroll = 0
    self.scroll_changed_in_tab = False
    self.needs_raf_callbacks = False
    self.needs_style = False
    self.needs_layout = False
    self.needs_paint = False
    self.js = None
    self.browser = browser
    self.loaded = False
    self.task_runner = TaskRunner(self)
    self.task_runner.start_thread()

    self.composited_updates = []

  def raster(self, canvas):
    for cmd in self.display_list:
      cmd.execute(canvas)
  
  def go_back(self):
    if len(self.history) > 1:
      self.history.pop()
      back = self.history.pop()
      self.load(back)

  def load(self, url, payload=None):
    self.scroll = 0
    self.scroll_changed_in_tab = True
    self.task_runner.clear_pending_tasks()
    headers, body = url.request(self.url, payload)
    self.url = url
    self.history.append(url)

    self.allowed_origins = None
    if "content-security-policy" in headers:
      csp = headers["content-security-policy"].split()
      if len(csp) > 0 and csp[0] == "default-src":
        self.allowed_origins = csp[1:]

    self.nodes = HTMLParser(body).parse()
    
    if self.js: self.js.discarded = True
    self.js = JSContext(self)
    scripts = [node.attributes["src"]
               for node in tree_to_list(self.nodes, [])
               if isinstance(node, Element)
               and node.tag == "script"
               and "src" in node.attributes]
    
    for script in scripts:
      script_url = url.resolve(script)
      if not self.allowed_request(script_url):
        print("Blocked script", script, "due to CSP")
        continue

      try:
        header, body = script_url.request(url)
      except:
        continue
      task = Task(self.js.run, script_url, body)
      self.task_runner.schedule_task(task)

    self.rules = DEFAULT_STYLE_SHEET.copy()
    links = [node.attributes["href"]
             for node in tree_to_list(self.nodes, [])
             if isinstance(node, Element)
             and node.tag == "link"
             and node.attributes.get("rel") == "stylesheet"
             and "href" in node.attributes]
    for link in links:
      style_url = url.resolve(link)
      if not self.allowed_request(style_url):
        print("Blocked style", link, "due to CSP")
        continue

      try:
        header, body = style_url.request(url)
      except:
        continue
      self.rules.extend(CSSParser(body).parse())
    self.set_needs_render()

  def allowed_request(self, url):
    return self.allowed_origins == None or url.origin() in self.allowed_origins

  def set_needs_render(self):
    self.needs_style = True
    self.browser.set_needs_animation_frame(self)

  def set_needs_layout(self):
    self.needs_layout = True
    self.browser.set_needs_animation_frame(self)

  def set_needs_paint(self):
    self.needs_paint = True
    self.browser.set_needs_animation_frame(self)

  def render(self):
    self.browser.measure.time('render')

    if self.needs_style:
      style(self.nodes, sorted(self.rules, key=cascade_priority), self)
      self.needs_layout = True
      self.needs_style = False

    if self.needs_layout:
      self.document = DocumentLayout(self.nodes)
      self.document.layout()
      self.needs_paint = True
      self.needs_layout = False

    if self.needs_paint:
      self.display_list = []
      paint_tree(self.document, self.display_list)
      self.needs_paint = False

    clamped_scroll = self.clamp_scroll(self.scroll)
    if clamped_scroll != self.scroll:
      self.scroll_changed_in_tab = True
    self.scroll = clamped_scroll

    self.browser.measure.stop('render')
  
  def run_animation_frame(self, scroll):
    if not self.scroll_changed_in_tab:
      self.scroll = scroll
    self.browser.measure.time('script-runRAFHandlers')
    self.js.interp.evaljs("__runRAFHandlers()")
    self.browser.measure.stop('script-runRAFHandlers')

    for node in tree_to_list(self.nodes, []):
      for (property_name, animation) in node.animations.items():
        value = animation.animate()
        if value:
          node.style[property_name] = value
          self.composited_updates.append(node)
          self.set_needs_paint()

    needs_composite = self.needs_style or self.needs_layout

    self.render()

    scroll = None
    if self.scroll_changed_in_tab:
      scroll = self.scroll

    composited_updates = None
    if not needs_composite:
      composited_updates = {}
      for node in self.composited_updates:
        composited_updates[node] = node.blend_op
    self.composited_updates = []
    
    document_height = math.ceil(self.document.height + 2*VSTEP)
    commit_data = CommitData(
      self.url, scroll, document_height, self.display_list, composited_updates
    )
    self.display_list = None
    self.scroll_changed_in_tab = False
    self.browser.commit(self, commit_data)

  def clamp_scroll(self, scroll):
    height = math.ceil(self.document.height + 2*VSTEP)
    maxscroll = height - self.tab_height
    return max(0, min(scroll, maxscroll))

  def click(self, x, y):
    self.render()
    self.focus = None
    y += self.scroll
    loc_rect = skia.Rect.MakeXYWH(x, y, 1, 1)
    objs = [obj for obj in tree_to_list(self.document, [])
            if absolute_bounds_for_obj(obj).intersects(loc_rect)]
    if not objs: return
    elt = objs[-1].node
    if elt and self.js.dispatch_event("click", elt): return
    while elt:
      if isinstance(elt, Text):
        pass
      elif elt.tag == "a" and "href" in elt.attributes:
        url = self.url.resolve(elt.attributes["href"])
        self.load(url)
        return
      elif elt.tag == "input":
        elt.attributes["value"] = ""
        if self.focus:
          self.focus.is_focused = False
        self.focus = elt
        elt.is_focused = True
        self.set_needs_render()
        return
      elif elt.tag == "button":
        while elt.parent:
          if elt.tag == "form" and "action" in elt.attributes:
            return self.submit_form(elt)
          elt = elt.parent
      elt = elt.parent

  def submit_form(self, elt):
    if self.js.dispatch_event("submit", elt): return
    inputs = [node for node in tree_to_list(elt, [])
              if isinstance(node, Element)
              and node.tag == "input"
              and "name" in node.attributes]
    body = ""
    for input in inputs:
      name = input.attributes["name"]
      value = input.attributes.get("value", "")
      name = urllib.parse.quote(name)
      value = urllib.parse.quote(value)
      body += "&" + name + "=" + value
    body = body[1:]

    url = self.url.resolve(elt.attributes["action"])
    self.load(url, body)
  
  def keypress(self, char):
    if self.focus:
      if self.js.dispatch_event("keydown", self.focus): return
      self.focus.attributes["value"] += char
      self.set_needs_render()

  def __repr__(self):
    return "Tab(history={})".format(self.history)

class Chrome:
  def __init__(self, browser):
    self.browser = browser
    self.focus = None
    self.address_bar = ""

    self.font = get_font(12, "normal", "roman")
    self.font_height = linespace(self.font)

    self.padding = 5
    self.tabbar_top = 0
    self.tabbar_bottom = self.font_height + 2*self.padding

    plus_width = self.font.measureText("+") + 2*self.padding
    self.newtab_rect = skia.Rect.MakeLTRB(
      self.padding, self.padding,
      self.padding + plus_width,
      self.padding + self.font_height
    )

    self.urlbar_top = self.tabbar_bottom
    self.urlbar_bottom = self.urlbar_top + self.font_height + 2*self.padding

    back_width = self.font.measureText("<") + 2*self.padding
    self.back_rect = skia.Rect.MakeLTRB(
      self.padding,
      self.urlbar_top + self.padding,
      self.padding + back_width,
      self.urlbar_bottom - self.padding
    )
    self.address_rect = skia.Rect.MakeLTRB(
      self.back_rect.right() + self.padding,
      self.urlbar_top + self.padding,
      WIDTH - self.padding,
      self.urlbar_bottom - self.padding
    )

    self.bottom = self.urlbar_bottom

  def tab_rect(self, i):
    tabs_start = self.newtab_rect.right() + self.padding
    tab_width = self.font.measureText("Tab X") + 2*self.padding
    return skia.Rect.MakeLTRB(
      tabs_start + tab_width * i, self.tabbar_top,
      tabs_start + tab_width * (i + 1), self.tabbar_bottom
    )
  
  def paint(self):
    cmds = []
    cmds.append(DrawLine(0, self.bottom, WIDTH, self.bottom, "black", 1))

    cmds.append(DrawOutline(self.newtab_rect, "black", 1))
    cmds.append(DrawText(
      self.newtab_rect.left() + self.padding,
      self.newtab_rect.top(),
      "+", self.font, "black"
    ))

    for i, tab in enumerate(self.browser.tabs):
      bounds = self.tab_rect(i)
      cmds.append(DrawLine(
        bounds.left(), 0, bounds.left(), bounds.bottom(), "black", 1
      ))
      cmds.append(DrawLine(
        bounds.right(), 0, bounds.right(), bounds.bottom(), "black", 1
      ))
      cmds.append(DrawText(
        bounds.left() + self.padding, bounds.top() + self.padding,
        "Tab {}".format(i), self.font, "black"
      ))

      if tab == self.browser.active_tab:
        cmds.append(DrawLine(0, bounds.bottom(), bounds.left(), bounds.bottom(), "black", 1))
        cmds.append(DrawLine(bounds.right(), bounds.bottom(), WIDTH, bounds.bottom(), "black", 1))
    
    cmds.append(DrawOutline(self.back_rect, "black", 1))
    cmds.append(DrawText(
      self.back_rect.left() + self.padding,
      self.back_rect.top(),
      "<", self.font, "black"
    ))

    cmds.append(DrawOutline(self.address_rect, "black", 1))
    if self.focus == "address bar":
      cmds.append(DrawText(
        self.address_rect.left() + self.padding,
        self.address_rect.top(),
        self.address_bar, self.font, "black"
      ))
      w = self.font.measureText(self.address_bar)
      cmds.append(DrawLine(
        self.address_rect.left() + self.padding + w,
        self.address_rect.top(),
        self.address_rect.left() + self.padding + w,
        self.address_rect.bottom(),
        "red", 1
      ))
    else:
      url = str(self.browser.active_tab_url) if self.browser.active_tab_url else ""
      cmds.append(DrawText(
        self.address_rect.left() + self.padding,
        self.address_rect.top(),
        url, self.font, "black"
      ))
    return cmds
  
  def click(self, x, y):
    if self.newtab_rect.contains(x, y):
      self.browser.new_tab_internal(URL("https://browser.engineering/"))
    elif self.back_rect.contains(x, y):
      task = Task(self.browser.active_tab.go_back)
      self.browser.active_tab.task_runner.schedule_task(task)
    elif self.address_rect.contains(x, y):
      self.focus = "address bar"
      self.address_bar = ""
    else:
      for i, tab in enumerate(self.browser.tabs):
        if self.tab_rect(i).contains(x, y):
          self.browser.set_active_tab(tab)
          active_tab = self.browser.active_tab
          task = Task(active_tab.set_needs_render)
          active_tab.task_runner.schedule_task(task)
          break

  def keypress(self, char):
    if self.focus == "address bar":
      self.address_bar += char
      return True
    return False

  def enter(self):
    if self.focus == "address bar":
      self.browser.schedule_load(URL(self.address_bar))
      self.focus = None
      return True
    return False
  
  def blur(self):
    self.focus = None