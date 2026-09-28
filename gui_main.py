import os
import sys
import json
import threading
import time
import webview
from loguru import logger
import traceback
import builtins
import tqdm

GUI_CONFIG_PATH = "gui_config.json"

# ---- UI State for Polling (Thread-Safe) ----
ui_lock = threading.Lock()
pending_logs = []
progress_state = {}

def push_log(msg):
    with ui_lock:
        pending_logs.append(msg)
        if len(pending_logs) > 1000:
            pending_logs.pop(0)

def push_progress(gui_id, desc, n, total):
    with ui_lock:
        progress_state[gui_id] = {
            "desc": desc,
            "n": n,
            "total": total
        }

# ---- TQDM Patch ----
import tqdm.std

class GuiTqdm(tqdm.std.tqdm):
    def __init__(self, *args, **kwargs):
        kwargs['file'] = open(os.devnull, 'w')
        super().__init__(*args, **kwargs)
        self._gui_id = str(id(self))
        self._update_gui()

    def update(self, n=1):
        super().update(n)
        self._update_gui()

    def set_description(self, desc=None, refresh=True):
        super().set_description(desc, refresh)
        self._update_gui()

    def set_postfix(self, ordered_dict=None, refresh=True, **kwargs):
        super().set_postfix(ordered_dict, refresh, **kwargs)
        self._update_gui()

    def close(self):
        super().close()
        self._update_gui()

    def _update_gui(self):
        desc_str = self.desc if self.desc else ""
        if self.postfix:
            desc_str += f" | {self.postfix}"
        push_progress(self._gui_id, str(desc_str), self.n, self.total if self.total else 0)

# Monkey-patch tqdm globally before importing any project modules
tqdm.tqdm = GuiTqdm
tqdm.std.tqdm = GuiTqdm
try:
    import tqdm.auto
    tqdm.auto.tqdm = GuiTqdm
except ImportError:
    pass
# ------------------------------------------------

class PollingLogHandler:
    def write(self, message):
        msg = message.strip()
        if msg:
            push_log(msg)

# Now import chaoxing internals
from api.base import Chaoxing
from api.answer import Tiku
from main import init_chaoxing, filter_courses, JobProcessor, ChapterTask
from api.notification import Notification

