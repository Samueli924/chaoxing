from celery import Celery, Task
from flask import Flask


def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app


if __name__ == '__main__':
    app = Flask(__name__)
    app.config.from_mapping(
        CELERY=dict(
            broker_url="db+sqlite:///celeryresults.sqlite3",
            result_backend="sqlite:///celeryresults.sqlite3",
            task_ignore_result=True,
        ),
    )
    celery_app = celery_init_app(app)