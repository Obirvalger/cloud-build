from typing import List


def test_docker(image: str) -> List[str]:
    dockerfile = rf"""FROM scratch
ADD {image} /

RUN true > /etc/security/limits.d/50-defaults.conf

CMD ["/bin/bash"]"""

    with open('Dockerfile', 'w') as f:
        f.write(dockerfile)

    name = f'cloud_build_test_{abs(hash(image))}'
    commands = [
        f'docker build --rm --tag={name} .',
        f"docker run --rm {name} /bin/sh -c "
        "'apt-get update && apt-get install -y vim-console'",
        f'docker image rm {name}',
    ]

    return commands