class Api:
    def __init__(self):
        # Prefix all internal states with underscore '_' so pywebview won't serialize them!
        self._chaoxing = None
        self._config = {
            "common": {
                "username": "",
                "password": "",
                "speed": 1.0,
                "jobs": 4,
                "notopen_action": "retry",
                "add_learning_count": False,
                "target_count": 100,
                "use_cookies": False
            },
            "tiku": {
                "provider": "TikuYanxi",
                "submit": False,
                "cover_rate": 0.9,
                "tokens": "",
                "key": "",
                "endpoint": "",
                "model": ""
            },
            "notification": {
                "provider": "",
                "url": ""
            }
        }
        self._load_config()
        self._stop_event = threading.Event()
        self._running_thread = None

    def get_ui_updates(self):
        global pending_logs, progress_state
        with ui_lock:
            logs_copy = pending_logs[:]
            pending_logs.clear()
            progress_copy = progress_state.copy()
        return {"success": True, "logs": logs_copy, "progress": progress_copy}

    def _load_config(self):
        if os.path.exists(GUI_CONFIG_PATH):
            try:
                with open(GUI_CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved_config = json.load(f)
                    for key in self._config:
                        if key in saved_config:
                            self._config[key].update(saved_config[key])
            except Exception as e:
                print("Failed to load config:", e)

    def _save_config(self):
        with open(GUI_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=4)

    def get_config(self):
        return {"success": True, "data": self._config}

    def test_api_connection(self, config_str):
        try:
            new_config = json.loads(config_str)
            tiku_config = new_config.get("tiku", self._config.get("tiku", {}))
            
            mapped_tiku_config = {
                "provider": str(tiku_config.get("provider", "TikuYanxi")),
                "submit": "true" if tiku_config.get("submit", False) else "false",
                "cover_rate": str(tiku_config.get("cover_rate", "0.9")),
                "tokens": str(tiku_config.get("tokens", "")),
                "endpoint": str(tiku_config.get("endpoint", "")),
                "key": str(tiku_config.get("key", "")),
                "model": str(tiku_config.get("model", "")),
                "true_list": "正确,对,√,是",
                "false_list": "错误,错,×,否,不对,不正确",
                "delay": "1.0",
                "check_llm_connection": "true",
                "likeapi_search": "false",
                "likeapi_vision": "true",
                "likeapi_model": "glm-4.5-air",
                "likeapi_retry": "true",
                "likeapi_retry_times": "3",
                "go_authorization": "",
                "go_min_interval": "1.0",
                "go_retry_times": "3",
                "go_retry_backoff": "1.2",
                "min_interval_seconds": "3",
                "http_proxy": "",
                "siliconflow_key": str(tiku_config.get("key", "")),
                "siliconflow_model": str(tiku_config.get("model", "deepseek-ai/DeepSeek-R1")),
                "siliconflow_endpoint": str(tiku_config.get("endpoint", "https://api.siliconflow.cn/v1/chat/completions")),
                "manual_mode_default": "batch",
                "manual_mode_separator": ";",
                "url": ""
            }
            
            from api.answer import Tiku
            test_tiku = Tiku.get_tiku_from_config(mapped_tiku_config, config_path=None)
            test_tiku.init_tiku()
            
            if not test_tiku.check_llm_connection():
                return {"success": False, "msg": f"{test_tiku.name} 连接测试失败，请检查配置密钥或网络。"}
                
            return {"success": True, "msg": f"{test_tiku.name} 连接测试成功！"}
        except Exception as e:
            return {"success": False, "msg": f"测试异常: {e}"}

    def save_config_and_login(self, config_str):
        try:
            new_config = json.loads(config_str)
            for key in self._config:
                if key in new_config:
                    self._config[key].update(new_config[key])
            self._save_config()

            common_config = self._config["common"]
            tiku_config = self._config["tiku"]
            
            mapped_tiku_config = {
                "provider": str(tiku_config.get("provider", "TikuYanxi")),
                "submit": "true" if tiku_config.get("submit", False) else "false",
                "cover_rate": str(tiku_config.get("cover_rate", "0.9")),
                "tokens": str(tiku_config.get("tokens", "")),
                "endpoint": str(tiku_config.get("endpoint", "")),
                "key": str(tiku_config.get("key", "")),
                "model": str(tiku_config.get("model", "")),
                "true_list": "正确,对,√,是",
                "false_list": "错误,错,×,否,不对,不正确",
                "delay": "1.0",
                "check_llm_connection": "false",
                "likeapi_search": "false",
                "likeapi_vision": "true",
                "likeapi_model": "glm-4.5-air",
                "likeapi_retry": "true",
                "likeapi_retry_times": "3",
                "go_authorization": "",
                "go_min_interval": "1.0",
                "go_retry_times": "3",
                "go_retry_backoff": "1.2",
                "min_interval_seconds": "3",
                "http_proxy": "",
                "siliconflow_key": "",
                "siliconflow_model": "deepseek-ai/DeepSeek-R1",
                "siliconflow_endpoint": "https://api.siliconflow.cn/v1/chat/completions",
                "manual_mode_default": "batch",
                "manual_mode_separator": ";",
                "url": ""
            }
            
            logger.info("Initializing Chaoxing API...")
            self._chaoxing = init_chaoxing(common_config, mapped_tiku_config, config_path=None)
            
            logger.info(f"Trying to login with account: {common_config['username']}")
            _login_state = self._chaoxing.login(login_with_cookies=common_config.get("use_cookies", False))
            
            if not _login_state["status"]:
                return {"success": False, "msg": _login_state["msg"]}
            
            return {"success": True, "msg": "登录成功"}
        except Exception as e:
            logger.error(f"登录时发生异常: {e}")
            return {"success": False, "msg": str(e)}

    def get_courses(self):
        if not self._chaoxing:
            return {"success": False, "msg": "尚未登录"}
        try:
            all_course = self._chaoxing.get_course_list()
            formatted_courses = []
            for c in all_course:
                formatted_courses.append({
                    "courseId": c.get("courseId", ""),
                    "classId": c.get("clazzId", ""),
                    "title": c.get("title", ""),
                    "class_name": c.get("className", ""),
                    "teacher": c.get("teacher", "")
                })
            return {"success": True, "data": formatted_courses}
        except Exception as e:
            logger.error(f"获取课程异常: {e}")
            return {"success": False, "msg": str(e)}

    def start_tasks(self, course_ids_str):
        if not self._chaoxing:
            return {"success": False, "msg": "未登录"}
        
        course_ids = json.loads(course_ids_str)
        if not course_ids:
            return {"success": False, "msg": "未选择课程"}
            
        if self._running_thread and self._running_thread.is_alive():
            return {"success": False, "msg": "当前已有任务正在运行，请先停止"}

        self._stop_event.clear()
        
        self._running_thread = threading.Thread(target=self._run_tasks_thread, args=(course_ids,))
        self._running_thread.start()
        
        return {"success": True, "msg": "任务已在后台启动"}

    def stop_tasks(self):
        if self._running_thread and self._running_thread.is_alive():
            self._stop_event.set()
            logger.info("已发送停止信号，等待当前任务中断...")
            return {"success": True, "msg": "已发送停止信号"}
        return {"success": False, "msg": "当前没有运行的任务"}

    def _run_tasks_thread(self, course_ids):
        try:
            logger.info(f"开始执行选定的 {len(course_ids)} 门课程...")
            all_course = self._chaoxing.get_course_list()
            
            target_courses = [c for c in all_course if c.get("courseId") in course_ids]
            common_config = self._config["common"]

            tasks = []
            for course in target_courses:
                if self._stop_event.is_set():
                    logger.warning("任务已被手动停止！")
                    break
                    
                logger.info(f"正在读取课程章节: {course['title']}")
                point_list = self._chaoxing.get_course_point(
                    course["courseId"], course["clazzId"], course["cpi"]
                )
                for i, point in enumerate(point_list["points"]):
                    task = ChapterTask(point=point, index=i, course=course)
                    tasks.append(task)

            if tasks and not self._stop_event.is_set():
                p = JobProcessor(self._chaoxing, tasks, common_config)
                p.run()
                
            logger.info("========== 所有选定的任务已完成 ==========")
            
            try:
                notification_config = self._config.get("notification", {})
                if notification_config.get("provider"):
                    notification = Notification()
                    notification.config_set(notification_config)
                    notification = notification.get_notification_from_config()
                    notification.init_notification()
                    notification.send("超星学习通桌面版: 您选定的课程学习任务已完成")
            except Exception as ne:
                logger.warning(f"发送通知失败: {ne}")
                
        except Exception as e:
            logger.error(f"执行任务发生异常: {e}")
            traceback.print_exc()


def setup_logger():
    # Intercept loguru logs
    logger.remove()
    logger.add(PollingLogHandler(), format="{message}")

if __name__ == '__main__':
    setup_logger()

    api = Api()
    
    # 兼容 PyInstaller 打包路径
    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
    dist_path = os.path.join(base_dir, "gui_dist", "index.html")
    if not os.path.exists(dist_path):
        print(f"Frontend not found at {dist_path}. Please build the Vue project first.")
        sys.exit(1)

    window = webview.create_window('超星学习通 桌面客户端', url=dist_path, js_api=api, width=1024, height=768)
    webview.start(debug=False)
