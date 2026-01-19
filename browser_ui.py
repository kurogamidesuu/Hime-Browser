import tkinter
from constants import HEIGHT, WIDTH, VSTEP, SCROLL_STEP
from dom import HTMLParser, Text, tree_to_list
from css import DEFAULT_STYLE_SHEET, CSSParser, style, cascade_priority
from layout import Element, DocumentLayout, paint_tree, Rect, get_font
from draw import DrawLine, DrawOutline, DrawRect, DrawText
from network import URL
from js import JSContext
import urllib.parse
import dukpy

class Browser:
  def __init__(self):
    self.width = WIDTH
    self.height = HEIGHT
    self.window = tkinter.Tk()
    self.canvas = tkinter.Canvas(
      self.window,
      width=self.width,
      height=self.height,
      bg="white"
    )
    self.canvas.pack(
      fill="both",
      expand=1
    )
    self.window.bind("<Down>", self.handle_down)
    self.window.bind("<Up>", self.handle_up)
    self.window.bind("<MouseWheel>", self.handle_scroll_with_mouse)
    self.window.bind("<Configure>", self.handle_resize)
    self.window.bind("<Button-1>", self.handle_click)
    self.window.bind("<Key>", self.handle_key)
    self.window.bind("<Return>", self.handle_enter)
    self.tabs = []
    self.active_tab = None
    self.chrome = Chrome(self)
    self.focus = None

  def handle_enter(self, e):
    self.chrome.enter()
    self.draw()

  def handle_key(self, e):
    if len(e.char) == 0: return
    if not (0x20 <= ord(e.char) < 0x7f): return
    if self.chrome.keypress(e.char):
      self.draw()
    elif self.focus == "content":
      self.active_tab.keypress(e.char)
      self.draw()

  def handle_down(self, e):
    self.active_tab.scrolldown()
    self.draw()

  def handle_up(self, e):
    self.active_tab.scrollup()
    self.draw()

  def handle_scroll_with_mouse(self, e):
    self.active_tab.scroll_with_mouse(e.delta)
    self.draw()

  def handle_resize(self, e):
    if e.widget == self.window:
      self.width = e.width
      self.height = e.height
      if self.active_tab:
        self.active_tab.handle_resize(self.width, self.height, self.chrome.bottom)
      self.draw()

  def handle_click(self, e):
    if e.y < self.chrome.bottom:
      self.focus = None
      self.chrome.click(e.x, e.y)
    else:
      self.focus = "content"
      self.chrome.blur()
      tab_y = e.y - self.chrome.bottom
      self.active_tab.click(e.x, tab_y)
    self.draw()

  def draw(self):
    self.canvas.delete("all")
    self.active_tab.draw(self.canvas, self.chrome.bottom)
    for cmd in self.chrome.paint():
      cmd.execute(0, self.canvas)

  def new_tab(self, url):
    new_tab = Tab(self.height - self.chrome.bottom, self.height, self.width)
    new_tab.load(url)
    self.active_tab = new_tab
    self.tabs.append(new_tab)
    self.draw()

class Tab:
  def __init__(self, tab_height, h, w):
    self.url = None
    self.tab_height = tab_height
    self.history = []
    self.focus = None
    self.width = w
    self.height = h
    self.scroll = 0

  def draw(self, canvas, offset):
    for cmd in self.display_list:
      if cmd.rect.top > self.scroll + self.tab_height:
        continue
      if cmd.rect.bottom < self.scroll: continue
      cmd.execute(self.scroll - offset, canvas)
  
  def go_back(self):
    if len(self.history) > 1:
      self.history.pop()
      back = self.history.pop()
      self.load(back)

  def load(self, url, payload=None):
    headers, body = url.request(self.url, payload)
    self.scroll = 0
    self.url = url
    self.history.append(url)

    self.allowed_origins = None
    if "content-security-policy" in headers:
      csp = headers["content-security-policy"].split()
      if len(csp) > 0 and csp[0] == "default-src":
        self.allowed_origins = []
        for origin in csp[1:]:
          self.allowed_origins.append(URL(origin).origin())

    self.nodes = HTMLParser(body).parse()
    
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
      self.js.run(script_url, body)

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
    self.render()

  def allowed_request(self, url):
    return self.allowed_origins == None or url.origin() in self.allowed_origins

  def render(self):
    style(self.nodes, sorted(self.rules, key=cascade_priority))
    self.document = DocumentLayout(self.nodes, self.height, self.width)
    self.document.layout()
    self.display_list = []
    paint_tree(self.document, self.display_list)
  
  def scrolldown(self):
    max_y = max(self.document.height + 2*VSTEP - self.tab_height, 0)
    self.scroll = min(self.scroll + SCROLL_STEP, max_y)

  def scrollup(self):
    if self.scroll <= 0:
      return
    self.scroll -= SCROLL_STEP
  
  def scroll_with_mouse(self, delta):
    if delta < 0:
      self.scrolldown()
    else:
      self.scrollup()

  def handle_resize(self, width, height, chrome_height):
    self.width = width
    self.height = height
    self.tab_height = height - chrome_height

    self.document = DocumentLayout(self.nodes, height, width)
    self.document.layout()
    self.total_height = self.document.height + 2*VSTEP
    self.display_list = []
    paint_tree(self.document, self.display_list)
  
  def click(self, x, y):
    if self.focus:
      self.focus.is_focused = False
    self.focus = None
    y += self.scroll
    objs = [obj for obj in tree_to_list(self.document, [])
            if obj.x <= x < obj.x + obj.width
            and obj.y <= y < obj.y + obj.height]
    if not objs: return self.render()
    elt = objs[-1].node
    while elt:
      if isinstance(elt, Text):
        pass
      elif elt.tag == "a" and "href" in elt.attributes:
        if self.js.dispatch_event("click", elt): return
        url = self.url.resolve(elt.attributes["href"])
        return self.load(url)
      elif elt.tag == "input":
        if self.js.dispatch_event("click", elt): return
        elt.attributes["value"] = ""
        if self.focus:
          self.focus.is_focused = False
        self.focus = elt
        elt.is_focused = True
        return self.render()
      elif elt.tag == "button":
        if self.js.dispatch_event("click", elt): return
        while elt.parent:
          if elt.tag == "form" and "action" in elt.attributes:
            return self.submit_form(elt)
          elt = elt.parent
      elt = elt.parent
    self.render()

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
      self.render()

  def __repr__(self):
    return "Tab(history={})".format(self.history)

