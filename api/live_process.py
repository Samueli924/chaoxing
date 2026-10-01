import time

from api import interrupt
from api.live import Live
from api.logger import logger


class LiveProcessor:
    @staticmethod
    def run_live(live: Live, speed: float = 1.0):
        """按真实时间提交直播时长，直到达到总时长。

        直播是实时流：这里强制 1 倍速（忽略配置倍速），并响应 q 终止；
        任何一次时长提交失败都会返回 False，不再无条件报成功。
        """
        speed = 1.0
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

        total_minutes = (int(duration) + 59) // 60
        logger.info(f"开始刷取直播'{live.name}'，总时长{total_minutes}分钟（真实时间）")

        for i in range(total_minutes):
            if interrupt.should_stop():
                logger.warning(f"直播'{live.name}'已被用户终止，本次不计为完成")
                return False
            logger.info(f"直播'{live.name}'已观看{i + 1}/{total_minutes}分钟")
            if not live.do_finish():
                logger.warning(f"第{i + 1}分钟时长提交失败，5 秒后重试一次")
                time.sleep(5)
                if not live.do_finish():
                    logger.error(f"直播'{live.name}'时长提交连续失败，本次不计为完成")
                    return False
            time.sleep(59)

        logger.success(f"直播'{live.name}'时长刷取完成")
        return True
