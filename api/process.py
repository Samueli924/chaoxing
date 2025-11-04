import time

from api.config import GlobalConst as gc
from api.live import Live
from loguru import logger
import time
import threading


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
class LiveProcessor:
    @staticmethod
    def run_live(live: Live, speed: float = 1.0):
        """循环提交直播时长，直到达到总时长"""
        # 获取直播状态（包含总时长）
        live_status = live.get_status()
        if not live_status:
            logger.error("直播状态获取失败，无法继续")
            return False
        
        # 解析直播总时长（单位：秒）
        try:
            duration = live_status.get("temp", {}).get("data", {}).get("duration", 0)
            if not duration:
                logger.warning("无法获取直播总时长，默认按30分钟处理")
                duration = 30 * 60  # 默认30分钟
        except Exception as e:
            logger.error(f"解析直播时长失败: {str(e)}")
            return False
        
        # 根据播放速度调整所需时间
        adjusted_duration = duration / speed
        total_minutes = (int(adjusted_duration) + 59) // 60  # 转换为分钟（向上取整）
        logger.info(f"开始刷取直播'{live.name}'，总时长{total_minutes}分钟（已根据倍速调整）")

        # 循环提交时长（每59秒一次，模拟持续观看）
        for i in range(total_minutes):
            logger.info(f"直播'{live.name}'已观看{i+1}/{total_minutes}分钟")
            success = live.do_finish()  # 提交当前时长
            if not success:
                logger.warning(f"第{i+1}分钟时长提交失败，将重试")
                # 失败重试一次
                time.sleep(5)
                live.do_finish()
            
            # 根据倍速调整间隔时间
            sleep_time = 59 / speed
            time.sleep(sleep_time)

        logger.success(f"直播'{live.name}'时长刷取完成")
        return True
