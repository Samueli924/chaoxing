import time
from api.config import GlobalConst as gc

def sec2time(sec):
    ret = ""
    if sec // 3600 > 0:
        ret += f"{sec // 3600}h "
        sec = sec - sec // 3600 * 3600
    if sec // 60 > 0:
        ret += f"{sec // 60}min "
        sec = sec - sec // 60 * 60
    if sec:
        ret += f"{sec}s"
    if not ret:
        ret = "0s"
    return ret


def show_progress(name, start: int, span: int, total: int, _speed):
    start_time = time.time()
    while int(time.time() - start_time) < int(span // _speed):
        current = start + int(time.time() - start_time)
        percent = int(current / total * 100)
        length = int(percent * 40 // 100)
        progress = ("#" * length).ljust(40, " ")
        # remain = (total - current)
        print("\r" + f"当前任务: {name} |{progress}| {percent}%  {sec2time(current)}/{sec2time(total)}     ", end="", flush=True)
        time.sleep(gc.THRESHOLD)