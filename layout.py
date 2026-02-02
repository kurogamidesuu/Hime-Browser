import skia
from constants import WIDTH, BLOCK_ELEMENTS, HSTEP, VSTEP, INPUT_WIDTH_PX, IFRAME_HEIGHT_PX, IFRAME_WIDTH_PX
from dom import Text, Element
from draw import get_font, DrawRRect, DrawText, DrawLine, linespace, Blend, Transform, paint_outline, DrawImage, font
from css import parse_transform, parse_outline

def print_composited_layers(composited_layers):
  print("Composited layers:")
  for layer in composited_layers:
    print("  " * 4 + str(layer))

def add_parent_pointers(nodes, parent=None):
  for node in nodes:
    node.parent = parent
    add_parent_pointers(node.children, node)

def paint_tree(layout_object, display_list):
  cmds = layout_object.paint()

  if isinstance(layout_object, IframeLayout) and layout_object.node.frame and layout_object.node.frame.loaded:
    paint_tree(layout_object.node.frame.document, cmds)
  else:
    for child in layout_object.children:
      paint_tree(child, cmds)

  cmds = layout_object.paint_effects(cmds)
  display_list.extend(cmds)

def paint_visual_effects(node, cmds, rect):
  opacity = float(node.style.get("opacity", "1.0"))
  blend_mode = node.style.get("mix-blend-mode")
  translation = parse_transform(node.style.get("transform", ""))

  if node.style.get("overflow", "visible") == "clip":
    border_radius = float(node.style.get("border-radius", "0px")[:-2])
    if not blend_mode:
      blend_mode = "source-over"
    cmds.append(Blend(1.0, "destination-in", None, [
      DrawRRect(rect, border_radius, "white")
    ]))

  blend_op = Blend(opacity, blend_mode, node, cmds)
  node.blend_op = blend_op
  return [Transform(translation, rect, node, [blend_op])]

def dpx(css_px, zoom):
  return css_px * zoom

class DocumentLayout:
  def __init__(self, node, frame):
    self.node = node
    self.frame = frame
    node.layout_object = self
    self.parent = None
    self.previous = None
    self.children = []

  def layout(self, width, zoom):
    self.zoom = zoom
    child = BlockLayout(self.node, self, None, self.frame)
    self.children.append(child)

    self.width = width - 2*dpx(HSTEP, self.zoom)
    self.x = dpx(HSTEP, self.zoom)
    self.y = dpx(VSTEP, self.zoom)
    child.layout()
    self.height = child.height
  
  def paint(self):
    return []
  
  def should_paint(self):
    return True
  
  def paint_effects(self, cmds):
    if self.frame != self.frame.tab.root_frame and self.frame.scroll != 0:
      rect = skia.Rect.MakeLTRB(
        self.x, self.y,
        self.x + self.width, self.y + self.height
      )
      cmds = [Transform((0, - self.frame.scroll), rect, self.node, cmds)]
    return cmds

