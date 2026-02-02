import skia
from constants import NAMED_COLORS, SHOW_COMPOSITED_LAYER_BORDERS

FONTS = {}

def parse_color(color):
  if color.startswith("#") and len(color) == 7:
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    return skia.Color(r, g, b)
  elif color.startswith("#") and len(color) == 9:
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    a = int(color[7:9], 16)
    return skia.Color(r, g, b, a)
  elif color.startswith("#") and len(color) == 4:
    r = int(color[1] * 2, 16)
    g = int(color[2] * 2, 16)
    b = int(color[3] * 2, 16)
    return skia.Color(r, g, b)
  elif color in NAMED_COLORS:
    return parse_color(NAMED_COLORS[color])
  else:
    print("MISSING COLOR:", color)
    return skia.ColorBLACK

def parse_blend_mode(blend_mode_str):
  if blend_mode_str == "multiply":
    return skia.BlendMode.kMultiply
  elif blend_mode_str == "difference":
    return skia.BlendMode.kDifference
  elif blend_mode_str == "destination-in":
    return skia.BlendMode.kDstIn
  elif blend_mode_str == "source-over":
    return skia.BlendMode.kSrcOver
  else:
    return skia.BlendMode.kSrcOver

def parse_image_rendering(quality):
  if quality == "high-quality":
    return skia.SamplingOptions(skia.CubicResampler.Mitchell())
  elif quality == "crisp-edges":
    return skia.SamplingOptions(skia.FilterMode.kNearest, skia.MipmapMode.kNone)
  else:
    return skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear)

def get_font(size, weight, style):
  key = (weight, style)
  if key not in FONTS:
    if weight == "bold":
      skia_weight = skia.FontStyle.kBold_Weight
    else:
      skia_weight = skia.FontStyle.kNormal_Weight
    if style == "italic":
      skia_style = skia.FontStyle.kItalic_Slant
    else:
      skia_style = skia.FontStyle.kUpright_Slant
    skia_width = skia.FontStyle.kNormal_Width
    style_info = skia.FontStyle(skia_weight, skia_width, skia_style)
    font = skia.Typeface('Arial', style_info)
    FONTS[key] = font
  return skia.Font(FONTS[key], size)

def font(style, zoom):
  from layout import dpx

  weight = style["font-weight"]
  variant = style["font-style"]
  size = None
  try:
    size = float(style["font-size"][:-2]) * 0.75
  except:
    size = 16 
  font_size = dpx(size, zoom)
  return get_font(font_size, weight, variant)

def linespace(font):
  metrics = font.getMetrics()
  return metrics.fDescent - metrics.fAscent

def local_to_absolute(display_item, rect):
  while display_item.parent:
    rect = display_item.parent.map(rect)
    display_item = display_item.parent
  return rect

def absolute_to_local(display_item, rect):
  parent_chain = []
  while display_item.parent:
    parent_chain.append(display_item.parent)
    display_item = display_item.parent
  for parent in reversed(parent_chain):
    rect = parent.unmap(rect)
  return rect

def paint_outline(node, cmds, rect, zoom):
  from layout import dpx
  from css import parse_outline

  outline = parse_outline(node.style.get("outline"))
  if not outline: return
  thickness, color = outline
  cmds.append(DrawOutline(rect, color, dpx(thickness, zoom)))

class PaintCommand:
  def __init__(self, rect):
    self.rect = rect
    self.children = []

class VisualEffect:
  def __init__(self, rect, children, node=None):
    self.rect = rect.makeOffset(0.0, 0.0)
    self.children = children
    for child in self.children:
      self.rect.join(child.rect)
    self.node = node
    self.needs_compositing = any([
      child.needs_compositing for child in self.children
      if isinstance(child, VisualEffect)
    ])

