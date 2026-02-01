import skia
from dom import Element
from constants import INHERITED_PROPERTIES, REFRESH_RATE_SEC
from draw import NumericAnimation

class CSSParser:
  def __init__(self, s):
    self.s = s
    self.i = 0

  def whitespace(self):
    while self.i < len(self.s) and self.s[self.i].isspace():
      self.i += 1

  def literal(self, literal):
    if not (self.i < len(self.s) and self.s[self.i] == literal):
      raise Exception("Parsing Error")
    self.i += 1

  def word(self):
    start = self.i
    in_quote = False
    while self.i < len(self.s):
      cur = self.s[self.i]
      if cur == "'":
        in_quote = not in_quote
      if cur.isalnum() or cur in ",/#-.%()\"'" or (in_quote and cur == ':'):
        self.i += 1
      else:
        break
    if not (self.i > start):
      raise Exception("Parsing Error")
    return self.s[start:self.i]

  def pair(self, until):
    prop = self.word()
    self.whitespace()
    self.literal(":")
    self.whitespace()
    val = self.until_chars(until)
    return prop.casefold(), val.strip()
    
  def ignore_until(self, chars):
    while self.i < len(self.s):
      if self.s[self.i] in chars:
        return self.s[self.i]
      else:
        self.i += 1
    return None
  
  def body(self):
    pairs = {}
    while self.i < len(self.s) and self.s[self.i] != "}":
      try:
        prop, val = self.pair([";", "}"])
        pairs[prop] = val
        self.whitespace()
        self.literal(";")
        self.whitespace()
      except Exception:
        why = self.ignore_until([";", "}"])
        if why == ";":
          self.literal(";")
          self.whitespace()
        else:
          break
    return pairs
  
  def selector(self):
    out = self.simple_selector()
    self.whitespace()
    while self.i < len(self.s) and self.s[self.i] != "{":
      descendant = self.simple_selector()
      out = DescendantSelector(out, descendant)
      self.whitespace()
    return out
  
  def simple_selector(self):
    out = TagSelector(self.word().casefold())
    if self.i < len(self.s) and self.s[self.i] == ":":
      self.literal(":")
      pseudoclass = self.word().casefold()
      out = PseudoclassSelector(pseudoclass, out)
    return out
  
  def parse(self):
    rules = []
    media = None
    self.whitespace()
    while self.i < len(self.s):
      try:
        if self.s[self.i] == "@" and not media:
          prop, val = self.media_query()
          if prop == "prefers-color-scheme" and val in ["dark", "light"]:
            media = val
          self.whitespace()
          self.literal("{")
          self.whitespace()
        elif self.s[self.i] == "}" and media:
          self.literal("}")
          media = None
          self.whitespace()
        else:
          selector = self.selector()
          self.literal("{")
          self.whitespace()
          body = self.body()
          self.literal("}")
          self.whitespace()
          rules.append((media, selector, body))
      except Exception:
        why = self.ignore_until(["}"])
        if why == "}":
          self.literal("}")
          self.whitespace()
        else:
          break
    return rules
  
  def until_chars(self, chars):
    start = self.i
    while self.i < len(self.s) and self.s[self.i] not in chars:
      self.i += 1
    return self.s[start:self.i]
  
  def media_query(self):
    self.literal("@")
    assert self.word() == "media"
    self.whitespace()
    self.literal("(")
    self.whitespace()
    prop, val = self.pair([")"])
    self.whitespace()
    self.literal(")")
    return prop, val

class TagSelector:
  def __init__(self, tag):
    self.tag = tag
    self.priority = 1

  def matches(self, node):
    return isinstance(node, Element) and self.tag == node.tag
  
class DescendantSelector:
  def __init__(self, ancestor, descendant):
    self.ancestor = ancestor
    self.descendant = descendant
    self.priority = ancestor.priority + descendant.priority

  def matches(self, node):
    if not self.descendant.matches(node): return False
    while node.parent:
      if self.ancestor.matches(node.parent): return True
      node = node.parent
    return False
  
