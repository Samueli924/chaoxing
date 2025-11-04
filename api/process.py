import time

from api.config import GlobalConst as gc


def sec2time(seconds: int) -> str:
    """
    将秒数转换为时分秒格式的字符串。
    
    Args:
        seconds: 要转换的秒数
        
    Returns:
        格式化的时间字符串，格式为 "h:mm:ss" 或 "mm:ss"，如果秒数为0则返回"--:--"
    """
    hours = int(seconds / 3600)
    minutes = int(seconds % 3600 / 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02}:{secs:02}"
    if seconds > 0:
        return f"{minutes:02}:{secs:02}"
    return "--:--"


def show_progress(task_name: str, start_position: int, duration: int, 
                 total_length: int, speed: float) -> None:
    """
    显示任务进度条，模拟任务进度。
    
    Args:
        task_name: 当前执行的任务名称
        start_position: 起始位置（以秒为单位）
        duration: 任务持续时间（以秒为单位）
        total_length: 任务总长度（以秒为单位）
        speed: 任务执行速度
        
    Returns:
        None
    """
    start_time = time.time()
    expected_end_time = start_time + (duration / speed)
    
    while time.time() < expected_end_time:
        # 计算当前进度
        current_position = start_position + int((time.time() - start_time) * speed)
        percent_complete = min(int(current_position / total_length * 100), 100)
        
        # 生成进度条
        bar_length = 40
        filled_length = int(percent_complete * bar_length // 100)
        progress_bar = ("#" * filled_length).ljust(bar_length, " ")
        
        # 格式化输出进度信息
        progress_text = (
            f"\r当前任务: {task_name} |{progress_bar}| {percent_complete}%  "
            f"{sec2time(current_position)}/{sec2time(total_length)}"
        )
        
        print(progress_text, end="", flush=True)
        time.sleep(gc.THRESHOLD)