class CompositedLayer:
  def __init__(self, skia_context, display_item):
    self.skia_context = skia_context
    self.surface = None
    self.display_items = [display_item]
    self.parent = display_item.parent

  def composited_bounds(self):
    rect = skia.Rect.MakeEmpty()
    for item in self.display_items:
      rect.join(absolute_to_local(
        item, local_to_absolute(item, item.rect)
      ))
    rect.outset(1, 1)
    return rect
  
  def raster(self):
    bounds = self.composited_bounds()
    if bounds.isEmpty(): return
    irect = bounds.roundOut()

    if not self.surface:
      self.surface = skia.Surface.MakeRenderTarget(
        self.skia_context, skia.Budgeted.kNo,
        skia.ImageInfo.MakeN32Premul(
          irect.width(), irect.height())
      )
      if not self.surface:
        self.surface = skia.Surface(irect.width(), irect.height())
      assert self.surface

    canvas = self.surface.getCanvas()
    canvas.clear(skia.ColorTRANSPARENT)
    canvas.save()
    canvas.translate(-bounds.left(), -bounds.top())
    for item in self.display_items:
      item.execute(canvas)
    canvas.restore()

    if SHOW_COMPOSITED_LAYER_BORDERS:
      border_rect = skia.Rect.MakeXYWH(1, 1, irect.width() - 2, irect.height() - 2)
      DrawOutline(border_rect, "red", 1).execute(canvas)

  def add(self, display_item):
    assert self.can_merge(display_item)
    self.display_items.append(display_item)

  def can_merge(self, display_item):
    return display_item.parent == self.display_items[0].parent
  
  def absolute_bounds(self):
    rect = skia.Rect.MakeEmpty()
    for item in self.display_items:
      rect.join(local_to_absolute(item, item.rect))
    return rect

  def __repr__(self):
    return ("layer: composited_bounds={} absolute_bounds={} first_chunk={}").format(
        self.composited_bounds(), self.absolute_bounds(),
        self.display_items if len(self.display_items) > 0 else 'None')

class DrawCompositedLayer(PaintCommand):
  def __init__(self, composited_layer):
    self.composited_layer = composited_layer
    super().__init__(self.composited_layer.composited_bounds())

  def execute(self, canvas):
    layer = self.composited_layer
    if not layer.surface: return
    bounds = layer.composited_bounds()
    layer.surface.draw(canvas, bounds.left(), bounds.top())

  def __repr__(self):
    return "DrawCompositedLayer()"
  
class DrawText(PaintCommand):
  def __init__(self, x1, y1, text, font, color):
    self.font = font
    self.text = text
    self.color = color
    super().__init__(skia.Rect.MakeLTRB(
      x1, y1,
      x1 + font.measureText(text),
      y1 - font.getMetrics().fAscent + font.getMetrics().fDescent
    ))

  def execute(self, canvas):
    paint = skia.Paint(
      AntiAlias=True,
      Color=parse_color(self.color)
    )
    baseline = self.rect.top() - self.font.getMetrics().fAscent
    canvas.drawString(self.text, float(self.rect.left()), baseline, self.font, paint)

  def __repr__(self):
    return "DrawText(text={})".format(self.text)

class DrawRect(PaintCommand):
  def __init__(self, rect, color):
    super().__init__(rect)
    self.rect = rect
    self.color = color

  def execute(self, canvas):
    paint = skia.Paint(
      Color=parse_color(self.color),
    )
    canvas.drawRect(self.rect, paint)

  def __repr__(self):
    return "DrawRect(top={} left={} bottom={} right={} color={})".format(
        self.rect.top(), self.rect.left(), self.rect.bottom(),
        self.rect.right(), self.color)
  
class DrawRRect(PaintCommand):
  def __init__(self, rect, radius, color):
    super().__init__(rect)
    self.rrect = skia.RRect.MakeRectXY(rect, radius, radius)
    self.color = color

  def execute(self, canvas):
    paint = skia.Paint(
      Color=parse_color(self.color),
    )
    canvas.drawRRect(self.rrect, paint)
  
  def __repr__(self):
    return "DrawRRect(rect={}, color={})".format(
      str(self.rrect), self.color
    )

class DrawLine(PaintCommand):
  def __init__(self, x1, y1, x2, y2, color, thickness):
    super().__init__(skia.Rect.MakeLTRB(x1, y1, x2, y2))
    self.color = color
    self.thickness = thickness

  def execute(self, canvas):
    path = skia.Path().moveTo(
      self.rect.left(), self.rect.top()
    ).lineTo(self.rect.right(), self.rect.bottom())
    paint = skia.Paint(
      Color=parse_color(self.color),
      StrokeWidth=self.thickness,
      Style=skia.Paint.kStroke_Style,
    )
    canvas.drawPath(path, paint)
  
  def __repr__(self):
    return "DrawLine(top={} left={} bottom={} right={})".format(
      self.rect.top(), self.rect.left(), self.rect.bottom(), self.rect.right()
    )