class PseudoclassSelector:
  def __init__(self, pseudoclass, base):
    self.pseudoclass = pseudoclass
    self.base = base
    self.priority = self.base.priority

  def matches(self, node):
    if not self.base.matches(node):
      return False
    if self.pseudoclass == "focus":
      return node.is_focused
    else:
      return False
  
  def __repr__(self):
    return "PseudoclassSelector({}, {})".format(self.pseudoclass, self.base)
  
def cascade_priority(rule):
  media, selector, body = rule
  return selector.priority

def style(node, rules, tab):
  old_style = node.style
  node.style = {}
  for property, default_value in INHERITED_PROPERTIES.items():
    if node.parent:
      node.style[property] = node.parent.style[property]
    else:
      node.style[property] = default_value  
  for media, selector, body in rules:
    if media:
      if (media == "dark") != tab.dark_mode: continue
    if not selector.matches(node): continue
    for property, value in body.items():
      node.style[property] = value
  if isinstance(node, Element) and "style" in node.attributes:
    pairs = CSSParser(node.attributes["style"]).body()
    for property, value in pairs.items():
      node.style[property] = value
  if node.style["font-size"].endswith("%"):
    if node.parent:
      parent_font_size = node.parent.style["font-size"]
    else:
      parent_font_size = INHERITED_PROPERTIES["font-size"]
    node_pct = float(node.style["font-size"][:-1]) / 100
    parent_px = float(parent_font_size[:-2])
    node.style["font-size"] = str(node_pct * parent_px) + "px"

  if old_style:
    transitions = diff_styles(old_style, node.style)
    for property, (old_value, new_value, num_frames) in transitions.items():
      if property == "opacity":
        tab.set_needs_render()
        animation = NumericAnimation(
          old_value, new_value, num_frames
        )
        node.animations[property] = animation
        node.style[property] = animation.animate()

  for child in node.children:
    style(child, rules, tab)

def parse_transition(value):
  properties = {}
  if not value: return properties
  for item in value.split(","):
    property, duration = item.split(" ", 1)
    frames = int(float(duration[:-1]) / REFRESH_RATE_SEC)
    properties[property] = frames
  return properties

def diff_styles(old_style, new_style):
  transitions = {}
  for property, num_frames in parse_transition(new_style.get("transition")).items():
    if property not in old_style: continue
    if property not in new_style: continue
    old_value = old_style[property]
    new_value = new_style[property]
    if old_value == new_value: continue
    transitions[property] = (old_value, new_value, num_frames)
  return transitions

def parse_transform(transform_str):
  if transform_str.find('translate(') < 0:
    return None
  left_paren = transform_str.find('(')
  right_paren = transform_str.find(')')
  (x_px, y_px) = transform_str[left_paren + 1:right_paren].split(",")
  return (float(x_px[:-2]), float(y_px[:-2]))

def map_translation(rect, translation, reversed=False):
  if not translation:
    return rect
  else:
    (x, y) = translation
    matrix = skia.Matrix()
    if reversed:
      matrix.setTranslate(-x, -y)
    else:
      matrix.setTranslate(x, y)
    return matrix.mapRect(rect)

def absolute_bounds_for_obj(obj):
  rect = skia.Rect.MakeXYWH(
    obj.x, obj.y, obj.width, obj.height
  )
  cur = obj.node
  while cur:
    rect = map_translation(rect, parse_transform(cur.style.get("transform", "")))
    cur = cur.parent
  return rect

def parse_outline(outline_str):
  if not outline_str: return None
  values = outline_str.split(" ")
  if len(values) != 3: return None
  if values[1] != "solid": return None
  return int(values[0][:-2]), values[2]

DEFAULT_STYLE_SHEET = CSSParser(open("browser.css").read()).parse()