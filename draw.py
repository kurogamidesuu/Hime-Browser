import skia
from constants import NAMED_COLORS

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

def linespace(font):
  metrics = font.getMetrics()
  return metrics.fDescent - metrics.fAscent
  
class DrawText:
  def __init__(self, x1, y1, text, font, color):
    self.rect = skia.Rect.MakeLTRB(x1, y1, x1 + font.measureText(text), y1 - font.getMetrics().fAscent + font.getMetrics().fDescent)
    self.text = text
    self.font = font
    self.color = color

  def execute(self, canvas):
    paint = skia.Paint(
      AntiAlias=True,
      Color=parse_color(self.color),
    )
    baseline = self.rect.top() - self.font.getMetrics().fAscent
    canvas.drawString(self.text, float(self.rect.left()), baseline, self.font, paint)

class DrawRect:
  def __init__(self, rect, color):
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
  
class DrawRRect:
  def __init__(self, rect, radius, color):
    self.rect = rect
    self.rrect = skia.RRect.MakeRectXY(rect, radius, radius)
    self.color = color

  def execute(self, canvas):
    paint = skia.Paint(
      Color=parse_color(self.color),
    )
    canvas.drawRRect(self.rrect, paint)

class DrawLine:
  def __init__(self, x1, y1, x2, y2, color, thickness):
    self.rect = skia.Rect.MakeLTRB(x1, y1, x2, y2)
    self.color = color
    self.thickness = thickness

  def execute(self, canvas):
    path = skia.Path().moveTo(
      self.rect.left(), self.rect.top()
    ).lineTo(self.rect.right(), self.rect.bottom())
    paint = skia.Paint(
      Color = parse_color(self.color),
      StrokeWidth=self.thickness,
      Style=skia.Paint.kStroke_Style,
    )
    canvas.drawPath(path, paint)

class DrawOutline:
  def __init__(self, rect, color, thickness):
    self.rect = rect
    self.color = color
    self.thickness = thickness

  def execute(self, canvas):
    paint = skia.Paint(
      Color=parse_color(self.color),
      StrokeWidth=self.thickness,
      Style=skia.Paint.kStroke_Style,
    )
    canvas.drawRect(self.rect, paint)
  
class Opacity:
  def __init__(self, opacity, children):
    self.opacity = opacity
    self.children = children
    self.rect = skia.Rect.MakeEmpty()
    for cmd in self.children:
      self.rect.join(cmd.rect)

  def execute(self, canvas):
    paint = skia.Paint(
      Alphaf=self.opacity
    )
    if self.opacity < 1:
      canvas.saveLayer(None, paint)
    for cmd in self.children:
      cmd.execute(canvas)
    if self.opacity < 1:
      canvas.restore()

class Blend:
  def __init__(self, opacity, blend_mode, children):
    self.opacity = opacity
    self.blend_mode = blend_mode
    self.should_save = self.blend_mode or self.opacity < 1

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