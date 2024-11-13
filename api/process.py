import time
from api.config import GlobalConst as gc

def sec2time(sec: int):
    h = int(sec / 3600)
    m = int(sec % 3600 / 60)
    s = int(sec % 60)
    if h != 0:
        return f'{h}:{m:02}:{s:02}'
    if sec != 0:
        return f'{m:02}:{s:02}'
    return '--:--'


def show_progress(name: str, start: int, span: int, total: int, _speed: float):
    start_time = time.time()
    while int(time.time() - start_time) < int(span / _speed):
        current = start + int((time.time() - start_time) * _speed)
        percent = int(current / total * 100)
        length = int(percent * 40 // 100)
        progress = ("#" * length).ljust(40, " ")
        # remain = (total - current)
        print(f"\r当前任务: {name} |{progress}| {percent}%  {sec2time(current)}/{sec2time(total)}", end="", flush=True)
        time.sleep(gc.THRESHOLD)