import json
import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, Response, jsonify, render_template, request

from api.account_manager import AccountManager
from api.chaoxing_auth import ChaoXingQRManager
from api.config_manager import ConfigManager
from api.cookies import parse_cookie_string
from api.decode import parse_course_progress as _parse_course_progress_data
from api.task_runner import TaskStateHub

_course_progress_cache: dict[str, tuple[float, dict]] = {}
_courses_list_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 300.0


def _empty_progress(text: str = "待读取") -> dict:
    """构造未取到进度时的占位结果."""
    return {"finished": 0, "total": 0, "percent": 0, "text": text}


def _fetch_single_course_progress(
    item: dict,
    force: bool = False,
    session_cookies: dict | None = None,
    acc_key: str = "",
) -> dict:
    cid = str(item.get("courseId", ""))
    clazz_id = str(item.get("clazzId", ""))
    cpi = str(item.get("cpi", ""))
    if not cid or not clazz_id:
        return _empty_progress()

    cache_key = f"{acc_key}_{cid}_{clazz_id}" if acc_key else f"{cid}_{clazz_id}"
    now = time.time()
    if not force and cache_key in _course_progress_cache:
        cached_time, val = _course_progress_cache[cache_key]
        if now - cached_time < _CACHE_TTL:
            return val

    try:
        from api.base import SessionManager
        import requests
        s = requests.Session()
        cookie_dict = session_cookies if session_cookies is not None else dict(SessionManager.get_session().cookies)
        s.cookies.update(cookie_dict)
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction",
        })
        url = f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid={cid}&clazzid={clazz_id}&cpi={cpi}&ut=s"
        resp = s.get(url, timeout=12)
        resp.encoding = "utf-8"

        if resp.status_code != 200:
            return _empty_progress()

        if (
            "passport2.chaoxing.com" in resp.url
            or "login" in resp.url
            or "passport2.chaoxing.com" in resp.text
        ):
            return _empty_progress("待刷新")

        has_indicator = (
            "完成任务点" in resp.text
            or "chapter_unit" in resp.text
            or "catalog_ressbar_width" in resp.text
            or "studentcourse" in resp.text
        )
        if not has_indicator:
            return _empty_progress()

        fin, tot, pct = _parse_course_progress_data(resp.text)
        if tot > 0:
            text = f"{fin}/{tot} ({pct}%)"
        elif pct >= 100:
            text = "0/0 (100%)"
            pct = 100
        else:
            text = f"{pct}%"

        res = {"finished": fin, "total": tot, "percent": pct, "text": text}
        _course_progress_cache[cache_key] = (now, res)
        return res
    except Exception as e:
        try:
            from api.logger import logger
            logger.debug(f"读取课程完成度失败 {cid}/{clazz_id}: {e}")
        except Exception:
            pass

    return _empty_progress()


