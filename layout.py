import skia
from constants import HEIGHT, WIDTH, BLOCK_ELEMENTS, HSTEP, VSTEP, INPUT_WIDTH_PX
from dom import Text, Element
from draw import get_font, DrawRRect, DrawText, DrawLine, linespace, Blend, Transform
from css import parse_transform

def print_composited_layers(composited_layers):
  print("Composited layers:")
  for layer in composited_layers:
    print("  " * 4 + str(layer))

def add_parent_pointers(nodes, parent=None):
  for node in nodes:
    node.parent = parent
    add_parent_pointers(node.children, node)

def paint_tree(layout_object, display_list):
  cmds = []
  if layout_object.should_paint():
    cmds = layout_object.paint()
  for child in layout_object.children:
    paint_tree(child, cmds)

  if layout_object.should_paint():
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

class DocumentLayout:
  def __init__(self, node, h=HEIGHT, w=WIDTH):
    self.node = node
    self.parent = None
    self.children = []

    self.x = None
    self.y = None
    self.width = w
    self.height = h

  def layout(self):
    child = BlockLayout(self.node, self, None, self.height, self.width)
    self.children.append(child)
    self.width = self.width - 2*HSTEP
    self.x = HSTEP
    self.y = VSTEP
    child.layout()

    self.height = child.height
  
  def paint(self):
    return []
  
  def should_paint(self):
    return True
  
  def paint_effects(self, cmds):
    return cmds

