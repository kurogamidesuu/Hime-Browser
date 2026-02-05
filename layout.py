import skia
from constants import BLOCK_ELEMENTS, HSTEP, VSTEP, INPUT_WIDTH_PX, IFRAME_HEIGHT_PX, IFRAME_WIDTH_PX, CSS_PROPERTIES
from dom import Text, tree_to_list
from draw import DrawRRect, DrawText, linespace, Blend, Transform, paint_outline, DrawImage, font, DrawCursor
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
    if isinstance(layout_object.children, ProtectedField):
      for child in layout_object.children.get():
        paint_tree(child, cmds)
    else:
      for child in layout_object.children:
        paint_tree(child, cmds)

  cmds = layout_object.paint_effects(cmds)
  display_list.extend(cmds)

def paint_visual_effects(node, cmds, rect):
  opacity = float(node.style["opacity"].get())
  blend_mode = node.style["mix-blend-mode"].get()
  translation = parse_transform(node.style["transform"].get())

  if node.style["overflow"].get() == "clip":
    border_radius = float(node.style["border-radius"].get()[:-2])
    if not blend_mode:
      blend_mode = "source-over"
    cmds = [Blend(1.0, "source-over", node, cmds + [Blend(1.0, "destination-in", None, [DrawRRect(rect, 0, "white")])])]

  blend_op = Blend(opacity, blend_mode, node, cmds)
  node.blend_op = blend_op
  return [Transform(translation, rect, node, [blend_op])]

def dpx(css_px, zoom):
  return css_px * zoom

class ProtectedField:
  def __init__(self, obj, name, parent=None, dependencies=None):
    self.obj = obj
    self.name = name
    self.parent = parent

    self.value = None
    self.dirty = True
    self.invalidations = set()

    self.frozen_dependencies = (dependencies != None)
    if dependencies != None:
      for dependency in dependencies:
        dependency.invalidations.add(self)
  
  def mark(self):
    if self.dirty: return
    self.dirty = True
    self.set_ancestor_dirty_flags()
  
  def get(self):
    assert not self.dirty
    return self.value
  
  def read(self, notify):
    if notify.frozen_dependencies:
      assert notify in self.invalidations
    else:
      self.invalidations.add(notify)
    return self.get()
  
  def set(self, value):
    # if self.value != None:
    #   print("Change", self)
    if value != self.value:
      self.notify()
    self.value = value
    self.dirty = False

  def notify(self):
    for field in self.invalidations:
      field.mark()
    self.set_ancestor_dirty_flags()
  
  def copy(self, field):
    self.set(field.read(notify=self))

  def set_ancestor_dirty_flags(self):
    parent = self.parent
    while parent and not parent.has_dirty_descendants:
      parent.has_dirty_descendants = True
      parent = parent.parent
  
  def set_dependencies(self, dependencies):
    for dependency in dependencies:
      dependency.invalidations.add(self)
    self.frozen_dependencies = True

  def __repr__(self):
    return "ProtectedField({}, {})".format(self.obj.node if hasattr(self.obj, "node") else self.obj, self.name)

class DocumentLayout:
  def __init__(self, node, frame):
    self.node = node
    self.frame = frame
    node.layout_object = self
    self.parent = None
    self.previous = None
    self.children = []

    self.zoom = ProtectedField(self, "zoom", None, [])
    self.width = ProtectedField(self, "width", None, [])
    self.x = ProtectedField(self, "x", None, [])
    self.y = ProtectedField(self, "y", None, [])
    self.height = ProtectedField(self, "height")

    self.has_dirty_descendants = True

  def layout_needed(self):
    if self.zoom.dirty: return True
    if self.width.dirty: return True
    if self.height.dirty: return True
    if self.x.dirty: return True
    if self.y.dirty: return True
    if self.has_dirty_descendants: return True
    return False

  def layout(self, width, zoom):
    if not self.layout_needed(): return

    self.zoom.set(zoom)
    self.width.set(width - 2*dpx(HSTEP, zoom))

    if not self.children:
      child = BlockLayout(self.node, self, None, self.frame)
      self.height.set_dependencies([child.height])
    else:
      child = self.children[0]
    self.children = [child]

    self.x.set(dpx(HSTEP, zoom))
    self.y.set(dpx(VSTEP, zoom))

    child.layout()
    self.has_dirty_descendants = False 
    self.height.copy(child.height)
  
  def paint(self):
    return []
  
  def should_paint(self):
    return True
  
  def paint_effects(self, cmds):
    if self.frame != self.frame.tab.root_frame and self.frame.scroll != 0:
      rect = skia.Rect.MakeLTRB(
        self.x.get(), self.y.get(),
        self.x.get() + self.width.get(), self.y.get() + self.height.get()
      )
      cmds = [Transform((0, -self.frame.scroll), rect, self.node, cmds)]
    return cmds