class BlockLayout:
  def __init__(self, node, parent, previous, frame):
    self.node = node
    node.layout_object = self
    self.frame = frame
    self.parent = parent
    self.previous = previous
    self.children = []
    self.x = None
    self.y = None
    self.width = None
    self.height = None

  def layout(self):
    self.zoom = self.parent.zoom
    self.width = self.parent.width
    self.x = self.parent.x

    if self.previous:
      self.y = self.previous.y + self.previous.height
    else:
      self.y = self.parent.y

    mode = self.layout_mode()
    if mode == "block":
      previous = None
      for child in self.node.children:
        next = BlockLayout(child, self, previous, self.frame)
        self.children.append(next)
        previous = next
    else:
      self.new_line()
      self.recurse(self.node)
    
    for child in self.children:
      child.layout()

    self.height = sum([child.height for child in self.children])

  def layout_mode(self):
    if isinstance(self.node, Text):
      return "inline"
    elif self.node.children:
      for child in self.node.children:
        if isinstance(child, Text): continue
        if child.tag in BLOCK_ELEMENTS:
          return "block"
      return "inline"
    elif self.node.tag in ["input", "img", "iframe"]:
      return "inline"
    else:
      return "block"

  def recurse(self, node):
    if isinstance(node, Text):
      for word in node.text.split():
        self.word(node, word)
    else:
      if node.tag == "br":
        self.new_line()
      elif node.tag == "input" or node.tag == "button":
        self.input(node)
      elif node.tag == "img":
        self.image(node)
      elif node.tag == "iframe" and "src" in node.attributes:
        self.iframe(node)
      else:
        for child in node.children:
          self.recurse(child)

  def flush(self): pass

  def word(self, node, word):
    node_font = font(node.style, self.zoom)
    w = node_font.measureText(word)
    self.add_inline_child(node, w, TextLayout, self.frame, word)
  
  def image(self, node):
    if "width" in node.attributes:
      w = dpx(int(node.attributes["width"]), self.zoom)
    else:
      w = dpx(node.image.width(), self.zoom)
    self.add_inline_child(node, w, ImageLayout, self.frame)
  
  def iframe(self, node):
    if "width" in node.attributes:
      w = dpx(int(node.attributes["width"]), self.zoom)
    else:
      w = IFRAME_WIDTH_PX + dpx(2, self.zoom)
    self.add_inline_child(node, w, IframeLayout, self.frame)
  
  def new_line(self):
    self.cursor_x = self.x
    last_line = self.children[-1] if self.children else None
    new_line = LineLayout(self.node, self, last_line)
    self.children.append(new_line)
  
  def self_rect(self):
    return skia.Rect.MakeLTRB(self.x, self.y, self.x + self.width, self.y + self.height)

  def paint(self):
    cmds = []
    bgcolor = self.node.style.get("background-color", "transparent")

    if bgcolor != "transparent":
      radius = dpx(float(
        self.node.style.get("border-radius", "0px")[:-2]),
        self.zoom
      )
      cmds.append(DrawRRect(
        self.self_rect(), radius, bgcolor
      ))
    return cmds
  
  def input(self, node):
    w = dpx(INPUT_WIDTH_PX, self.zoom)
    self.add_inline_child(node, w, InputLayout, self.frame)

  def should_paint(self):
    return isinstance(self.node, Text) or (self.node.tag not in ["input", "button", "img", "iframe"])
  
  def paint_effects(self, cmds):
    cmds = paint_visual_effects(
      self.node, cmds, self.self_rect()
    )
    return cmds
  
  def add_inline_child(self, node, w, child_class, frame, word=None):
    if self.cursor_x + w > self.x + self.width:
      self.new_line()
    line = self.children[-1]
    previous_word = line.children[-1] if line.children else None
    if word:
      child = child_class(node, word, line, previous_word)
    else:
      child = child_class(node, line, previous_word, frame)
    line.children.append(child)
    self.cursor_x += w + font(node.style, self.zoom).measureText(" ")

class LineLayout:
  def __init__(self, node, parent, previous):
    self.node = node
    self.parent = parent
    self.previous = previous
    self.children = []
    self.x = None
    self.y = None
    self.height = None
    self.width = None

  def layout(self):
    self.zoom = self.parent.zoom
    self.width = self.parent.width
    self.x = self.parent.x

    if self.previous:
      self.y = self.previous.y + self.previous.height
    else:
      self.y = self.parent.y
    
    for word in self.children:
      word.layout()

    if not self.children:
      self.height = 0
      return
    
    max_ascent = max([-child.ascent
                  for child in self.children])
    baseline = self.y + max_ascent
    for child in self.children:
      if isinstance(child, TextLayout):
        child.y = baseline + child.ascent / 1.25
      else:
        child.y = baseline + child.ascent
    max_descent = max([child.descent
                for child in self.children])
    self.height = max_ascent + max_descent
  
  def paint(self):
    return []
  
  def __repr__(self):
    return "LineLayout(x={}, y={}, width={}, height={})".format(self.x, self.y, self.width, self.height)

  def should_paint(self):
    return True
  
  def self_rect(self):
    return skia.Rect.MakeLTRB(
      self.x, self.y, self.x + self.width, self.y + self.height
    )
  
  def paint_effects(self, cmds):
    outline_rect = skia.Rect.MakeEmpty()
    outline_node = None
    for child in self.children:
      outline_str = child.node.parent.style.get("outline")
      if parse_outline(outline_str):
        outline_rect.join(child.self_rect())
        outline_node = child.node.parent
    if outline_node:
      paint_outline(outline_node, cmds, outline_rect, self.zoom)
    return cmds

