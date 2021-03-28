import json


def load():
    with open('config/general.json') as f:
        config = json.loads(f.read())
    speed = config['speed']
    return speed