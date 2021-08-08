from typing import Dict

import re
import subprocess


def rename(rename_dict: Dict[str, str], name: str) -> str:
    if regex := rename_dict.get('regex'):
        to = rename_dict['to']
        name = re.sub(regex, to, name)
    elif prog := rename_dict.get('prog'):
        name = subprocess.run(
            [prog, name],
            stdout=subprocess.PIPE,
        ).stdout.decode().strip()
    else:
        to = rename_dict['to']
        name = to

    return name