class BlockLayout:
  def __init__(self, node, parent, previous, frame):
    self.node = node
    node.layout_object = self
    self.frame = frame
    self.parent = parent
    self.previous = previous

    self.zoom = ProtectedField(self, "zoom", self.parent, [self.parent.zoom])
    self.width = ProtectedField(self, "width", self.parent, [self.parent.width])
    self.height = ProtectedField(self, "height", self.parent)
    self.x = ProtectedField(self, "x", self.parent, [self.parent.x])
    if self.previous:
      y_dependencies = [self.previous.y, self.previous.height]
    else:
      y_dependencies = [self.parent.y]
    self.y = ProtectedField(self, "y", self.parent, y_dependencies)
    self.children = ProtectedField(self, "children", self.parent, None)

    self.has_dirty_descendants = True

  def layout_needed(self):
    if self.zoom.dirty: return True
    if self.width.dirty: return True
    if self.height.dirty: return True
    if self.x.dirty: return True
    if self.y.dirty: return True
    if self.children.dirty: return True
    if self.has_dirty_descendants: return True
    return False

  def layout(self):
    if not self.layout_needed(): return

    self.zoom.copy(self.parent.zoom)
    self.width.copy(self.parent.width)
    self.x.copy(self.parent.x)
    if self.previous:
      prev_y = self.previous.y.read(notify=self.y)
      prev_height = self.previous.height.read(notify=self.y)
      self.y.set(prev_y + prev_height)
    else:
      self.y.copy(self.parent.y)

    mode = self.layout_mode()
    if mode == "block":
      if self.children.dirty:
        children = []
        previous = None
        for child in self.node.children:
          next = BlockLayout(child, self, previous, self.frame)
          children.append(next)
          previous = next
        self.children.set(children)

        height_dependencies = [child.height for child in children]
        height_dependencies.append(self.children)
        self.height.set_dependencies(height_dependencies)
    else:
      if self.children.dirty:
        self.temp_children = []
        self.new_line()
        self.recurse(self.node)
        self.children.set(self.temp_children)

        height_dependencies = [child.height for child in self.temp_children]
        height_dependencies.append(self.children)
        self.height.set_dependencies(height_dependencies)
        self.temp_children = None
    
    for child in self.children.get():
      child.layout()

    self.has_dirty_descendants = False

    children = self.children.read(notify=self.height)
    new_height = sum([
      child.height.read(notify=self.height)
      for child in children
    ])
    self.height.set(new_height)

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
    zoom = self.zoom.read(notify=self.children)
    node_font = font(node.style, zoom, notify=self.children)
    w = node_font.measureText(word)
    self.add_inline_child(node, w, TextLayout, self.frame, word)
   
  def input(self, node):
    zoom = self.zoom.read(notify=self.children)
    w = dpx(INPUT_WIDTH_PX, zoom)
    self.add_inline_child(node, w, InputLayout, self.frame)
 
  def image(self, node):
    zoom = self.zoom.read(notify=self.children)
    if "width" in node.attributes:
      w = dpx(int(node.attributes["width"]), zoom)
    else:
      w = dpx(node.image.width(), zoom)
    self.add_inline_child(node, w, ImageLayout, self.frame)
  
  def iframe(self, node):
    zoom = self.zoom.read(notify=self.children)
    if "width" in node.attributes:
      w = dpx(int(node.attributes["width"]), zoom)
    else:
      w = IFRAME_WIDTH_PX + dpx(2, zoom)
    self.add_inline_child(node, w, IframeLayout, self.frame)
  
  def new_line(self):
    self.previous_word = None
    self.cursor_x = 0
    last_line = self.temp_children[-1] if self.temp_children else None
    new_line = LineLayout(self.node, self, last_line)
    self.temp_children.append(new_line)
  
  def self_rect(self):
    return skia.Rect.MakeLTRB(self.x.get(), self.y.get(), self.x.get() + self.width.get(), self.y.get() + self.height.get())

  def paint(self):
    cmds = []
    bgcolor = self.node.style["background-color"].get()

    if bgcolor != "transparent":
      radius = dpx(float(
        self.node.style["border-radius"].get()[:-2]),
        self.zoom.get()
      )
      cmds.append(DrawRRect(
        self.self_rect(), radius, bgcolor
      ))
    return cmds

  def should_paint(self):
    return isinstance(self.node, Text) or (self.node.tag not in ["input", "button", "img", "iframe"])
  
  def paint_effects(self, cmds):
    if self.node.is_focused and "contenteditable" in self.node.attributes:
      text_nodes = [
        t for t in tree_to_list(self, [])
        if isinstance(t, TextLayout)
      ]
      if text_nodes:
        cmds.append(DrawCursor(text_nodes[-1], text_nodes[-1].width.get()))
      else:
        cmds.append(DrawCursor(self, 0))

    cmds = paint_visual_effects(
      self.node, cmds, self.self_rect()
    )
    return cmds
  
  def add_inline_child(self, node, w, child_class, frame, word=None):
    width = self.width.read(notify=self.children)
    if self.cursor_x + w > width:
      self.new_line()
    line = self.temp_children[-1]
    if word:
      child = child_class(node, word, line, self.previous_word)
    else:
      child = child_class(node, line, self.previous_word, frame)
    line.children.append(child)
    self.previous_word = child
    zoom = self.zoom.read(notify=self.children)
    self.cursor_x += w + font(node.style, zoom, notify=self.children).measureText(" ")

