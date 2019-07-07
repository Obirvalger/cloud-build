from typing import List


def test_docker(image: str) -> List[str]:
    dockerfile = rf"""FROM scratch
ADD {image} /

RUN true > /etc/security/limits.d/50-defaults.conf
RUN apt-get update && \
        apt-get install -y vim-console; \
        rm -f /var/cache/apt/archives/*.rpm \
              /var/cache/apt/*.bin \
              /var/lib/apt/lists/*.*

CMD ["/bin/bash"]"""

    with open('Dockerfile', 'w') as f:
        f.write(dockerfile)

    name = 'cloud_build_test_docker_image'
    commands = [
        f'docker build --rm --tag={name} .',
        f'docker run --rm {name}',
        f'docker image rm {name}',
    ]

    return commands
