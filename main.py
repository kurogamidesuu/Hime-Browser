import sys
import ctypes
import sdl2
from network import URL
from browser_ui import Browser

def mainloop(browser):
  event = sdl2.SDL_Event()
  while True:
    while sdl2.SDL_PollEvent(ctypes.byref(event)) != 0:
      if event.type == sdl2.SDL_QUIT:
        browser.handle_quit()
        sdl2.SDL_Quit()
        sys.exit()
      elif event.type == sdl2.SDL_MOUSEBUTTONUP:
        browser.handle_click(event.button)
      elif event.type == sdl2.SDL_KEYDOWN:
        if event.key.keysym.sym == sdl2.SDLK_RETURN:
          browser.handle_enter()
        elif event.key.keysym.sym == sdl2.SDLK_DOWN:
          browser.handle_down()
        elif event.key.keysym.sym == sdl2.SDLK_UP:
          browser.handle_up()
      elif event.type == sdl2.SDL_MOUSEWHEEL:
        scroll_y = event.wheel.y

        if event.wheel.direction == sdl2.SDL_MOUSEWHEEL_FLIPPED:
          scroll_y = - scroll_y
        
        browser.handle_scroll_with_mouse(scroll_y)
      elif event.type == sdl2.SDL_TEXTINPUT:
        browser.handle_key(event.text.text.decode('utf8'))
    
    browser.composite_raster_and_draw()
    browser.schedule_animation_frame()

if __name__ == "__main__":
  sdl2.SDL_Init(sdl2.SDL_INIT_EVENTS)
  browser = Browser()
  browser.new_tab(URL(sys.argv[1]))
  browser.draw()
  mainloop(browser)