class LineLayout:
  def __init__(self, node, parent, previous):
    self.node = node
    self.parent = parent
    self.previous = previous
    self.children = []

    self.zoom = ProtectedField(self, "zoom", self.parent, [self.parent.zoom])
    self.x = ProtectedField(self, "x", self.parent, [self.parent.x])
    if self.previous:
      y_dependencies = [self.previous.y, self.previous.height]
    else:
      y_dependencies = [self.parent.y]
    self.y = ProtectedField(self, "y", self.parent, y_dependencies)
    self.initialized_fields = False
    self.ascent = ProtectedField(self, "ascent", self.parent)
    self.descent = ProtectedField(self, "descent", self.parent)

    self.width = ProtectedField(self, "width", self.parent, [self.parent.width])
    self.height = ProtectedField(self, "height", self.parent, [self.ascent, self.descent])

    self.has_dirty_descendants = True

  def layout_needed(self):
    if self.zoom.dirty: return True
    if self.width.dirty: return True
    if self.height.dirty: return True
    if self.x.dirty: return True
    if self.y.dirty: return True
    if self.ascent.dirty: return True
    if self.descent.dirty: return True
    if self.has_dirty_descendants: return True
    return False

  def layout(self):
    if not self.initialized_fields:
      self.ascent.set_dependencies(
        [child.ascent for child in self.children]
      )
      self.descent.set_dependencies(
        [child.descent for child in self.children]
      )
      self.initialized_fields = True

    if not self.layout_needed(): return

    self.zoom.copy(self.parent.zoom)
    self.width.copy(self.parent.width)
    self.x.copy(self.parent.x)
    if self.previous:
      prev_y = self.previous.y.read(notify=self.y)
      prev_height = self.previous.height.read(notify=self.y)
      self.y.set(prev_y + prev_height)
    else:
      self.y.copy(self.parent.y)
    
    for word in self.children:
      word.layout()

    if not self.children:
      self.ascent.set(0)
      self.descent.set(0)
      self.height.set(0)
      self.has_dirty_descendants = False
      return
    
    self.ascent.set(max([
      -child.ascent.read(notify=self.ascent)
      for child in self.children
    ]))
    self.descent.set(max([
      child.descent.read(notify=self.descent)
      for child in self.children
    ]))

    for child in self.children:
      new_y = self.y.read(notify=child.y)
      new_y += self.ascent.read(notify=child.y)
      if isinstance(child, TextLayout):
          new_y += child.ascent.read(notify=child.y) / 1.25
      else:
          new_y += child.ascent.read(notify=child.y)
      child.y.set(new_y)
    
    max_ascent = self.ascent.read(notify=self.height)
    max_descent = self.descent.read(notify=self.height)
    self.height.set(max_ascent + max_descent)

    self.has_dirty_descendants = False
  
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
      child_outline = parse_outline(child.node.parent.style["outline"].get())
      if child_outline:
        outline_rect.join(child.self_rect())
        outline_node = child.node.parent
    if outline_node:
      paint_outline(outline_node, cmds, outline_rect, self.zoom.get())
    return cmds

