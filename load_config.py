import json,os


def load():
    if os.path.exists('config'):
        if os.path.exists('config/general.json'):
            with open('config/general.json','r') as f:
                config = json.loads(f.read())
            speed = config['speed']
            return speed
        else:
            with open('config/general.json', 'w') as f:
                dic = {}
                dic['speed'] = 1
                json.dump(dic,f)
            return 1
    else:
        os.mkdir('config')
        with open('config/general.json', 'w') as f:
            dic = {}
            dic['speed'] = 1
            json.dump(dic, f)
        return 1