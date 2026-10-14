import time

from api.base import ActivityStatus, ActivityType
from api.logger import logger
from api.config import GlobalConst as gc

# 签到活动类型: 活动列表接口的 activeType 在不同接口版本里可能是数字或字符串
SIGN_ACTIVITY_TYPES = {str(int(ActivityType.SIGNIN)), "sign"}

# 签到接口返回纯文本: 成功是 success, 已经签到也算完成, 其余(距离限制、非本班学生等)按失败处理
# 用完整文本比对: 子串匹配会把 unsuccessful 判成 success
SIGN_DONE_TEXTS = (
    "success",
    "successful",
    "签到成功",
    "已经签到",
    "您已经签到",
    "已签到",
)
SIGN_TEXT_PUNCT = ".!。！,，;； \t\r\n"


def sign_succeeded(result) -> bool:
    """根据签到接口返回的文本判断签到是否完成."""
    text = str(result or '').strip().lower().strip(SIGN_TEXT_PUNCT)
    return text in SIGN_DONE_TEXTS


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


def increase_learning_count_for_course(chaoxing, course, config):
    """
    为单个课程增加章节学习次数。

    遍历课程的所有章节，轮询调用 studentstudyAjax，直到总次数达到 target_count。

    Args:
        chaoxing: Chaoxing 实例
        course: 课程信息字典
        config: 配置字典，需包含 target_count 字段
    """
    target_count = config.get("target_count", 100)
    logger.info(f"开始为课程 [{course['title']}] 增加章节学习次数, 目标总次数: {target_count}")

    # 获取课程所有章节
    point_list = chaoxing.get_course_point(
        course["courseId"], course["clazzId"], course["cpi"]
    )
    points = point_list.get("points", [])
    if not points:
        logger.warning(f"课程 [{course['title']}] 没有章节, 跳过")
        return

    logger.info(f"课程 [{course['title']}] 共有 {len(points)} 个章节")

    # 调用核心方法
    result = chaoxing.increase_chapter_learning_count(course, points, target_count)
    if result.is_success():
        logger.info(f"课程 [{course['title']}] 章节学习次数增加完成")
    else:
        logger.error(f"课程 [{course['title']}] 章节学习次数增加失败")


def pending_sign_activities(activities) -> list[dict]:
    """
    从活动列表里挑出正在进行中的签到活动.

    Args:
        activities: Chaoxing.get_activity_list() 的返回值

    Returns:
        [{"activeId": ..., "name": ...}, ...]
    """
    pending = []
    for item in activities or []:
        if str(item.get("activeType")) not in SIGN_ACTIVITY_TYPES:
            continue
        if item.get("status") != int(ActivityStatus.ACTIVE):
            continue
        active_id = item.get("activeId")
        if not active_id:
            logger.warning(f"签到活动缺少 activeId, 已跳过: {item.get('name')}")
            continue
        pending.append({"activeId": active_id, "name": item.get("name", "签到")})
    return pending


def sign_in_course(chaoxing, course) -> int:
    """
    完成单个课程当前正在进行的所有签到.

    Args:
        chaoxing: Chaoxing 实例
        course: 课程信息字典

    Returns:
        实际发起签到的次数
    """
    try:
        activities = chaoxing.get_activity_list(course)
    except Exception as e:
        logger.error(f"课程 [{course['title']}] 获取活动列表失败: {type(e).__name__}: {e}")
        return 0

    pending = pending_sign_activities(activities)
    if not pending:
        logger.info(f"课程 [{course['title']}] 没有进行中的签到活动")
        return 0

    signed = 0
    for activity in pending:
        active_id = activity["activeId"]
        logger.info(f"课程 [{course['title']}] 正在签到: {activity['name']} (activeId={active_id})")
        try:
            chaoxing.pre_sign(course, active_id)
            result = chaoxing.sign_in_normal(course, active_id)
        except Exception as e:
            logger.error(f"课程 [{course['title']}] 签到异常: {type(e).__name__}: {e}")
            continue
        # pre_sign / sign_in_normal 对非 200 只记日志不抛异常, 所以要看返回文本
        if sign_succeeded(result):
            signed += 1
            logger.info(f"课程 [{course['title']}] 签到完成: {result}")
        else:
            logger.warning(f"课程 [{course['title']}] 签到未成功, 服务端返回: {result}")

    return signed