class TextLayout:
  def __init__(self, node, word, parent, previous):
    self.node = node
    self.parent = parent
    self.previous = previous
    self.children = []
    self.word = word

    self.zoom = ProtectedField(self, "zoom", self.parent, [self.parent.zoom])
    self.font = ProtectedField(self, "font", self.parent,
      [self.zoom,
       self.node.style["font-weight"],
       self.node.style["font-style"],
       self.node.style["font-size"]])
    self.width = ProtectedField(self, "width", self.parent, [self.font])
    self.height = ProtectedField(self, "height", self.parent, [self.font])
    self.ascent = ProtectedField(self, "ascent", self.parent, [self.font])
    self.descent = ProtectedField(self, "descent", self.parent, [self.font])
    if self.previous:
      x_dependencies = [self.previous.x, self.previous.font, self.previous.width]
    else:
      x_dependencies = [self.parent.x]
    self.x = ProtectedField(self, "x", self.parent, x_dependencies)
    self.y = ProtectedField(self, "y", self.parent, [self.ascent, self.parent.y, self.parent.ascent])

    self.has_dirty_descendants = True

  def layout_needed(self):
    if self.zoom.dirty: return True
    if self.width.dirty: return True
    if self.height.dirty: return True
    if self.x.dirty: return True
    if self.y.dirty: return True
    if self.ascent.dirty: return True
    if self.descent.dirty: return True
    if self.font.dirty: return True
    if self.has_dirty_descendants: return True
    return False

  def layout(self):
    if not self.layout_needed(): return

    self.zoom.copy(self.parent.zoom)

    zoom = self.zoom.read(notify=self.font)
    self.font.set(font(self.node.style, zoom, notify=self.font))

    f = self.font.read(notify=self.width)
    self.width.set(f.measureText(self.word))

    f = self.font.read(notify=self.ascent)
    self.ascent.set(f.getMetrics().fAscent * 1.25)

    f = self.font.read(notify=self.descent)
    self.descent.set(f.getMetrics().fDescent * 1.25)

    f = self.font.read(notify=self.height)
    self.height.set(linespace(f) * 1.25)

    if self.previous:
      prev_x = self.previous.x.read(notify=self.x)
      prev_font = self.previous.font.read(notify=self.x)
      prev_width = self.previous.width.read(notify=self.x)
      self.x.set(prev_x + prev_font.measureText(' ') + prev_width)
    else:
      self.x.copy(self.parent.x)

    self.has_dirty_descendants = False

  def paint(self):
    cmds = []
    leading = self.height.get() / 1.25 * .25 / 2
    color = self.node.style["color"].get()
    cmds.append(DrawText(self.x.get(), self.y.get() + leading, self.word, self.font.get(), color))
    return cmds
  
  def self_rect(self):
    return skia.Rect.MakeLTRB(
      self.x.get(), self.y.get(), self.x.get() + self.width.get(), self.y.get() + self.height.get()
    )
  
  def __repr__(self):
    return ("TextLayout(x={}, y={}, width={}, height={}, word={})").format(self.x.get(), self.y.get(), self.width.get(), self.height.get(), self.word)
  
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
    self.zoom = ProtectedField(self, "zoom", self.parent, [self.parent.zoom])
    self.font = ProtectedField(self, "font", self.parent,
      [self.zoom,
      self.node.style['font-weight'],
      self.node.style['font-style'],
      self.node.style['font-size']])
    self.width = ProtectedField(self, "width", self.parent, [self.zoom])
    self.height = ProtectedField(self, "height", self.parent, [self.zoom, self.font, self.width])
    self.ascent = ProtectedField(self, "ascent", self.parent, [self.height])
    self.descent = ProtectedField(self, "descent", self.parent, [])

    if self.previous:
      x_dependencies = [self.previous.x, self.previous.font, self.previous.width]
    else:
      x_dependencies = [self.parent.x]
    self.x = ProtectedField(self, "x", self.parent, x_dependencies)
    self.y = ProtectedField(self, "y", self.parent, [self.ascent, self.parent.y, self.parent.ascent])
  
    self.has_dirty_descendants = True
  
  def layout_needed(self):
    if self.zoom.dirty: return True
    if self.width.dirty: return True
    if self.height.dirty: return True
    if self.x.dirty: return True
    if self.y.dirty: return True
    if self.ascent.dirty: return True
    if self.descent.dirty: return True
    if self.font.dirty: return True
    if self.has_dirty_descendants: return True
    return False

  def layout(self):
    self.zoom.copy(self.parent.zoom)
    
    zoom = self.zoom.read(notify=self.font)
    self.font.set(font(self.node.style, zoom, notify=self.font))
    
    if self.previous:
      prev_x = self.previous.x.read(notify=self.x)
      prev_font = self.previous.font.read(notify=self.x)
      prev_width = self.previous.width.read(notify=self.x)
      self.x.set(prev_x + prev_font.measureText(' ') + prev_width)
    else:
      self.x.copy(self.parent.x)

    self.has_dirty_descendants = False
    
  def should_paint(self):
    return True
  
