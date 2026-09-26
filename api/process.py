from api.logger import logger


def increase_learning_count_for_course(chaoxing, course, config):
    """
    为单个课程增加章节学习次数。

    遍历课程的所有章节，轮询调用 studentstudyAjax，直到总次数达到 target_count。

    Args:
        chaoxing: Chaoxing 实例
        course: 课程信息字典
        config: 配置字典，需包含 target_count 字段

    Returns:
        StudyResult: 操作结果
    """
    target_count = config.get("target_count", 100)
    logger.info(f"开始为课程 [{course['title']}] 增加章节学习次数, 目标总次数: {target_count}")

    point_list = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
    points = point_list.get("points", [])
    if not points:
        logger.warning(f"课程 [{course['title']}] 没有章节, 跳过")
        return None

    logger.info(f"课程 [{course['title']}] 共有 {len(points)} 个章节")

    result = chaoxing.increase_chapter_learning_count(course, points, target_count)
    if result.is_success():
        logger.info(f"课程 [{course['title']}] 章节学习次数增加完成")
    else:
        logger.error(f"课程 [{course['title']}] 章节学习次数增加未完成")
    return result