class BlockLayout:
  def __init__(self, node, parent, previous, h=HEIGHT, w=WIDTH):
    self.node = node
    self.parent = parent
    self.previous = previous
    self.children = []

    self.x = None
    self.y = None
    self.width = w
    self.height = h

  def layout(self):
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
        next = BlockLayout(child, self, previous)
        self.children.append(next)
        previous = next
    else:
      self.new_line()
      self.recurse(self.node)
    
    for child in self.children:
      child.layout()

    self.height = sum([child.height for child in self.children])

  def layout_intermediate(self):
    previous = None
    for child in self.node.children:
      next = BlockLayout(child, self, previous)
      self.children.append(next)
      previous = next
  
  def layout_mode(self):
    if isinstance(self.node, Text):
      return "inline"
    elif any([isinstance(child, Element) and child.tag in BLOCK_ELEMENTS for child in self.node.children]):
      return "block"
    elif self.node.children or self.node.tag == "input":
      return "inline"
    else:
      return "block"

  # def open_tag(self, tag):
  #   if tag == "i":
  #     self.style = "italic"
  #   elif tag == "b":
  #     self.weight = "bold"
  #   elif tag == "small":
  #     self.size -= 2
  #   elif tag == "big":
  #     self.size += 4
  #   elif tag == "br":
  #     self.flush()
  #   elif tag == "p":
  #     self.new_line()
  #     self.cursor_y += VSTEP
  
  # def close_tag(self, tag):
  #   if tag == "i":
  #     self.style = "roman"
  #   elif tag == "b":
  #     self.weight = "normal"
  #   elif tag == "small":
  #     self.size += 2
  #   elif tag == "big":
  #     self.size -= 4
  #   elif tag == "p":
  #     self.new_line()
  #     self.cursor_y += VSTEP

  def recurse(self, node):
    if isinstance(node, Text):
      for word in node.text.split():
        self.word(node, word)
    else:
      if node.tag == "br":
        self.new_line()
      elif node.tag == "input" or node.tag == "button":
        self.input(node)
      else:
        for child in node.children:
          self.recurse(child)

  def flush(self): pass

  def word(self, node, word):
    weight = node.style["font-weight"]
    style = node.style["font-style"]
    size = int(float(node.style["font-size"][:-2]) * .75)
    font = get_font(size, weight, style)

    word_width = font.measureText(word)
    if self.cursor_x + word_width > self.width:
      self.new_line()
    
    line = self.children[-1]
    previous_word = line.children[-1] if line.children else None
    text = TextLayout(node, word, line, previous_word)
    line.children.append(text)
    self.cursor_x += word_width + font.measureText(" ")
  
  def new_line(self):
    self.cursor_x = 0
    last_line = self.children[-1] if self.children else None
    new_line = LineLayout(self.node, self, last_line)
    self.children.append(new_line)
  
  def self_rect(self):
    return skia.Rect.MakeLTRB(self.x, self.y, self.x + self.width, self.y + self.height)

  def paint(self):
    cmds = []
    bgcolor = self.node.style.get("background-color", "transparent")

    if bgcolor != "transparent":
      radius = float(
        self.node.style.get("border-radius", "0px")[:-2]
      )
      cmds.append(DrawRRect(
        self.self_rect(), radius, bgcolor
      ))
    return cmds
  
  def input(self, node):
    w = INPUT_WIDTH_PX
    if self.cursor_x + w > self.width:
      self.new_line()
    line = self.children[-1]
    previous_word = line.children[-1] if line.children else None
    input = InputLayout(node, line, previous_word)
    line.children.append(input)

    weight = node.style["font-weight"]
    style = node.style["font-style"]
    size = int(float(node.style["font-size"][:-2]) * .75)
    font = get_font(size, weight, style)

    self.cursor_x += w + font.measureText(" ")

  def should_paint(self):
    return isinstance(self.node, Text) or (self.node.tag != "input" and self.node.tag != "button")
  
  def paint_effects(self, cmds):
    cmds = paint_visual_effects(
      self.node, cmds, self.self_rect()
    )
    return cmds

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
    
    max_ascent = max([-word.font.getMetrics().fAscent
                  for word in self.children])
    baseline = self.y + 1.25 * max_ascent
    for word in self.children:
        word.y = baseline + word.font.getMetrics().fAscent
    max_descent = max([word.font.getMetrics().fDescent
                for word in self.children])
    self.height = 1.25 * (max_ascent + max_descent)
  
  def paint(self):
    return []
  
  def __repr__(self):
    return "LineLayout(x={}, y={}, width={}, height={})".format(self.x, self.y, self.width, self.height)

  def should_paint(self):
    return True
  
  def paint_effects(self, cmds):
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
    weight = self.node.style["font-weight"]
    style = self.node.style["font-style"]
    if style == "normal": style = "roman"
    size = int(float(self.node.style["font-size"][:-2]) * .75)
    self.font = get_font(size, weight, style)

    self.width = self.font.measureText(self.word)

    if self.previous:
      space = self.previous.font.measureText(" ")
      self.x = self.previous.x + space + self.previous.width
    else:
      self.x = self.parent.x

    self.height = linespace(self.font)
  
  def paint(self):
    cmds = []
    color = self.node.style["color"]
    cmds.append(DrawText(self.x, self.y, self.word, self.font, color))
    return cmds
  
  def __repr__(self):
    return ("TextLayout(x={}, y={}, width={}, height={}, word={})").format(self.x, self.y, self.width, self.height, self.word)
  
  def should_paint(self):
    return True
  
  def paint_effects(self, cmds):
    return cmds

class InputLayout:
  def __init__(self, node, parent, previous):
    self.node = node
    self.parent = parent
    self.previous = previous
    self.children = []
    self.x = None
    self.y = None
    self.width = None
    self.height = None
    self.font = None

  def layout(self):
    weight = self.node.style["font-weight"]
    style = self.node.style["font-style"]
    if style == "normal": style = "roman"
    size = int(float(self.node.style["font-size"][:-2]) * .75)
    self.font = get_font(size, weight, style)

    self.width = INPUT_WIDTH_PX

    if self.previous:
      space = self.previous.font.measureText(" ")
      self.x = self.previous.x + space + self.previous.width
    else:
      self.x = self.parent.x

    self.height = linespace(self.font)

  def paint(self):
    cmds = []
    bgcolor = self.node.style.get("background-color", "transparent")

    if bgcolor != "transparent":
      radius = float(
        self.node.style.get("border-radius", "0px")[:-2])
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

    if self.node.is_focused:
      cx = self.x + self.font.measureText(text)
      cmds.append(DrawLine(cx, self.y, cx, self.y + self.height, "black", 1))

    return cmds
  
  def should_paint(self):
    return True
  
  def paint_effects(self, cmds):
    return paint_visual_effects(self.node, cmds, self.self_rect())
  
  def self_rect(self):
    return skia.Rect.MakeLTRB(self.x, self.y, self.x + self.width, self.y + self.height)
