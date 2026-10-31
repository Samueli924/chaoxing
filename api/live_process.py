import threading
import time

from api.live import Live
from api.logger import logger
from api.task_runner import TaskStateHub


class LiveProcessor:
    @staticmethod
    def run_live(live: Live, speed: float = 1.0, course_title: str = ""):
        """循环提交直播时长，直到达到总时长"""
        live_status = live.get_status()
        if not live_status:
            logger.error("直播状态获取失败，无法继续")
            return False

        try:
            duration = live_status.get("temp", {}).get("data", {}).get("duration", 0)
            if not duration:
                logger.warning("无法获取直播总时长，默认按30分钟处理")
                duration = 30 * 60
        except Exception as e:
            logger.error(f"解析直播时长失败: {str(e)}")
            return False

        hub = TaskStateHub()
        worker_id = threading.current_thread().name
        effective_speed = hub.get_effective_speed(worker_id) if hub.is_web_mode() else speed
        adjusted_duration = duration / max(0.5, float(effective_speed))
        total_minutes = max(1, (int(adjusted_duration) + 59) // 60)
        logger.info(f"开始刷取直播'{live.name}'，总时长{total_minutes}分钟")

        chapter_name = f"[直播] {course_title} - {live.name}" if course_title else f"[直播] {live.name}"

        try:
            for i in range(total_minutes):
                if hub.is_web_mode() and not hub.is_task_running():
                    logger.warning(f"检测到任务终止指令，中断直播刷取: {live.name}")
                    return False

                current_speed = hub.get_effective_speed(worker_id) if hub.is_web_mode() else speed
                if hub.is_web_mode():
                    hub.update_worker_state(worker_id, {
                        "chapter": chapter_name,
                        "position": i + 1,
                        "duration": total_minutes,
                        "unit": "分钟",
                        "speed": current_speed,
                        "status": "PLAYING",
                        "type": "video",
                    })

                logger.info(f"直播'{live.name}'已观看{i + 1}/{total_minutes}分钟")
                success = live.do_finish()
                if not success:
                    logger.warning(f"第{i + 1}分钟时长提交失败，将重试")
                    retry_waited = 0.0
                    while retry_waited < 5.0:
                        if hub.is_web_mode() and not hub.is_task_running():
                            logger.warning(f"检测到任务终止指令，中断直播刷取: {live.name}")
                            return False
                        time.sleep(0.5)
                        retry_waited += 0.5
                    live.do_finish()

                current_speed = hub.get_effective_speed(worker_id) if hub.is_web_mode() else speed
                sleep_time = max(1.0, 59.0 / max(0.5, float(current_speed)))
                elapsed = 0.0
                while elapsed < sleep_time:
                    if hub.is_web_mode() and not hub.is_task_running():
                        logger.warning(f"检测到任务终止指令，中断直播刷取: {live.name}")
                        return False
                    current_speed = hub.get_effective_speed(worker_id) if hub.is_web_mode() else speed
                    sleep_time = max(1.0, 59.0 / max(0.5, float(current_speed)))
                    if elapsed >= sleep_time:
                        break
                    step = min(1.0, sleep_time - elapsed)
                    time.sleep(step)
                    elapsed += step

            logger.success(f"直播'{live.name}'时长刷取完成")
            return True
        finally:
            if hub.is_web_mode():
                hub.remove_worker(worker_id)