class Chrome:
  def __init__(self, browser):
    self.browser = browser
    self.font = get_font(12, "normal", "roman")
    self.font_height = self.font.metrics("linespace")
    self.padding = 5
    self.tabbar_top = 0
    self.tabbar_bottom = self.font_height + 2*self.padding
    plus_width = self.font.measure("+") + 2*self.padding
    self.newtab_rect = Rect(
      self.padding, self.padding,
      self.padding + plus_width,
      self.padding + self.font_height
    )
    self.urlbar_top = self.tabbar_bottom
    self.urlbar_bottom = self.urlbar_top + self.font_height + 2*self.padding
    self.bottom = self.urlbar_bottom
    back_width = self.font.measure("<") + 2*self.padding
    self.back_rect = Rect(
      self.padding,
      self.urlbar_top + self.padding,
      self.padding + back_width,
      self.urlbar_bottom - self.padding
    )
    self.address_rect = Rect(
      self.back_rect.right + self.padding,
      self.urlbar_top + self.padding,
      WIDTH - self.padding,
      self.urlbar_bottom - self.padding
    )
    self.focus = None
    self.address_bar = ""

  def tab_rect(self, i):
    tabs_start = self.newtab_rect.right + self.padding
    tab_width = self.font.measure("Tab X") + 2*self.padding
    return Rect(
      tabs_start + tab_width * i, self.tabbar_top,
      tabs_start + tab_width * (i + 1), self.tabbar_bottom
    )
  
  def paint(self):
    cmds = []
    cmds.append(DrawRect(Rect(0, 0, self.browser.width, self.bottom), "white"))
    cmds.append(DrawLine(0, self.bottom, self.browser.width, self.bottom, "black", 1))

    cmds.append(DrawOutline(self.newtab_rect, "black", 1))
    cmds.append(DrawText(
      self.newtab_rect.left + self.padding,
      self.newtab_rect.top,
      "+", self.font, "black"
    ))

    for i, tab in enumerate(self.browser.tabs):
      bounds = self.tab_rect(i)
      cmds.append(DrawLine(
        bounds.left, 0, bounds.left, bounds.bottom, "black", 1
      ))
      cmds.append(DrawLine(
        bounds.right, 0, bounds.right, bounds.bottom, "black", 1
      ))
      cmds.append(DrawText(
        bounds.left + self.padding, bounds.top + self.padding,
        "Tab {}".format(i), self.font, "black"
      ))
      if tab == self.browser.active_tab:
        cmds.append(DrawLine(0, bounds.bottom, bounds.left, bounds.bottom, "black", 1))
        cmds.append(DrawLine(bounds.right, bounds.bottom, self.browser.width, bounds.bottom, "black", 1))
    
    cmds.append(DrawOutline(self.back_rect, "black", 1))
    cmds.append(DrawText(
      self.back_rect.left + self.padding,
      self.back_rect.top,
      "<", self.font, "black"
    ))
    
    self.address_rect = Rect(
      self.back_rect.right + self.padding,
      self.urlbar_top + self.padding,
      self.browser.width - self.padding,
      self.urlbar_bottom - self.padding
    )

    cmds.append(DrawOutline(self.address_rect, "black", 1))
    
    if self.focus == "address bar":
      cmds.append(DrawText(
        self.address_rect.left + self.padding,
        self.address_rect.top,
        self.address_bar, self.font, "black"
      ))
      w = self.font.measure(self.address_bar)
      cmds.append(DrawLine(
        self.address_rect.left + self.padding + w,
        self.address_rect.top,
        self.address_rect.left + self.padding + w,
        self.address_rect.bottom,
        "red", 1
      ))
    else:
      url = str(self.browser.active_tab.url)
      cmds.append(DrawText(
        self.address_rect.left + self.padding,
        self.address_rect.top,
        url, self.font, "black"
      ))
    return cmds
  
  
  def click(self, x, y):
    self.focus = None
    if self.newtab_rect.contains_point(x, y):
      self.browser.new_tab(URL("https://browser.engineering/"))
    elif self.back_rect.contains_point(x, y):
      self.browser.active_tab.go_back()
    elif self.address_rect.contains_point(x, y):
      self.focus = "address bar"
      self.address_bar = ""
    else:
      for i, tab in enumerate(self.browser.tabs):
        if self.tab_rect(i).contains_point(x, y):
          self.browser.active_tab = tab
          break

  def keypress(self, char):
    if self.focus == "address bar":
      self.address_bar += char
      return True
    return False

  def enter(self):
    if self.focus == "address bar":
      self.browser.active_tab.load(URL(self.address_bar))
      self.focus = None
  
  def blur(self):
    self.focus = None