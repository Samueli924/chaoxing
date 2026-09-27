import math

from api.live import Live
from api.logger import logger
from api.runtime import runtime


class LiveProcessor:
    @staticmethod
    def run_live(live: Live, speed: float = 1.0) -> bool:
        """循环提交直播观看时长，直到达到直播总时长。每次提交记录约 1 分钟观看时长。"""
        live_status = live.get_status()
        if not live_status:
            logger.error("直播状态获取失败，无法继续")
            return False

        # 解析直播总时长（单位：秒）
        try:
            duration = float(((live_status.get("temp") or {}).get("data") or {}).get("duration") or 0)
        except (AttributeError, TypeError, ValueError):
            duration = 0
        if duration <= 0:
            logger.warning("无法获取直播总时长，默认按30分钟处理")
            duration = 30 * 60

        # 提交次数由直播总时长决定；倍速只缩短两次提交之间的等待时间
        total_minutes = max(1, math.ceil(duration / 60))
        interval = 59 / max(1.0, speed)
        logger.info(f"开始观看直播'{live.name}'，共需提交 {total_minutes} 次观看记录，"
                    f"预计耗时约 {math.ceil(total_minutes * interval / 60)} 分钟")

        progress_key = f"live-{live.course_id}-{live.attachment.get('jobid', '')}"
        failures = 0
        try:
            for i in range(total_minutes):
                if runtime.should_stop():
                    return False
                success = live.do_finish()
                if not success:
                    logger.warning(f"第{i + 1}分钟时长提交失败，将重试")
                    if runtime.sleep(5):
                        return False
                    success = live.do_finish()
                if not success:
                    failures += 1
                runtime.update_item(progress_key, f"直播 · {live.name}", i + 1, total_minutes, kind="live")
                logger.info(f"直播'{live.name}'已观看{i + 1}/{total_minutes}分钟")
                if runtime.sleep(interval):
                    return False
        finally:
            runtime.remove_item(progress_key)

        if failures * 2 > total_minutes:
            logger.error(f"直播'{live.name}'有 {failures}/{total_minutes} 次时长提交失败")
            return False
        logger.success(f"直播'{live.name}'时长刷取完成")
        return True
