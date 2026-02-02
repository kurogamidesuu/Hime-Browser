import sys
import ctypes
import sdl2
from network import URL
from browser_ui import Browser

def mainloop(browser):
  event = sdl2.SDL_Event()
  ctrl_down = False
  while True:
    while sdl2.SDL_PollEvent(ctypes.byref(event)) != 0:
      if event.type == sdl2.SDL_QUIT:
        browser.handle_quit()
        sdl2.SDL_Quit()
        sys.exit()
        break
      elif event.type == sdl2.SDL_MOUSEBUTTONUP:
        browser.handle_click(event.button)
      elif event.type == sdl2.SDL_MOUSEMOTION:
        browser.handle_hover(event.motion)
      elif event.type == sdl2.SDL_KEYDOWN:
        if ctrl_down:
          if event.key.keysym.sym == sdl2.SDLK_EQUALS:
            browser.increment_zoom(True)
          elif event.key.keysym.sym == sdl2.SDLK_MINUS:
            browser.increment_zoom(False)
          elif event.key.keysym.sym == sdl2.SDLK_0:
            browser.reset_zoom()
          elif event.key.keysym.sym == sdl2.SDLK_LEFT:
            browser.go_back()
          elif event.key.keysym.sym == sdl2.SDLK_l:
            browser.focus_addressbar()
          elif event.key.keysym.sym == sdl2.SDLK_d:
            browser.toggle_dark_mode()
          elif event.key.keysym.sym == sdl2.SDLK_a:
            browser.toggle_accessibility()
          elif event.key.keysym.sym == sdl2.SDLK_t:
            browser.new_tab(URL("https://browser.engineering/"))
          elif event.key.keysym.sym == sdl2.SDLK_TAB:
            browser.cycle_tabs()
          elif event.key.keysym.sym == sdl2.SDLK_q:
            browser.handle_quit()
            sdl2.SDL_Quit()
            sys.exit()
            break
        if event.key.keysym.sym == sdl2.SDLK_RETURN:
          browser.handle_enter()
        elif event.key.keysym.sym == sdl2.SDLK_DOWN:
          browser.handle_down()
        elif event.key.keysym.sym == sdl2.SDLK_TAB:
          browser.handle_tab()
        elif event.key.keysym.sym == sdl2.SDLK_RCTRL or event.key.keysym.sym == sdl2.SDLK_LCTRL:
          ctrl_down = True
        elif event.key.keysym.sym == sdl2.SDLK_UP:
          browser.handle_up()
      elif event.type == sdl2.SDL_KEYUP:
        if event.key.keysym.sym == sdl2.SDLK_RCTRL or event.key.keysym.sym == sdl2.SDLK_LCTRL:
          ctrl_down = False
      elif event.type == sdl2.SDL_MOUSEWHEEL:
        scroll_y = event.wheel.y

        if event.wheel.direction == sdl2.SDL_MOUSEWHEEL_FLIPPED:
          scroll_y = - scroll_y
        
        browser.handle_scroll_with_mouse(scroll_y)
      elif event.type == sdl2.SDL_TEXTINPUT and not ctrl_down:
        browser.handle_key(event.text.text.decode('utf8'))
    
    browser.composite_raster_and_draw()
    browser.schedule_animation_frame()

if __name__ == "__main__":
  sdl2.SDL_Init(sdl2.SDL_INIT_EVENTS)
  browser = Browser()
  browser.new_tab(URL(sys.argv[1] if len(sys.argv) > 1 else "https://browser.engineering/"))
  browser.draw()
  mainloop(browser)