# -*- coding: utf-8 -*-
"""容错的 ini 读取工具

配置文件是用户可以手改的，写坏（比如节标题之前冒出一行 key=value）
时不能直接抛异常让程序崩掉，而是尽量抢救还能用的内容。
"""
import configparser


def read_config_file(config_path, strict=False):
    """
    读取 ini 文件，返回 (ConfigParser, broken)。

    正常情况下 broken=False。
    文件被写坏时，会丢掉破坏结构的行再读一次，并返回 broken=True，
    调用方可以据此提示用户。
    """
    config = configparser.ConfigParser(strict=strict)
    try:
        config.read(config_path, encoding="utf8")
        return config, False
    except (configparser.Error, UnicodeDecodeError, OSError):
        pass

    kept = []
    seen_section = False
    try:
        with open(config_path, encoding="utf8", errors="replace") as fp:
            for line in fp:
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    seen_section = True
                    kept.append(line)
                elif not stripped or stripped.startswith(("#", ";")) or seen_section:
                    kept.append(line)
    except OSError:
        return config, True

    try:
        config.read_string("".join(kept))
    except configparser.Error:
        pass
    return config, True