class InputLayout(EmbedLayout):
  def __init__(self, node, parent, previous, frame):
    super().__init__(node, parent, previous, frame)

  def layout(self):
    if not self.layout_needed(): return
    super().layout()
    zoom = self.zoom.read(notify=self.width)
    self.width.set(dpx(INPUT_WIDTH_PX, zoom))

    font = self.font.read(notify=self.height)
    self.height.set(linespace(font))

    height = self.height.read(notify=self.ascent)
    self.ascent.set(-height)
    self.descent.set(0)

  def self_rect(self):
    return skia.Rect.MakeLTRB(self.x.get(), self.y.get(), self.x.get() + self.width.get(), self.y.get() + self.height.get())

  def paint(self):
    cmds = []

    bgcolor = self.node.style["background-color"].get()
    if bgcolor != "transparent":
      radius = dpx(float(
        self.node.style["border-radius"].get()[:-2]), self.zoom.get())
      cmds.append(DrawRRect(self.self_rect(), radius, bgcolor))

    if self.node.tag == "input":
      text = self.node.attributes.get("value", "")
    elif self.node.tag == "button":
      if len(self.node.children) == 1 and isinstance(self.node.children[0], Text):
        text = self.node.children[0].text
      else:
        print("HTML inside button not implemented yet")
        text = ""
    color = self.node.style["color"].get()
    cmds.append(
      DrawText(self.x.get(), self.y.get(), text, self.font.get(), color)
    )

    if self.node.is_focused and self.node.tag == "input":
      cmds.append(DrawCursor(self, self.font.get().measureText(text)))

    return cmds
  
  def paint_effects(self, cmds):
    cmds = paint_visual_effects(self.node, cmds, self.self_rect())
    paint_outline(self.node, cmds, self.self_rect(), self.zoom.get())
    return cmds