def create_app(test_config: dict | None = None) -> Flask:
    """构建本地 Web 控制台 Flask 应用服务."""
    import sys
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    template_dir = os.path.join(base_dir, "web", "templates")
    static_dir = os.path.join(base_dir, "web", "static")

    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=static_dir,
        static_url_path="/static"
    )

    if test_config:
        app.config.update(test_config)
    else:
        from api.logger import setup_webui_logging
        setup_webui_logging()

    accounts_dir = app.config.get("ACCOUNTS_DIR") or os.path.abspath("accounts")
    auto_import = not bool(app.config.get("TESTING"))
    account_mgr = AccountManager(accounts_dir=accounts_dir, auto_import_legacy=auto_import)
    auth_mgr = ChaoXingQRManager()
    hub = TaskStateHub()
    hub.set_web_mode(True)
    hub.set_task_running(False)
    hub.clear_workers()

    def get_active_config_manager() -> ConfigManager:
        active = account_mgr.get_active_account()
        if active and os.path.exists(active.get("path", "")):
            cfg_path = active["path"]
        elif app.config.get("DEFAULT_CONFIG_PATH") and os.path.exists(app.config["DEFAULT_CONFIG_PATH"]):
            cfg_path = app.config["DEFAULT_CONFIG_PATH"]
        elif os.path.exists("/config/config.ini"):
            cfg_path = "/config/config.ini"
        else:
            cfg_path = os.path.abspath("config.ini")
        tmpl_path = os.path.join(base_dir, "config_template.ini")
        if not os.path.exists(tmpl_path):
            tmpl_path = os.path.abspath("config_template.ini")
        return ConfigManager(config_path=cfg_path, template_path=tmpl_path)

    def _sync_hub_speed() -> None:
        try:
            cfg = get_active_config_manager().get_full_config()
            sp = cfg.get("common", {}).get("speed")
            if sp:
                hub.set_global_speed(float(sp))
        except Exception:
            pass

    def _apply_session_cookies(cookies_str: str) -> None:
        """把指定账号的 cookie 写入当前会话并同步全局倍速."""
        from api.base import SessionManager
        session = SessionManager.get_session()
        session.cookies.clear()
        session.cookies.update(parse_cookie_string(cookies_str))
        _sync_hub_speed()

    _sync_hub_speed()

    @app.route("/")
    def index():
        if os.path.exists(os.path.join(template_dir, "index.html")):
            return render_template("index.html")
        return "Web 控制台资源准备中", 200

    @app.route("/api/accounts", methods=["GET"])
    def list_accounts():
        accounts = account_mgr.list_accounts()
        active = account_mgr.get_active_account()
        active_id = active["id"] if active else None
        return jsonify({
            "accounts": accounts,
            "active_account": active_id,
        })

    @app.route("/api/accounts/switch", methods=["POST"])
    def switch_account():
        data = request.get_json() or {}
        acc_id = data.get("account_id")
        if not acc_id:
            return jsonify({"status": "error", "msg": "缺少 account_id 参数"}), 400
        active = account_mgr.switch_account(acc_id)
        if not active:
            return jsonify({"status": "error", "msg": "账号不存在"}), 404

        _apply_session_cookies(active.get("cookies", ""))
        return jsonify({"status": "success", "active_account": acc_id})

    @app.route("/api/accounts/alias", methods=["POST"])
    def set_account_alias():
        data = request.get_json(silent=True) or {}
        account_id = str(data.get("account_id", "")).strip()
        alias = str(data.get("alias", "")).strip()
        if not account_id:
            return jsonify({"status": "error", "msg": "缺少 account_id"}), 400
        if not account_mgr.set_alias(account_id, alias):
            return jsonify({"status": "error", "msg": "账号不存在或写入失败"}), 404
        return jsonify({
            "status": "success",
            "accounts": account_mgr.list_accounts(),
        })

    @app.route("/api/accounts/delete", methods=["POST"])
    def delete_account():
        data = request.get_json(silent=True) or {}
        account_id = str(data.get("account_id", "")).strip()
        if not account_id:
            return jsonify({"status": "error", "msg": "缺少 account_id"}), 400
        ok = account_mgr.delete_account(account_id)
        if ok:
            active = account_mgr.get_active_account()
            _apply_session_cookies(active.get("cookies", "") if active else "")
            return jsonify({
                "status": "success",
                "active_account": active["id"] if active else None,
                "accounts": account_mgr.list_accounts(),
            })
        return jsonify({"status": "error", "msg": "账号不存在或删除失败"}), 404

    @app.route("/api/auth/qr/create", methods=["POST"])
    def create_qr():
        res = auth_mgr.create_session()
        code = 200 if res.get("status") else 500
        return jsonify(res), code

    @app.route("/api/auth/qr/status/<session_id>", methods=["GET"])
    def check_qr(session_id: str):
        res = auth_mgr.check_status(session_id)
        if res.get("status") == "SUCCESS" and "cookies" in res:
            uid = res.get("uid") or session_id
            account_mgr.save_account(uid, {
                "cookies": res["cookies"],
                "use_cookies": "true",
            })
            _apply_session_cookies(res["cookies"])
        return jsonify(res)

    @app.route("/api/auth/login", methods=["POST"])
    def password_login():
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        if not username or not password:
            return jsonify({"status": "error", "msg": "用户名或密码不能为空"}), 400
        res = auth_mgr.login_with_password(username, password)
        if res.get("status") == "SUCCESS":
            uid = res.get("uid") or username
            account_mgr.save_account(uid, {
                "uid": uid,
                "username": username,
                "password": password,
                "cookies": res.get("cookies", ""),
                "use_cookies": "true",
            })
            if "cookies" in res:
                _apply_session_cookies(res["cookies"])
            else:
                _sync_hub_speed()
            return jsonify({"status": "success", "account_id": uid})
        return jsonify({"status": "error", "msg": res.get("msg", "登录失败")}), 401

    @app.route("/api/courses", methods=["GET"])
    def get_courses():
        active = account_mgr.get_active_account()
        if not active:
            return jsonify({"courses": [], "selected_ids": []})

        cfg_mgr = get_active_config_manager()
        selected_ids = set(cfg_mgr.get_course_list())
        force = request.args.get("refresh", "false").lower() in ("true", "1")
        acc_key = str(active.get("uid") or active.get("username") or active.get("id") or "")
        now = time.time()

        courses = []
        if not force and acc_key in _courses_list_cache:
            cached_time, cached_courses = _courses_list_cache[acc_key]
            if now - cached_time < _CACHE_TTL:
                courses = [dict(c) for c in cached_courses]

        if not courses:
            cookies_str = active.get("cookies", "")
            if cookies_str:
                try:
                    from api.base import Account, Chaoxing
                    account = Account(active.get("username", ""), active.get("password", ""))
                    cx = Chaoxing(account=account, cookies=cookies_str)
                    raw_courses = cx.get_course_list()
                    for c in raw_courses:
                        cid = str(c.get("courseId", ""))
                        courses.append({
                            "courseId": cid,
                            "clazzId": str(c.get("clazzId", "")),
                            "cpi": str(c.get("cpi", "")),
                            "title": c.get("title", ""),
                            "teacher": c.get("teacher", ""),
                            "status": c.get("status", "进行中"),
                            "is_ended": c.get("is_ended", False),
                            "progress": 0,
                            "selected": cid in selected_ids,
                        })
                except Exception as e:
                    hub.append_log("ERROR", f"获取课程列表失败: {e}")

            if not courses and active.get("username") and active.get("password"):
                try:
                    from api.base import Account, Chaoxing
                    account = Account(active["username"], active["password"])
                    cx = Chaoxing(account=account, cookies="")
                    login_res = cx.login(login_with_cookies=False)
                    if login_res.get("status"):
                        session = cx.get_session()
                        new_cookies = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
                        account_mgr.save_account(active.get("uid") or active["username"], {
                            "uid": active.get("uid", ""),
                            "username": active["username"],
                            "password": active["password"],
                            "cookies": new_cookies,
                            "use_cookies": "true",
                        })
                        raw_courses = cx.get_course_list()
                        for c in raw_courses:
                            cid = str(c.get("courseId", ""))
                            courses.append({
                                "courseId": cid,
                                "clazzId": str(c.get("clazzId", "")),
                                "cpi": str(c.get("cpi", "")),
                                "title": c.get("title", ""),
                                "teacher": c.get("teacher", ""),
                                "status": c.get("status", "进行中"),
                                "is_ended": c.get("is_ended", False),
                                "progress": 0,
                                "selected": cid in selected_ids,
                            })
                except Exception as e:
                    hub.append_log("ERROR", f"自动密码重登获取课程失败: {e}")

            if courses:
                _courses_list_cache[acc_key] = (now, [dict(c) for c in courses])

        for c in courses:
            c["selected"] = str(c.get("courseId", "")) in selected_ids
            cache_key = f"{acc_key}_{c['courseId']}_{c['clazzId']}" if acc_key else f"{c['courseId']}_{c['clazzId']}"
            cached_entry = _course_progress_cache.get(cache_key) if not force else None
            if cached_entry and now - cached_entry[0] < _CACHE_TTL:
                cached_data = cached_entry[1]
                c["progress"] = cached_data["percent"]
                c["progress_text"] = cached_data["text"]
            else:
                c["progress"] = None
                c["progress_text"] = "待读取"

        return jsonify({"courses": courses, "selected_ids": list(selected_ids)})

    @app.route("/api/courses/progress", methods=["GET"])
    def get_courses_progress():
        active = account_mgr.get_active_account()
        if not active:
            return jsonify({"progress": {}})

        force = request.args.get("refresh", "false").lower() in ("true", "1")
        acc_key = str(active.get("uid") or active.get("username") or active.get("id") or "")
        now = time.time()

        raw_courses = []
        if acc_key in _courses_list_cache:
            cached_time, cached_courses = _courses_list_cache[acc_key]
            if now - cached_time < _CACHE_TTL:
                raw_courses = cached_courses

        if not raw_courses:
            cookies_str = active.get("cookies", "")
            from api.base import Chaoxing
            cx = Chaoxing(cookies=cookies_str)
            try:
                raw_courses = cx.get_course_list()
                if raw_courses:
                    _courses_list_cache[acc_key] = (now, raw_courses)
            except Exception:
                raw_courses = []

        progress_map = {}
        session_cookies = parse_cookie_string(active.get("cookies", ""))

        with ThreadPoolExecutor(max_workers=min(5, max(1, len(raw_courses)))) as pool:
            futures = [
                pool.submit(_fetch_single_course_progress, c, force=force, session_cookies=session_cookies, acc_key=acc_key)
                for c in raw_courses
            ]
            for c, f in zip(raw_courses, futures):
                cid = str(c.get("courseId", ""))
                clazz_id = str(c.get("clazzId", ""))
                try:
                    res_val = f.result()
                except Exception:
                    res_val = _empty_progress()
                progress_map[cid] = res_val
                if clazz_id:
                    progress_map[f"{cid}_{clazz_id}"] = res_val

        return jsonify({"progress": progress_map})

    @app.route("/api/config/course_list", methods=["POST"])
    def save_course_list():
        data = request.get_json() or {}
        course_ids = data.get("course_list", [])
        cfg_mgr = get_active_config_manager()
        cfg_mgr.set_course_list(course_ids)
        return jsonify({"status": "success"})

    @app.route("/api/config/full", methods=["GET"])
    def get_full_config():
        cfg_mgr = get_active_config_manager()
        cfg = cfg_mgr.get_full_config()
        for secret in ("password", "cookies"):
            cfg.get("common", {}).pop(secret, None)
        return jsonify(cfg)

    @app.route("/api/config/full", methods=["POST"])
    def save_full_config():
        data = request.get_json() or {}
        if isinstance(data.get("common"), dict):
            data["common"].pop("password", None)
            data["common"].pop("cookies", None)
        cfg_mgr = get_active_config_manager()
        cfg_mgr.update_full_config(data)
        _sync_hub_speed()
        return jsonify({"status": "success"})

    @app.route("/api/speed/global", methods=["POST"])
    def set_global_speed():
        data = request.get_json() or {}
        speed = data.get("speed", 1.0)
        hub.set_global_speed(float(speed))
        if not app.config.get("TESTING"):
            cfg_mgr = get_active_config_manager()
            if os.path.exists(cfg_mgr.config_path):
                try:
                    cfg_mgr.update_full_config({"common": {"speed": hub.get_global_speed()}})
                except Exception as e:
                    hub.append_log("WARNING", f"保存全局倍速到配置文件失败: {e}")
        return jsonify({"status": "success", "global_speed": hub.get_global_speed()})

    @app.route("/api/speed/worker", methods=["POST"])
    def set_worker_speed():
        data = request.get_json() or {}
        worker_id = data.get("worker_id")
        speed = data.get("speed", 1.0)
        if not worker_id:
            return jsonify({"status": "error", "msg": "缺少 worker_id"}), 400
        hub.set_worker_speed(worker_id, float(speed))
        return jsonify({
            "status": "success",
            "worker_id": worker_id,
            "speed": hub.get_effective_speed(worker_id),
        })

    @app.route("/api/status", methods=["GET"])
    def get_status():
        return jsonify(hub.get_snapshot())

    @app.route("/api/task/start", methods=["POST"])
    def start_task():
        data = request.get_json(silent=True) or {}
        active = account_mgr.get_active_account()
        if not active:
            return jsonify({"status": "error", "msg": "未选择或未登录账号"}), 400

        cfg_mgr = get_active_config_manager()
        full_cfg = cfg_mgr.get_full_config()

        checked_ids = data.get("course_list")
        if isinstance(checked_ids, list):
            course_list = [str(x).strip() for x in checked_ids if str(x).strip()]
            if course_list:
                cfg_mgr.set_course_list(course_list)
        else:
            course_list = cfg_mgr.get_course_list()

        if not course_list:
            acc_key = str(active.get("uid") or active.get("username") or active.get("id") or "")
            all_raw = []
            if acc_key in _courses_list_cache:
                all_raw = _courses_list_cache[acc_key][1]
            else:
                from api.base import Chaoxing
                cx = Chaoxing(cookies=active.get("cookies", ""))
                try:
                    all_raw = cx.get_course_list()
                    _courses_list_cache[acc_key] = (time.time(), all_raw)
                except Exception:
                    all_raw = []

            course_list = [str(c["courseId"]) for c in all_raw if not c.get("is_ended")]
            if not course_list:
                course_list = [str(c["courseId"]) for c in all_raw]

        if not course_list:
            return jsonify({"status": "error", "msg": "当前账号下未找到可用课程"}), 400

        common_config = full_cfg.get("common", {})
        common_config["course_list"] = course_list
        common_config["username"] = active.get("username") or active.get("uid") or active.get("id") or ""
        common_config["speed"] = hub.get_global_speed() or float(common_config.get("speed", 1.0))

        has_cookies = bool(active.get("cookies"))
        common_config["use_cookies"] = has_cookies
        if has_cookies:
            common_config["cookies"] = active.get("cookies", "")
        if active.get("password"):
            common_config["password"] = active.get("password", "")

        if not has_cookies and not active.get("password"):
            return jsonify({"status": "error", "msg": "当前账号缺少有效登录凭据，请重新登录"}), 400

        tiku_config = full_cfg.get("tiku", {})
        notification_config = full_cfg.get("notification", {})
        config_path = active.get("path")

        from main import start_study_task
        started = start_study_task(common_config, tiku_config, notification_config, config_path)
        if not started:
            return jsonify({"status": "error", "msg": "任务已在运行中"}), 409
        return jsonify({"status": "success", "course_count": len(course_list)})

    @app.route("/api/task/stop", methods=["POST"])
    def stop_task():
        from main import stop_study_task
        stopped = stop_study_task()
        return jsonify({"status": "success" if stopped else "not_running"})

    @app.route("/api/manual/pending", methods=["GET"])
    def get_manual_pending():
        return jsonify({"questions": hub.get_pending_questions()})

    @app.route("/api/manual/answer", methods=["POST"])
    def submit_manual_answer():
        data = request.get_json() or {}
        prompt_id = data.get("prompt_id")
        answer = data.get("answer")
        if not prompt_id:
            return jsonify({"status": "error", "msg": "缺少 prompt_id"}), 400
        ok = hub.submit_manual_answer(prompt_id, str(answer) if answer is not None else "")
        if ok:
            return jsonify({"status": "success"})
        return jsonify({"status": "not_found", "msg": "作答会话已结束或不存在"}), 404

    @app.route("/api/manual/skip", methods=["POST"])
    def skip_manual_answer():
        data = request.get_json() or {}
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            return jsonify({"status": "error", "msg": "缺少 prompt_id"}), 400
        ok = hub.skip_manual_answer(prompt_id)
        if ok:
            return jsonify({"status": "success"})
        return jsonify({"status": "not_found", "msg": "作答会话已结束或不存在"}), 404

    @app.route("/api/log/level", methods=["GET", "POST"])
    def log_level_endpoint():
        from api.logger import get_log_level, set_log_level
        if request.method == "POST":
            data = request.get_json() or {}
            lvl = str(data.get("level", "")).upper()
            if lvl in ("TRACE", "DEBUG", "INFO", "WARNING", "ERROR"):
                set_log_level(lvl)
                return jsonify({"status": "success", "level": get_log_level()})
            return jsonify({"status": "error", "msg": "无效的日志级别"}), 400
        return jsonify({"level": get_log_level()})

    @app.route("/api/events", methods=["GET"])
    def sse_events():
        def event_stream():
            q = hub.subscribe_events()
            try:
                snapshot = hub.get_snapshot()
                yield f"event: STATUS_UPDATE\ndata: {json.dumps(snapshot)}\n\n"
                while True:
                    try:
                        msg = q.get(timeout=25.0)
                        event_type = msg["event"]
                        data_json = json.dumps(msg["data"])
                        yield f"event: {event_type}\ndata: {data_json}\n\n"
                    except queue.Empty:
                        yield ": keep-alive\n\n"
            finally:
                hub.unsubscribe_events(q)

        return Response(event_stream(), mimetype="text/event-stream")

    return app
