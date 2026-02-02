import dukpy
import threading
from css import CSSParser
from dom import tree_to_list, HTMLParser
from task import Task

EVENT_DISPATCH_JS = \
  "new window.Node(dukpy.handle)" + \
  ".dispatchEvent(new window.Event(dukpy.type))"

POST_MESSAGE_DISPATCH_JS = \
  "window.dispatchEvent(new window.MessageEvent(dukpy.data))"

SETTIMEOUT_JS = "window.__runSetTimeout(dukpy.handle)"
XHR_ONLOAD_JS = "window.__runXHROnload(dukpy.out, dukpy.handle)"
RUNTIME_JS = open("runtime.js").read()

class JSContext:
  def __init__(self, tab, url_origin):
    self.tab = tab
    self.url_origin = url_origin
    self.discarded = False
    
    self.interp = dukpy.JSInterpreter()
    self.interp.export_function("log", print)
    self.interp.export_function("querySelectorAll", self.querySelectorAll)
    self.interp.export_function("getAttribute", self.getAttribute)
    self.interp.export_function("setAttribute", self.setAttribute)
    self.interp.export_function("innerHTML_set", self.innerHTML_set)
    self.interp.export_function("style_set", self.style_set)
    self.interp.export_function("XMLHttpRequest_send", self.XMLHttpRequest_send)
    self.interp.export_function("setTimeout", self.setTimeout)
    self.interp.export_function("requestAnimationFrame", self.requestAnimationFrame)
    self.interp.export_function("parent", self.parent)
    self.interp.export_function("postMessage", self.postMessage)

    self.node_to_handle = {}
    self.handle_to_node = {}

    self.interp.evaljs("function Window(id) { this._id = id };")
    self.interp.evaljs("WINDOWS = {}")

  def run(self, script, code, window_id):
    try:
      code = self.wrap(code, window_id)
      self.tab.browser.measure.time('script-load')
      self.interp.evaljs(code)
      self.tab.browser.measure.stop('script-load')
    except dukpy.JSRuntimeError as e:
      self.tab.browser.measure.stop('script-load')
      print("Script", script, "crashed", e)
  
  def querySelectorAll(self, selector_text, window_id):
    frame = self.tab.window_id_to_frame[window_id]
    self.throw_if_cross_origin(frame)
    selector = CSSParser(selector_text).selector()
    nodes = [node for node
             in tree_to_list(frame.nodes, [])
             if selector.matches(node)]
    return [self.get_handle(node) for node in nodes]
  
  def get_handle(self, elt):
    if elt not in self.node_to_handle:
      handle = len(self.node_to_handle)
      self.node_to_handle[elt] = handle
      self.handle_to_node[handle] = elt
    else:
      handle = self.node_to_handle[elt]
    return handle
  
  def getAttribute(self, handle, attr):
    elt = self.handle_to_node[handle]
    attr = elt.attributes.get(attr, None)
    return attr if attr else ""
  
  def dispatch_event(self, type, elt, window_id):
    handle = self.node_to_handle.get(elt, -1)
    code = self.wrap(EVENT_DISPATCH_JS, window_id)
    do_default = self.interp.evaljs(
      code, type=type, handle=handle
    )
    return not do_default

  def innerHTML_set(self, handle, s, window_id):
    frame = self.tab.window_id_to_frame[window_id]
    self.throw_if_cross_origin(frame)
    doc = HTMLParser("<html><body>" + s + "</body></html>").parse()
    new_nodes = doc.children[0].children
    elt = self.handle_to_node[handle]
    elt.children = new_nodes
    for child in elt.children:
      child.parent = elt
    frame.set_needs_render()

  def XMLHttpRequest_send(self, method, url, body, isasync, handle, window_id):
    frame = self.tab.window_id_to_frame[window_id]
    full_url = frame.url.resolve(url)
    if not frame.allowed_request(full_url):
      raise Exception("Cross-origin XHR blocked by CSP")
    if full_url.origin() != frame.url.origin():
      raise Exception("Cross-origin XHR request not allowed")
    
    def run_load():
      headers, response = full_url.request(frame.url, body)
      response = response.decode("utf8", "replace")
      task = Task(self.dispatch_xhr_onload, response, handle, window_id)
      self.tab.task_runner.schedule_task(task)
      if not isasync:
        return response
    
    if not isasync:
      return run_load()
    else:
      threading.Thread(target=run_load).start()
  
  def dispatch_xhr_onload(self, out, handle, window_id):
    code = self.wrap(XHR_ONLOAD_JS, window_id)
    self.tab.browser.measure.time('script-xhr')
    do_default = self.interp.evaljs(code, out=out, handle=handle)
    self.tab.browser.measure.stop('script-xhr')
  
  def dispatch_settimeout(self, handle, window_id):
    self.tab.browser.measure.time('script-settimeout')
    self.interp.evaljs(self.wrap(SETTIMEOUT_JS, window_id), handle=handle)
    self.tab.browser.measure.stop('script-settimeout')
  
  def setTimeout(self, handle, time, window_id):
    def run_callback():
      task = Task(self.dispatch_settimeout, handle, window_id)
      self.tab.task_runner.schedule_task(task)
    threading.Timer(time / 1000.0, run_callback).start()

  def requestAnimationFrame(self):
    self.tab.browser.set_needs_animation_frame(self.tab)

  def style_set(self, handle, s, window_id):
    frame = self.tab.window_id_to_frame[window_id]
    self.throw_if_cross_origin(frame)
    elt = self.handle_to_node[handle]
    elt.attributes["style"] = s
    frame.set_needs_render()

  def setAttribute(self, handle, attr, value, window_id):
    frame = self.tab.window_id_to_frame[window_id]
    self.throw_if_cross_origin(frame)
    elt = self.handle_to_node[handle]
    elt.attributes[attr] = value
    self.tab.set_needs_render_all_frames()
  
  def add_window(self, frame):
    code = "var window_{} = new Window({});".format(frame.window_id, frame.window_id)
    self.interp.evaljs(code)

    self.tab.browser.measure.time('script-runtime')
    self.interp.evaljs(self.wrap(RUNTIME_JS, frame.window_id))
    self.tab.browser.measure.stop('script-runtime')

    self.interp.evaljs("WINDOWS[{}] = window_{};".format(frame.window_id, frame.window_id))
        
  def wrap(self, script, window_id):
    return "window = window_{}; {}".format(window_id, script)
  
  def dispatch_RAF(self, window_id):
    code = self.wrap("window.__runRAFHandlers()", window_id)
    self.interp.evaljs(code)

  def parent(self, window_id):
    parent_frame = self.tab.window_id_to_frame[window_id].parent_frame
    if not parent_frame:
      return None
    return parent_frame.window_id
  
  def throw_if_cross_origin(self, frame):
    if frame.url.origin() != self.url_origin:
      raise Exception("Cross-origin access disallowed from script")
  
  def postMessage(self, target_window_id, message, origin):
    task = Task(self.tab.post_message, message, target_window_id)
    self.tab.task_runner.schedule_task(task)
  
  def dispatch_post_message(self, message, window_id):
    self.interp.evaljs(self.wrap(POST_MESSAGE_DISPATCH_JS, window_id), data=message)