class ImageLayout(EmbedLayout):
  def __init__(self, node, parent, previous, frame):
    super().__init__(node, parent, previous, frame)

  def layout(self):
    if not self.layout_needed(): return
    super().layout()
    width_attr = self.node.attributes.get("width")
    height_attr = self.node.attributes.get("height")
    image_width = self.node.image.width()
    image_height = self.node.image.height()
    aspect_ratio = image_width / image_height

    w_zoom = self.zoom.read(notify=self.width)
    h_zoom = self.zoom.read(notify=self.height)
    if width_attr and height_attr:
      self.width.set(dpx(int(width_attr), w_zoom))
      self.img_height = dpx(int(height_attr), h_zoom)
    elif width_attr:
      self.width.set(dpx(int(width_attr), w_zoom))
      w = self.width.read(notify=self.height)
      self.img_height = w / aspect_ratio
    elif height_attr:
      self.img_height = dpx(int(height_attr), h_zoom)
      self.width.set(self.img_height * aspect_ratio)
    else:
      self.width.set(dpx(image_width, w_zoom))
      self.img_height = dpx(image_height, h_zoom)

    font = self.font.read(notify=self.height)
    self.height.set(max(self.img_height, linespace(font)))

    height = self.height.read(notify=self.ascent)
    self.ascent.set(-height)
    self.descent.set(0)

  def paint(self):
    cmds = []
    rect = skia.Rect.MakeLTRB(
      self.x.get(), self.y.get() + self.height.get() - self.img_height,
      self.x.get() + self.width.get(), self.y.get() + self.height.get()
    )
    quality = self.node.style["image-rendering"].get()
    cmds.append(DrawImage(self.node.image, rect, quality))
    return cmds
  
  def paint_effects(self, cmds):
    return cmds

class IframeLayout(EmbedLayout):
  def __init__(self, node, parent, previous, parent_frame):
    super().__init__(node, parent, previous, parent_frame)
  
  def layout(self):
    if not self.layout_needed(): return
    super().layout()

    width_attr = self.node.attributes.get("width")
    height_attr = self.node.attributes.get("height")

    w_zoom = self.zoom.read(notify=self.width)
    if width_attr:
      self.width.set(dpx(int(width_attr) + 2, w_zoom))
    else:
      self.width.set(dpx(IFRAME_WIDTH_PX + 2, w_zoom))

    zoom = self.zoom.read(notify=self.height)
    if height_attr:
      self.height.set(dpx(int(height_attr) + 2, zoom))
    else:
      self.height.set(dpx(IFRAME_HEIGHT_PX + 2, zoom))

    if self.node.frame and self.node.frame.loaded:
      self.node.frame.frame_height = self.height.get() - dpx(2, self.zoom.get())
      self.node.frame.frame_width = self.width.get() - dpx(2, self.zoom.get())
      self.node.frame.document.width.mark()
  
    height = self.height.read(notify=self.ascent)
    self.ascent.set(-height)
    self.descent.set(0)

  def paint(self):
    cmds = []
    rect = skia.Rect.MakeLTRB(
      self.x.get(), self.y.get(),
      self.x.get() + self.width.get(), self.y.get() + self.height.get()
    )
    bgcolor = self.node.style["background-color"].get()
    if bgcolor != "transparent":
      radius = dpx(float(
        self.node.style["border-radius"].get()[:-2]), self.zoom.get()
      )
      cmds.append(DrawRRect(rect, radius, bgcolor))
    return cmds

  def paint_effects(self, cmds):
    rect = skia.Rect.MakeLTRB(self.x.get(), self.y.get(), self.x.get() + self.width.get(), self.y.get() + self.height.get())
    diff = dpx(1, self.zoom.get())
    offset = (self.x.get() + diff, self.y.get() + diff)
    cmds = [Transform(offset, rect, self.node, cmds)]
    inner_rect = skia.Rect.MakeLTRB(
      self.x.get() + diff, self.y.get() + diff,
      self.x.get() + self.width.get() - diff,
      self.y.get() + self.height.get() - diff
    )
    internal_cmds = cmds
    internal_cmds.append(Blend(1.0, "destination-in", None, [DrawRRect(inner_rect, 0, "white")]))
    cmds = [Blend(1.0, "source-over", self.node, internal_cmds)]
    paint_outline(self.node, cmds, rect, self.zoom.get())
    cmds = paint_visual_effects(self.node, cmds, inner_rect)
    return cmds