import threading
import time

class Task:
  def __init__(self, task_code, *args):
    self.task_code = task_code
    self.args = args

  def run(self):
    self.task_code(*self.args)
    self.task_code = None
    self.args = None

class TaskRunner:
  def __init__(self, tab):
    self.condition = threading.Condition()
    self.tab = tab
    self.tasks = []
    self.main_thread = threading.Thread(
      target=self.run,
      name="Main thread",
    )
    self.needs_quit = False
  
  def start_thread(self):
    self.main_thread.start()

  def schedule_task(self, task):
    self.condition.acquire(blocking=True)
    self.tasks.append(task)
    self.condition.notify_all()
    self.condition.release()
  
  def set_needs_quit(self):
    self.condition.acquire(blocking=True)
    self.needs_quit = True
    self.condition.notify_all()
    self.condition.release()

  def run(self):
    while True:
      self.condition.acquire(blocking=True)
      needs_quit = self.needs_quit
      self.condition.release()
      if needs_quit:
        self.handle_quit()
        return

      task = None
      self.condition.acquire(blocking=True)
      if len(self.tasks) > 0:
        task = self.tasks.pop(0)
      self.condition.release()
      if task:
        task.run()
    
      self.condition.acquire(blocking=True)
      if len(self.tasks) == 0 and not self.needs_quit:
        self.condition.wait()
      self.condition.release()

  def clear_pending_tasks(self):
    self.condition.acquire(blocking=True)
    self.tasks.clear()
    self.condition.release()
  
  def handle_quit(self):
    pass

class MeasureTime:
  def __init__(self):
    self.lock = threading.Lock()
    self.file = open("browser.trace", "w")
    self.file.write('{"traceEvents": [')
    ts = time.time() * 1000000
    self.file.write(
      '{ "name": "process_name",' +
      '"ph": "M",' +
      '"ts": ' + str(ts) + ',' +
      '"pid": 1, "cat": "__metadata",' +
      '"args": {"name": "Browser"}}'
    )
    self.file.flush()

  def time(self, name):
    self.lock.acquire(blocking=True)
    ts = time.time() * 1000000
    tid = threading.get_ident()
    self.file.write(
      ', { "ph": "B", "cat": "_",' +
      '"name": "' + name + '",' +
      '"ts": ' + str(ts) + ',' +
      '"pid": 1, "tid": ' + str(tid) + '}'
    )
    self.file.flush()
    self.lock.release()

  def stop(self, name):
    self.lock.acquire(blocking=True)
    ts = time.time() * 1000000
    tid = threading.get_ident()
    self.file.write(
      ', { "ph": "E", "cat": "_",' +
      '"name": "' + name + '",' +
      '"ts": ' + str(ts) + ',' +
      '"pid": 1, "tid": ' + str(tid) + '}'
    )
    self.lock.release()

  def finish(self):
    self.lock.acquire(blocking=True)
    for thread in threading.enumerate():
      self.file.write(
        ', { "ph": "M", "name": "thread_name",' +
        '"pid": 1, "tid": ' + str(thread.ident) + ',' +
        '"args": { "name": "' + thread.name + '"}}'
      )
    self.file.write(']}')
    self.file.close()
    self.lock.release()

class CommitData:
  def __init__(self, url, scroll, height, display_list, composited_updates):
    self.url = url
    self.scroll = scroll
    self.height = height
    self.display_list = display_list
    self.composited_updates = composited_updates