class TextLayout:
  def __init__(self, node, word, parent, previous):
    self.node = node
    self.parent = parent
    self.previous = previous
    self.children = []
    self.word = word
    self.x = None
    self.y = None
    self.width = None
    self.height = None
    self.font = None

  def layout(self):
    self.zoom = self.parent.zoom
    self.font = font(self.node.style, self.zoom)

    self.width = self.font.measureText(self.word)

    if self.previous:
      space = self.previous.font.measureText(" ")
      self.x = self.previous.x + space + self.previous.width
    else:
      self.x = self.parent.x

    self.height = linespace(self.font)
    self.ascent = self.font.getMetrics().fAscent * 1.25
    self.descent = self.font.getMetrics().fDescent * 1.25
  
  def paint(self):
    cmds = []
    color = self.node.style["color"]
    cmds.append(DrawText(self.x, self.y, self.word, self.font, color))
    return cmds
  
  def self_rect(self):
    return skia.Rect.MakeLTRB(
      self.x, self.y, self.x + self.width, self.y + self.height
    )
  
  def __repr__(self):
    return ("TextLayout(x={}, y={}, width={}, height={}, word={})").format(self.x, self.y, self.width, self.height, self.word)
  
  def should_paint(self):
    return True
  
  def paint_effects(self, cmds):
    return cmds

class EmbedLayout:
  def __init__(self, node, parent, previous, frame):
    self.node = node
    self.frame = frame
    node.layout_object = self
    self.parent = parent
    self.previous = previous
    self.children = []
    self.x = None
    self.y = None
    self.width = None
    self.height = None
    self.font = None
  
  def layout(self):
    self.zoom = self.parent.zoom
    self.font = font(self.node.style, self.zoom)
    if self.previous:
      space = self.previous.font.measureText(" ")
      self.x = self.previous.x + space + self.previous.width
    else:
      self.x = self.parent.x
    
  def should_paint(self):
    return True
  
class InputLayout(EmbedLayout):
  def __init__(self, node, parent, previous, frame):
    super().__init__(node, parent, previous, frame)

  def layout(self):
    super().layout()
    self.width = dpx(INPUT_WIDTH_PX, self.zoom)
    self.height = linespace(self.font)
    self.ascent = -self.height
    self.descent = 0

  def self_rect(self):
    return skia.Rect.MakeLTRB(self.x, self.y, self.x + self.width, self.y + self.height)

  def paint(self):
    cmds = []
    bgcolor = self.node.style.get("background-color", "transparent")

    if bgcolor != "transparent":
      radius = dpx(float(
        self.node.style.get("border-radius", "0px")[:-2]), self.zoom)
      cmds.append(DrawRRect(self.self_rect(), radius, bgcolor))

    if self.node.tag == "input":
      text = self.node.attributes.get("value", "")
    elif self.node.tag == "button":
      if len(self.node.children) == 1 and isinstance(self.node.children[0], Text):
        text = self.node.children[0].text
      else:
        print("HTML inside button not implemented yet")
        text = ""
    color = self.node.style["color"]
    cmds.append(
      DrawText(self.x, self.y, text, self.font, color)
    )

    if self.node.is_focused and self.node.tag == "input":
      cx = self.x + self.font.measureText(text)
      cmds.append(DrawLine(cx, self.y, cx, self.y + self.height, color, 1))

    return cmds
  
  def paint_effects(self, cmds):
    cmds = paint_visual_effects(self.node, cmds, self.self_rect())
    paint_outline(self.node, cmds, self.self_rect(), self.zoom)
    return cmds