class DrawOutline(PaintCommand):
  def __init__(self, rect, color, thickness):
    super().__init__(rect)
    self.color = color
    self.thickness = thickness

  def execute(self, canvas):
    paint = skia.Paint(
      Color=parse_color(self.color),
      StrokeWidth=self.thickness,
      Style=skia.Paint.kStroke_Style,
    )
    canvas.drawRect(self.rect, paint) 

  def __repr__(self):
    return "DrawOutline(top={} left={} bottom={} right={} border_color={} thickness={})".format(
      self.rect.top(), self.rect.left(), self.rect.bottom(), self.rect.right(), self.color, self.thickness
    )
  
class DrawImage(PaintCommand):
  def __init__(self, image, rect, quality):
    super().__init__(rect)
    self.image = image
    self.quality = parse_image_rendering(quality)

  def execute(self, canvas):
    canvas.drawImageRect(self.image, self.rect, self.quality)

  def __repr__(self):
    return "DrawImage(rect={})".format(self.rect)
  
class Blend(VisualEffect):
  def __init__(self, opacity, blend_mode, node, children):
    super().__init__(skia.Rect.MakeEmpty(), children, node)
    self.opacity = opacity
    self.blend_mode = blend_mode
    self.should_save = self.blend_mode or self.opacity < 1

    if self.should_save:
      self.needs_compositing = True

    self.children = children
    self.rect = skia.Rect.MakeEmpty()
    for cmd in self.children:
      self.rect.join(cmd.rect)

  def execute(self, canvas):
    paint = skia.Paint(
      Alphaf=self.opacity,
      BlendMode=parse_blend_mode(self.blend_mode),
    )
    if self.should_save:
      canvas.saveLayer(None, paint)
    for cmd in self.children:
      cmd.execute(canvas)
    if self.should_save:
      canvas.restore()

  def clone(self, child):
    return Blend(self.opacity, self.blend_mode, self.node, [child])
  
  def map(self, rect):
    if self.children and isinstance(self.children[-1], Blend) and self.children[-1].blend_mode == "destination-in":
      bounds = rect.makeOffset(0.0, 0.0)
      bounds.intersect(self.children[-1].rect)
      return bounds
    else:
      return rect
    
  def unmap(self, rect):
    return rect

  def __repr__(self):
    args = ""
    if self.opacity < 1:
        args += ", opacity={}".format(self.opacity)
    if self.blend_mode:
        args += ", blend_mode={}".format(self.blend_mode)
    if not args:
        args = ", <no-op>"
    return "Blend({})".format(args[2:])

class Transform(VisualEffect):
  def __init__(self, translation, rect, node, children):
    super().__init__(rect, children, node)
    self.self_rect = rect
    self.translation = translation

  def execute(self, canvas):
    if self.translation:
      (x, y) = self.translation
      canvas.save()
      canvas.translate(x, y)
    for cmd in self.children:
      cmd.execute(canvas)
    if self.translation:
      canvas.restore()

  def clone(self, child):
    return Transform(self.translation, self.self_rect, self.node, [child])
  
  def map(self, rect):
    from css import map_translation
    return map_translation(rect, self.translation)
  
  def unmap(self, rect):
    from css import map_translation
    return map_translation(rect, self.translation, True)

  def __repr__(self):
    if self.translation:
      (x, y) = self.translation
      return "Transform(translate({}, {}))".format(x, y)
    else:
      return "Transform(<no-op>)"

class NumericAnimation:
  def __init__(self, old_value, new_value, num_frames):
    self.old_value = float(old_value)
    self.new_value = float(new_value)
    self.num_frames = num_frames

    self.frame_count = 1
    total_change = self.new_value - self.old_value
    self.change_per_frame = total_change / num_frames
  
  def animate(self):
    self.frame_count += 1
    if self.frame_count >= self.num_frames: return
    current_value = self.old_value + self.change_per_frame * self.frame_count
    return str(current_value)
  
  def __repr__(self):
    return "NumericAnimation(old_value={old_value}, change_per_frame={change_per_frame}, num_frames={num_frames})".format(
      old_value=self.old_value,
      change_per_frame=self.change_per_frame,
      num_frames=self.num_frames
    )