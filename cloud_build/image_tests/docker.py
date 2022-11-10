from typing import List


def test_docker(image: str) -> List[str]:
    dockerfile = rf"""FROM scratch
ADD {image} /

RUN true > /etc/security/limits.d/50-defaults.conf

CMD ["/bin/bash"]"""

    with open('Dockerfile', 'w') as f:
        f.write(dockerfile)

    name = f'cloud_build_test_{abs(hash(image))}'
    test_commads = [
        'apt-get update',
        'apt-get install -y vim-console',
        '[ -L /var/run ]',
        '[ -L /var/lock ]'
    ]
    test_commad = " && ".join(test_commads)
    commands = [
        f'docker build --rm --tag={name} .',
        f"docker run --rm {name} /bin/sh -c "
        f"'{test_commad}'",
        f'docker image rm {name}',
    ]

    return commands