class ImageLayout(EmbedLayout):
  def __init__(self, node, parent, previous, frame):
    super().__init__(node, parent, previous, frame)

  def layout(self):
    super().layout()
    width_attr = self.node.attributes.get("width")
    height_attr = self.node.attributes.get("height")
    image_width = self.node.image.width()
    image_height = self.node.image.height()
    aspect_ratio = image_width / image_height

    if width_attr and height_attr:
      self.width = dpx(int(width_attr), self.zoom)
      self.img_height = dpx(int(height_attr), self.zoom)
    elif width_attr:
      self.width = dpx(int(width_attr), self.zoom)
      self.img_height = self.width / aspect_ratio
    elif height_attr:
      self.img_height = dpx(int(height_attr), self.zoom)
      self.width = self.img_height * aspect_ratio
    else:
      self.width = dpx(image_width, self.zoom)
      self.img_height = dpx(image_height, self.zoom)
    self.height = max(self.img_height, linespace(self.font))
    self.ascent = -self.height
    self.descent = 0

  def paint(self):
    cmds = []
    rect = skia.Rect.MakeLTRB(
      self.x, self.y + self.height - self.img_height,
      self.x + self.width, self.y + self.height
    )
    quality = self.node.style.get("image-rendering", "auto")
    cmds.append(DrawImage(self.node.image, rect, quality))
    return cmds
  
  def paint_effects(self, cmds):
    return cmds

class IframeLayout(EmbedLayout):
  def __init__(self, node, parent, previous, parent_frame):
    super().__init__(node, parent, previous, parent_frame)
  
  def layout(self):
    super().layout()

    width_attr = self.node.attributes.get("width")
    height_attr = self.node.attributes.get("height")

    if width_attr:
      self.width = dpx(int(width_attr) + 2, self.zoom)
    else:
      self.width = dpx(IFRAME_WIDTH_PX + 2, self.zoom)

    if height_attr:
      self.height = dpx(int(height_attr) + 2, self.zoom)
    else:
      self.height = dpx(IFRAME_HEIGHT_PX + 2, self.zoom)

    if self.node.frame and self.node.frame.loaded:
      self.node.frame.frame_height = self.height - dpx(2, self.zoom)
      self.node.frame.frame_width = self.width - dpx(2, self.zoom)
  
    self.ascent = -self.height
    self.descent = 0

  def paint(self):
    cmds = []

    rect = skia.Rect.MakeLTRB(
      self.x, self.y,
      self.x + self.width, self.y + self.height
    )
    bgcolor = self.node.style.get("background-color", "transparent")
    if bgcolor != "transparent":
      radius = dpx(float(
        self.node.style.get("border-radius", "0px")[:-2]), self.zoom
      )
      cmds.append(DrawRRect(rect, radius, bgcolor))
    return cmds

  def paint_effects(self, cmds):
    rect = skia.Rect.MakeLTRB(self.x, self.y, self.x + self.width, self.y + self.height)
    diff = dpx(1, self.zoom)
    offset = (self.x + diff, self.y + diff)
    cmds = [Transform(offset, rect, self.node, cmds)]
    inner_rect = skia.Rect.MakeLTRB(
      self.x + diff, self.y + diff,
      self.x + self.width - diff, self.y + self.height - diff
    )
    internal_cmds = cmds
    internal_cmds.append(Blend(1.0, "destination-in", None, [DrawRRect(inner_rect, 0, "white")]))
    cmds = [Blend(1.0, "source-over", self.node, internal_cmds)]
    paint_outline(self.node, cmds, rect, self.zoom)
    cmds = paint_visual_effects(self.node, cmds, rect)
    return cmds